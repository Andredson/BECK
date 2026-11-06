"""The ``beck`` command: connects the parts. Only this module turns errors into exit codes."""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml

from beck import __version__
from beck.errors import BeckError, ConfigError, ReportNotFoundError, TransportError, UsageError
from beck.executor import execute
from beck.frontends import get_adapter
from beck.frontends.base import FrontendAdapter
from beck.hashing import scan
from beck.matcher import plan
from beck.models import MissingBios, RunResult
from beck.output.console import LOGGER_NAME, ConsoleRenderer, configure_logging
from beck.output.json import JsonRenderer, write_rejected_command
from beck.targets import URL_FORM, parse_smb_url
from beck.transports.base import Transport
from beck.transports.local import LocalTransport
from beck.transports.smb import SmbTransport

DESCRIPTION = "Match your BIOS files by MD5 and send them to the right folder on your Recalbox."

EXAMPLES = """\
examples:
  beck check                  copy the matching files to your device
  beck scan                   list your local files and their MD5s
  beck report                 list what your device is missing

See docs/cli.md for every option, the exit codes, and what gets deleted.
"""

COMMANDS = {
    "check": ("Copy your matching BIOS files to the device.", "example:\n  beck check\n"),
    "scan": ("List your local BIOS files with their MD5s.", "example:\n  beck scan\n"),
    "report": ("List the BIOS files the device reports as missing.", "example:\n  beck report\n"),
}

SMB_SETTINGS = ("server", "port", "user", "passwd")
DEFAULT_FRONTEND = "recalbox"
REPORT_FILE_HELP = "read this local copy of the report, not the one on the target"

Renderer = ConsoleRenderer | JsonRenderer


class _Parser(argparse.ArgumentParser):
    """With ``--json``, a bad command line must still give a document on stdout."""

    def __init__(self, *args: Any, json_errors: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.json_errors = json_errors

    def error(self, message: str) -> NoReturn:
        if self.json_errors:
            raise UsageError(message)
        super().error(message)


def _asks_for_json(argv: list[str]) -> bool:
    """Whether a command line asks for JSON. Needed before parsing, which can fail.

    Like argparse, this accepts a shortened option: ``--js``.
    """
    return any(len(arg) > 2 and "--json".startswith(arg) for arg in argv)


def load_legacy_config(file: Path) -> dict[str, Any]:
    """The ``smb`` section of ``config/config.yml``. TOML replaces this file in stage 07."""
    try:
        with file.open(encoding="utf-8") as config_file:
            data = yaml.safe_load(config_file)
    except FileNotFoundError as e:
        raise ConfigError(
            f"{file} not found. Copy config/config.example.yml to config/config.yml and fill it in."
        ) from e
    except yaml.YAMLError as e:
        raise ConfigError(f"{file} isn't valid YAML: {e}") from e

    try:
        settings: dict[str, Any] = data["smb"]
        for name in SMB_SETTINGS:
            settings[name]
    except (KeyError, TypeError) as e:
        raise ConfigError(f"{file} needs an smb section with {', '.join(SMB_SETTINGS)}") from e

    return settings


def _open_target(args: argparse.Namespace, base_dir: Path) -> Transport:
    """The transport for the chosen target. With none chosen, it comes from the config file."""
    if args.target_dir is not None:
        return LocalTransport(Path(args.target_dir))
    if args.target is not None:
        target = parse_smb_url(args.target)
        # No password: the one in the config file belongs to its own server, and sending it to
        # whatever host this flag names would leak it. Stage 07 adds passwords for targets.
        return SmbTransport(
            target.host, target.port, target.share, target.user, "", root=target.root
        )
    settings = load_legacy_config(base_dir / "config" / "config.yml")
    return SmbTransport(
        host=settings["server"],
        port=settings["port"],
        share="bios",
        user=settings["user"],
        password=settings["passwd"],
    )


def _entries_from_file(adapter: FrontendAdapter, report_file: str) -> list[MissingBios]:
    """Parse a local copy of the report."""
    try:
        raw = Path(report_file).read_bytes()
    except OSError as e:
        raise ReportNotFoundError(f"Can't read the report {report_file}: {e.strerror}") from e
    return adapter.parse_report(raw.decode("utf-8", errors="replace"))


def _entries_from_target(adapter: FrontendAdapter, transport: Transport) -> list[MissingBios]:
    """Parse the report on the target."""
    if not transport.exists(adapter.report_path):
        raise ReportNotFoundError(
            f"{adapter.report_path} not found on {transport.describe()}. "
            "Generate the report on the device first."
        )
    raw = transport.read_bytes(adapter.report_path)
    return adapter.parse_report(raw.decode("utf-8", errors="replace"))


def _source_folder(args: argparse.Namespace, base_dir: Path) -> Path:
    """The folder of BIOS files. One the user named must exist, so a typo can't read as empty."""
    if args.source is None:
        return base_dir / "bios"
    source = Path(args.source)
    if not source.is_dir():
        raise UsageError(f"The source folder {source} doesn't exist")
    return source


def _confirm_deletion(preview: RunResult, renderer: Renderer) -> None:
    """Ask before deleting. Without a terminal to ask on, deleting needs --yes."""
    count = len(preview.deleted)
    if not renderer.can_ask():
        raise UsageError(
            f"BECK would delete {count} local files, and can't ask here. Nothing was changed. "
            "To see them, use --dry-run. To confirm, use --yes."
        )
    if not renderer.confirm_deletion(preview):
        raise UsageError("Nothing was changed, because you didn't confirm the deletion.")


def _run_check(args: argparse.Namespace, base_dir: Path, renderer: Renderer) -> int:
    source = _source_folder(args, base_dir)
    adapter = get_adapter(args.frontend)

    def ended_early(entries: list[MissingBios]) -> int:
        """Nothing to upload. The plan still says what's missing and incorrect."""
        renderer.ended_early(RunResult(plan=plan(entries, []), dry_run=args.dry_run))
        return 0

    transport = _open_target(args, base_dir)
    renderer.opened(transport.url())
    with transport:
        if args.report_file is not None:
            entries = _entries_from_file(adapter, args.report_file)
        else:
            entries = _entries_from_target(adapter, transport)
        if not entries:
            renderer.nothing_missing()
            return ended_early(entries)
        incorrect = [entry for entry in entries if entry.incorrect]
        if not args.overwrite:
            renderer.incorrect(incorrect)
        to_fill = {e.target for e in entries if args.overwrite or not e.incorrect}
        if not to_fill:
            return ended_early(entries)
        renderer.missing_count(len(to_fill))

        scanned = scan(source)
        renderer.unreadable(scanned.unreadable)
        if not scanned.files:
            if args.overwrite:
                renderer.incorrect(incorrect)
            renderer.no_files(source)
            return ended_early(entries)
        renderer.files_found(len(scanned.files))

        built = plan(entries, scanned.files, replace_incorrect=args.overwrite)
        options = {
            "overwrite": args.overwrite,
            "move": args.move,
            "clean_unmatched": args.clean_unmatched,
        }
        if args.dry_run:
            result = execute(built, transport, dry_run=True, **options)
        else:
            if (args.move or args.clean_unmatched) and not args.yes:
                # The preview only reads, so that a refusal leaves everything as it was.
                preview = execute(built, transport, dry_run=True, **options)
                if preview.deleted:
                    _confirm_deletion(preview, renderer)
            result = execute(built, transport, dry_run=False, **options)

    if args.overwrite:
        renderer.incorrect(list(result.plan.incorrect))
    renderer.result(result)
    return TransportError.exit_code if result.errors else 0


def _run_report(args: argparse.Namespace, base_dir: Path, renderer: Renderer) -> int:
    """List what the report says. It never writes anything, and a local copy needs no target."""
    adapter = get_adapter(args.frontend)
    if args.report_file is not None:
        entries = _entries_from_file(adapter, args.report_file)
    else:
        transport = _open_target(args, base_dir)
        renderer.opened(transport.url())
        with transport:
            entries = _entries_from_target(adapter, transport)
    renderer.report(entries)
    return 0


def _run_scan(args: argparse.Namespace, base_dir: Path, renderer: JsonRenderer) -> int:
    """List the local files. It uses no network and writes nothing."""
    renderer.scan(scan(_source_folder(args, base_dir)))
    return 0


def _add_global_options(parser: argparse.ArgumentParser, *, on_a_command: bool) -> None:
    """Options that work before or after the command.

    On a command, the default must be SUPPRESS. Otherwise, argparse sets it after reading the part
    before the command, so ``beck --no-color check`` would lose the flag.
    """
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS if on_a_command else False,
        help="don't use colors, the same as setting NO_COLOR",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS if on_a_command else False,
        help="print one JSON document on stdout, and never ask anything (see docs/json-output.md)",
    )


def _add_target_options(parser: argparse.ArgumentParser) -> Any:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--target", metavar="URL", help=f"an SMB target: {URL_FORM}")
    group.add_argument(
        "--target-dir",
        metavar="DIR",
        help="a folder: a mounted SD card or USB drive, or the device itself",
    )
    return group


def _build_parser(*, json_errors: bool = False) -> argparse.ArgumentParser:
    parser = _Parser(
        json_errors=json_errors,
        prog="beck",
        description=DESCRIPTION,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"beck {__version__}")
    _add_global_options(parser, on_a_command=False)
    commands = parser.add_subparsers(dest="command", title="commands", metavar="<command>")
    for name, (summary, example) in COMMANDS.items():
        command = commands.add_parser(
            name,
            json_errors=json_errors,
            help=summary,
            description=summary,
            epilog=example,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        _add_global_options(command, on_a_command=True)
        if name in ("check", "scan"):
            command.add_argument(
                "--source", metavar="DIR", help="your folder of BIOS files (default: ./bios)"
            )
        if name == "check":
            group = _add_target_options(command)
            command.add_argument("--report-file", metavar="FILE", help=REPORT_FILE_HELP)
            command.add_argument(
                "--overwrite",
                action="store_true",
                help="replace files already on the device, even ones the report calls INCORRECT",
            )
            command.add_argument(
                "--dry-run",
                action="store_true",
                help="show the plan, including what would be deleted, and change nothing",
            )
            command.add_argument(
                "--move",
                action="store_true",
                help="delete a local file once it's uploaded to all its targets and sizes match",
            )
            command.add_argument(
                "--clean-unmatched",
                action="store_true",
                help="delete local files the current report doesn't ask for (read docs/cli.md)",
            )
            command.add_argument(
                "--yes", action="store_true", help="confirm deletions without asking"
            )
            command.add_argument(
                "--frontend",
                default=DEFAULT_FRONTEND,
                metavar="NAME",
                help=f"the kind of device (default: {DEFAULT_FRONTEND})",
            )
        if name == "report":
            group = _add_target_options(command)
            group.add_argument("--report-file", metavar="FILE", help=REPORT_FILE_HELP)
    parser.set_defaults(
        target=None,
        target_dir=None,
        frontend=DEFAULT_FRONTEND,
        source=None,
        report_file=None,
        overwrite=False,
        dry_run=False,
        move=False,
        clean_unmatched=False,
        yes=False,
    )
    return parser


def main(argv: list[str] | None = None, *, base_dir: Path | None = None) -> int:
    """Run BECK and return its exit code. Settings and files are found under ``base_dir``.

    With no ``base_dir``, that's the current directory: an installed tool has no folder of its own.
    """
    parser = _build_parser(json_errors=_asks_for_json(sys.argv[1:] if argv is None else argv))
    try:
        args = parser.parse_args(argv)
    except UsageError as error:
        write_rejected_command(str(error))
        return error.exit_code
    logger = configure_logging()
    renderer: Renderer
    if args.json:
        renderer = JsonRenderer(
            args.command or "check", frontend=args.frontend, dry_run=args.dry_run
        )
    else:
        environ = {**os.environ, "NO_COLOR": "1"} if args.no_color else None
        renderer = ConsoleRenderer(environ=environ)
    if args.command is None:
        logger.warning("Hint: use 'beck check'. Running beck with no command is going away.")

    try:
        folder = Path.cwd() if base_dir is None else base_dir
        if args.command == "scan":
            if isinstance(renderer, ConsoleRenderer):  # step 06.11 adds the human output
                raise UsageError("beck scan isn't available yet")
            return _run_scan(args, folder, renderer)
        if args.command == "report":
            return _run_report(args, folder, renderer)
        return _run_check(args, folder, renderer)
    except BeckError as error:
        renderer.error(error)
        return error.exit_code
    except Exception:
        # A bug in BECK: the traceback goes to stderr, for the bug report.
        logging.getLogger(LOGGER_NAME).exception("Unexpected error")
        renderer.unexpected_error()
        return 1
