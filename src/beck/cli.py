# SPDX-License-Identifier: GPL-3.0-only
"""The ``beck`` command: connects the parts. Only this module turns errors into exit codes."""

import argparse
import logging
import os
import platform
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

from beck import __version__
from beck.config import (
    DEFAULT_FRONTEND,
    Flags,
    Settings,
    find_config,
    load,
    resolve,
    write_template,
)
from beck.credentials import password_for
from beck.errors import BeckError, ConfigError, ReportNotFoundError, TransportError, UsageError
from beck.executor import execute
from beck.exporter import export
from beck.frontends import get_adapter
from beck.frontends.base import FrontendAdapter
from beck.hashing import scan
from beck.legacy_config import migration_notice, read_legacy
from beck.matcher import plan
from beck.models import ItemError, MissingBios, Plan, RunResult, ScanResult
from beck.output import LOGGER_NAME, escaped_for_terminal, finish_output
from beck.output.console import ConsoleRenderer, configure_logging
from beck.output.json import JsonRenderer, write_rejected_command
from beck.redact import add_secret, forget_secrets, redact
from beck.targets import URL_FORM, parse_smb_url
from beck.transports.base import Transport
from beck.transports.local import LocalTransport
from beck.transports.smb import DEFAULT_TIMEOUT, SmbTransport

DESCRIPTION = "Match your BIOS files by MD5 and send them to the right folder on your Recalbox."

EXAMPLES = """\
examples:
  beck check                  copy the matching files to your device
  beck scan                   list your local files and their MD5s
  beck report                 list what your device is missing
  beck export ~/bios-backup   copy the .rom and .bin files on your device to a folder
  beck config init            create a settings file

See docs/cli.md for every option, the exit codes, and what gets deleted.
"""

COMMANDS = {
    "check": ("Copy your matching BIOS files to the device.", "example:\n  beck check\n"),
    "scan": ("List your local BIOS files with their MD5s.", "example:\n  beck scan\n"),
    "report": ("List the BIOS files the device reports as missing.", "example:\n  beck report\n"),
    "export": (
        "Copy the .rom and .bin files on the device to a folder here.",
        "example:\n  beck export ~/bios-backup --dry-run\n",
    ),
    "config": ("Find, create or show BECK's settings.", "example:\n  beck config show\n"),
}
CONFIG_ACTIONS = {
    "path": "print which settings file BECK reads, and why",
    "init": "create that settings file",
    "show": "print the settings a run would use, and where each comes from",
}

EXPORT_DESCRIPTION = """\
Copy every .rom and .bin file in the device's BIOS folder to DIR, in the same folders. It never
replaces a file in DIR, and changes nothing on the device.

It isn't a complete backup: BIOS files of other kinds, such as .zip, .img or the Amiga kick files,
are left out, and so are .rom and .bin files that aren't BIOS files. The result says how many it
left. These are real BIOS files, so never commit them to a git repository."""

FAILED_IF_MISSING_EXIT_CODE = 5
REPORT_FILE_HELP = "read this local copy of the report, not the one on the target"

Renderer = ConsoleRenderer | JsonRenderer
Entries = tuple[list[MissingBios], list[ItemError]]  # what a report asks for, and what it refused

_log = logging.getLogger(__name__)


class _Parser(argparse.ArgumentParser):
    """With ``--json``, a bad command line must still give a document on stdout."""

    def __init__(self, *args: Any, json_errors: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.json_errors = json_errors

    def error(self, message: str) -> NoReturn:
        if self.json_errors:
            raise UsageError(message)
        super().error(escaped_for_terminal(redact(message)))  # it repeats what it was given


def _asks_for_json(argv: list[str]) -> bool:
    """Whether a command line asks for JSON. Needed before parsing, which can fail.

    Like argparse, this accepts a shortened option: ``--js``.
    """
    return any(len(arg) > 2 and "--json".startswith(arg) for arg in argv)


def _load_settings(args: argparse.Namespace) -> Settings:
    location = find_config(args.config, os.environ)
    _log.debug("Settings file: %s (%s)", location.path, location.source)
    file = load(location.path, may_be_missing=location.source == "default")
    flags = Flags(
        target=args.target, target_dir=args.target_dir, source=args.source, frontend=args.frontend
    )
    return resolve(flags, os.environ, file)


def _open_target(settings: Settings, password: Callable[[str, str], str]) -> Transport:
    """The transport for the chosen target. It connects when it's entered, not here."""
    if settings.target_dir is not None:
        return LocalTransport(settings.target_dir)
    if settings.target_url is None:
        raise ConfigError(
            "BECK has no target. Use --target or --target-dir, set BECK_TARGET or BECK_TARGET_DIR, "
            "or name one in the settings file: to create it, run beck config init."
        )
    target = parse_smb_url(settings.target_url)
    user = target.user or settings.smb_user
    return SmbTransport(
        target.host,
        target.port,
        target.share,
        user,
        password(user, target.host),
        timeout=settings.smb_timeout or DEFAULT_TIMEOUT,
        root=target.root,
    )


def _connect_to_target(settings: Settings, renderer: Renderer) -> Transport:
    """The transport for a run that connects: the only thing that may ask for a password."""

    def password(user: str, host: str) -> str:
        return password_for(user, host, settings.smb_password, can_ask=renderer.can_ask())

    return _open_target(settings, password)


def _entries_from_file(adapter: FrontendAdapter, report_file: str) -> Entries:
    """Parse a local copy of the report."""
    try:
        raw = Path(report_file).read_bytes()
    except OSError as e:
        raise ReportNotFoundError(f"Can't read the report {report_file}: {e.strerror}") from e
    return _parsed_report(adapter, raw)


def _entries_from_target(adapter: FrontendAdapter, transport: Transport) -> Entries:
    """Parse the report on the target."""
    if not transport.exists(adapter.report_path):
        raise ReportNotFoundError(
            f"{adapter.report_path} not found on {transport.describe()}. "
            "Generate the report on the device first."
        )
    return _parsed_report(adapter, transport.read_bytes(adapter.report_path))


def _parsed_report(adapter: FrontendAdapter, raw: bytes) -> Entries:
    text = raw.decode("utf-8", errors="replace")
    entries, rejected = adapter.parse_report(text), adapter.rejected_entries(text)
    _log.debug(
        "Report: %d entries, %d refused, from %d bytes", len(entries), len(rejected), len(raw)
    )
    return entries, rejected


def _scan_with_progress(source: Path, renderer: Renderer) -> ScanResult:
    started = time.monotonic()
    scanned = scan(source, renderer.hashing)
    renderer.hashing_done()
    _log.debug(
        "Scanned %s: %d files, %d can't be read, in %.3f s",
        source,
        len(scanned.files),
        len(scanned.unreadable),
        time.monotonic() - started,
    )
    return scanned


def _log_plan(built: Plan) -> None:
    _log.debug(
        "Plan: %d uploads, %d folders, %d duplicates, %d unmatched, %d already filled, "
        "%d still missing, %d incorrect",
        len(built.uploads),
        len(built.directories),
        len(built.duplicates),
        len(built.unmatched),
        len(built.already_filled),
        len(built.still_missing),
        len(built.incorrect),
    )
    for upload in built.uploads:
        _log.debug("Plan: %s -> %s", upload.source.relative, upload.target)


def _log_run(result: RunResult, started: float) -> None:
    _log.debug(
        "Ran in %.3f s: %d uploaded, %d kept, %d deleted, %d errors",
        time.monotonic() - started,
        len(result.completed),
        len(result.kept),
        len(result.deleted),
        len(result.errors),
    )


def _source_folder(settings: Settings, base_dir: Path) -> Path:
    """The folder of BIOS files. One the user named must exist, so a typo can't read as empty."""
    source = settings.source_dir
    if source is None:
        return base_dir / "bios"
    if not source.is_dir():
        raise UsageError(f"The source folder {source} doesn't exist")
    return source


def _confirm_deletion(preview: RunResult, renderer: Renderer) -> None:
    """Ask before deleting. Without a terminal to ask on, deleting needs --yes."""
    cant_ask = UsageError(
        f"BECK would delete {len(preview.deleted)} local files, and can't ask here. Nothing was "
        "changed. To see them, use --dry-run. To confirm, use --yes."
    )
    if not renderer.can_ask():
        raise cant_ask
    try:
        confirmed = renderer.confirm_deletion(preview)
    except OSError as e:  # the question or the answer didn't get through
        raise cant_ask from e
    if not confirmed:
        raise UsageError("Nothing was changed, because you didn't confirm the deletion.")


def _failing_if_missing(args: argparse.Namespace, result: RunResult) -> list[MissingBios]:
    """The entries ``--fail-if-missing`` fails on: required, or the report doesn't say.

    A required INCORRECT file counts, because the device still can't use it, and a failed item wins,
    because the run didn't do all it could (DEC-59). A file kept on the device isn't missing. In a
    dry run, this is what the same run would leave.
    """
    if not args.fail_if_missing or result.errors:
        return []
    still_needed = (*result.plan.still_missing, *result.plan.incorrect)
    return [entry for entry in still_needed if entry.required is not False]


def _exit_code(result: RunResult, failing: list[MissingBios]) -> int:
    """A failed item wins, because the run didn't do all it could (DEC-59)."""
    if result.errors:
        return TransportError.exit_code
    return FAILED_IF_MISSING_EXIT_CODE if failing else 0


def _run_check(
    args: argparse.Namespace, settings: Settings, base_dir: Path, renderer: Renderer
) -> int:
    source = _source_folder(settings, base_dir)
    adapter = get_adapter(settings.frontend)

    def ended_early(entries: list[MissingBios], rejected: list[ItemError]) -> int:
        """Nothing to upload. The plan still says what's missing, incorrect and refused."""
        built = plan(entries, [], rejected=rejected)
        result = RunResult(plan=built, errors=built.rejected, dry_run=args.dry_run)
        failing = _failing_if_missing(args, result)
        renderer.ended_early(result, failing)
        return _exit_code(result, failing)

    transport = _connect_to_target(settings, renderer)
    renderer.opened(transport.url())
    _log.debug("Target: %s", transport.url())
    with transport:
        if args.report_file is not None:
            entries, rejected = _entries_from_file(adapter, args.report_file)
        else:
            entries, rejected = _entries_from_target(adapter, transport)
        if not entries and not rejected:
            renderer.nothing_missing()
        incorrect = [entry for entry in entries if entry.incorrect]
        if not args.overwrite:
            renderer.incorrect(incorrect)
        to_fill = {e.target for e in entries if args.overwrite or not e.incorrect}
        if not to_fill:
            return ended_early(entries, rejected)
        renderer.missing_count(len(to_fill))

        scanned = _scan_with_progress(source, renderer)
        renderer.unreadable(scanned.unreadable)
        if not scanned.files:
            if args.overwrite:
                renderer.incorrect(incorrect)
            renderer.no_files(source)
            return ended_early(entries, rejected)
        # Files on disk: a member of a zip isn't one, and files_scanned keeps its meaning (DEC-78).
        renderer.files_found(sum(1 for file in scanned.files if file.member is None))

        built = plan(entries, scanned.files, replace_incorrect=args.overwrite, rejected=rejected)
        _log_plan(built)
        options = {
            "overwrite": args.overwrite,
            "move": args.move,
            "clean_unmatched": args.clean_unmatched,
            "verify": args.verify,
        }
        started = time.monotonic()
        if args.dry_run:
            result = execute(built, transport, dry_run=True, **options)
        else:
            if (args.move or args.clean_unmatched) and not args.yes:
                # The preview only reads, so that a refusal leaves everything as it was.
                preview = execute(built, transport, dry_run=True, **options)
                if preview.deleted:
                    _confirm_deletion(preview, renderer)
            result = execute(built, transport, dry_run=False, **options)
        _log_run(result, started)

    if args.overwrite:
        renderer.incorrect(list(result.plan.incorrect))
    failing = _failing_if_missing(args, result)
    renderer.result(result, failing)
    return _exit_code(result, failing)


def _run_report(
    args: argparse.Namespace, settings: Settings, base_dir: Path, renderer: Renderer
) -> int:
    """List what the report says. It never writes anything, and a local copy needs no target."""
    adapter = get_adapter(settings.frontend)
    if args.report_file is not None:
        entries, rejected = _entries_from_file(adapter, args.report_file)
    else:
        transport = _connect_to_target(settings, renderer)
        renderer.opened(transport.url())
        _log.debug("Target: %s", transport.url())
        with transport:
            entries, rejected = _entries_from_target(adapter, transport)
    renderer.report(entries, rejected)
    return TransportError.exit_code if rejected else 0


def _git_repository_of(folder: Path) -> Path | None:
    """The git working tree that ``folder`` would be in, if any, even before it's created."""
    for candidate in (folder.absolute(), *folder.absolute().parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _run_export(args: argparse.Namespace, settings: Settings, renderer: Renderer) -> int:
    """Copy the target's BIOS files here. It reads the target, and never replaces a local file."""
    destination = Path(args.directory)
    renderer.exporting_to(destination)
    if destination.exists() and not destination.is_dir():
        raise UsageError(f"{destination} isn't a folder")
    repository = _git_repository_of(destination)
    if repository is not None:
        logging.getLogger(LOGGER_NAME).warning(
            "%s is inside the git repository in %s. These are real BIOS files: never commit them, "
            "and check that git ignores them.",
            destination,
            repository,
        )
    transport = _connect_to_target(settings, renderer)
    renderer.opened(transport.url())
    _log.debug("Target: %s", transport.url())
    with transport:
        result = export(transport, destination, dry_run=args.dry_run)
    renderer.exported(result)
    return TransportError.exit_code if result.errors else 0


def _run_scan(settings: Settings, base_dir: Path, renderer: Renderer) -> int:
    """List the local files. It uses no network and writes nothing."""
    source = _source_folder(settings, base_dir)
    renderer.scan(_scan_with_progress(source, renderer), source)
    return 0


def _shown_settings(settings: Settings, base_dir: Path) -> dict[str, dict[str, Any]]:
    """What ``beck config show`` shows: never the password, only whether there is one."""
    has_target = settings.target_url is not None or settings.target_dir is not None
    url_user = parse_smb_url(settings.target_url).user if settings.target_url else ""
    source = base_dir / "bios" if settings.source_dir is None else settings.source_dir
    sources = settings.sources
    return {
        "target": {
            # Only its URL: showing the settings connects to nothing, and asks for nothing.
            "value": _open_target(settings, lambda _user, _host: "").url() if has_target else None,
            "source": sources["target"],
        },
        "source": {"value": str(source), "source": sources["source"]},
        "frontend": {"value": settings.frontend, "source": sources["frontend"]},
        "smb_user": {
            "value": url_user or settings.smb_user,
            "source": sources["target"] if url_user else sources["smb_user"],
        },
        "smb_password": {
            "value": "set" if settings.smb_password else "not set",
            "source": sources["smb_password"],
        },
        "smb_timeout": {
            "value": settings.smb_timeout or DEFAULT_TIMEOUT,
            "source": sources["smb_timeout"],
        },
    }


def _run_config(args: argparse.Namespace, base_dir: Path, renderer: Renderer) -> int:
    """Find, create or show the settings. Only ``show`` reads the file, so bad ones can be found."""
    location = find_config(args.config, os.environ)
    if args.config_action == "init":
        write_template(location.path, force=args.force)
        renderer.config_created(location, location.path.exists())
    elif args.config_action == "path":
        renderer.config_path(location, location.path.exists())
    else:
        renderer.config_file(location, location.path.exists())
        settings = _load_settings(args)
        renderer.config_settings(
            location, location.path.exists(), _shown_settings(settings, base_dir)
        )
    return 0


def _notice_old_settings(args: argparse.Namespace, base_dir: Path) -> None:
    """Help someone who still has the old file, until they have a new one."""
    if args.quiet:
        return
    old = base_dir / "config" / "config.yml"
    legacy = read_legacy(old)
    if legacy is None:
        return
    new = find_config(args.config, os.environ).path
    if not new.exists():
        for line in migration_notice(old, legacy, new):
            logging.getLogger(LOGGER_NAME).warning("%s", line)


def _add_global_options(parser: argparse.ArgumentParser, *, on_a_command: bool) -> None:
    """Options that work before or after the command.

    On a command, the default must be SUPPRESS. Otherwise, argparse sets it after reading the part
    before the command, so ``beck --no-color check`` would lose the flag.
    """
    parser.add_argument(
        "-v",
        dest="verbose",
        action="store_true",
        default=argparse.SUPPRESS if on_a_command else False,
        help="add debug logs on stderr: steps, timings and the plan, never credentials",
    )
    parser.add_argument(
        "-q",
        dest="quiet",
        action="store_true",
        default=argparse.SUPPRESS if on_a_command else False,
        help="with check, print only errors, deletions and how the run ended",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS if on_a_command else False,
        help="don't use colors, the same as setting NO_COLOR",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        default=argparse.SUPPRESS if on_a_command else None,
        help="read the settings from this file, not the default one (see docs/cli.md)",
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
    # Required (DEC-70): a script that still runs bare `beck` fails with 2, not running check.
    commands = parser.add_subparsers(
        dest="command", required=True, title="commands", metavar="<command>"
    )
    for name, (summary, example) in COMMANDS.items():
        command = commands.add_parser(
            name,
            json_errors=json_errors,
            help=summary,
            description=EXPORT_DESCRIPTION if name == "export" else summary,
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
                "--verify",
                action="store_true",
                help="read each upload back and compare its MD5, which is slower",
            )
            command.add_argument(
                "--fail-if-missing",
                action="store_true",
                help="exit with 5 if required files are still missing or incorrect after the run",
            )
            command.add_argument(
                "--frontend",
                metavar="NAME",
                help=f"the kind of device (default: {DEFAULT_FRONTEND})",
            )
        if name == "report":
            group = _add_target_options(command)
            group.add_argument("--report-file", metavar="FILE", help=REPORT_FILE_HELP)
        if name == "export":
            command.add_argument(
                "directory", metavar="DIR", help="the folder to copy them to, created if needed"
            )
            _add_target_options(command)
            command.add_argument(
                "--dry-run",
                action="store_true",
                help="show what would be copied, and write nothing",
            )
        if name == "config":
            actions = command.add_subparsers(
                dest="config_action", required=True, title="actions", metavar="<action>"
            )
            for action, help_text in CONFIG_ACTIONS.items():
                inner = actions.add_parser(
                    action, json_errors=json_errors, help=help_text, description=help_text
                )
                _add_global_options(inner, on_a_command=True)
                if action == "init":
                    inner.add_argument(
                        "--force", action="store_true", help="replace a file that's already there"
                    )
    parser.set_defaults(
        target=None,
        target_dir=None,
        frontend=None,
        source=None,
        report_file=None,
        overwrite=False,
        dry_run=False,
        move=False,
        clean_unmatched=False,
        yes=False,
        fail_if_missing=False,
        verify=False,
        config_action=None,
        force=False,
        directory=None,
    )
    return parser


def main(argv: list[str] | None = None, *, base_dir: Path | None = None) -> int:
    """Run BECK and return its exit code. Settings and files are found under ``base_dir``.

    With no ``base_dir``, that's the current directory: an installed tool has no folder of its own.
    Output that can't be written doesn't change the run or its exit code (DEC-62).
    """
    try:
        return _main(argv, base_dir)
    finally:
        finish_output()


def _main(argv: list[str] | None, base_dir: Path | None) -> int:
    forget_secrets()
    add_secret(os.environ.get("BECK_SMB_PASSWORD", ""))
    parser = _build_parser(json_errors=_asks_for_json(sys.argv[1:] if argv is None else argv))
    try:
        args = parser.parse_args(argv)
        if args.verbose and args.quiet:  # checked here because they can be on different sides
            parser.error("-v and -q can't be used together")
    except UsageError as error:
        write_rejected_command(str(error))
        return error.exit_code
    configure_logging(logging.DEBUG if args.verbose else logging.WARNING)
    _log.debug("BECK %s, Python %s", __version__, platform.python_version())
    renderer: Renderer
    if args.json:
        # The frontend can come from the settings file, which may be what fails.
        renderer = JsonRenderer(
            args.command,
            frontend=args.frontend or DEFAULT_FRONTEND,
            dry_run=args.dry_run,
            action=args.config_action,
        )
    else:
        environ = {**os.environ, "NO_COLOR": "1"} if args.no_color else None
        # A list is what report and scan are for, so quiet is only for check.
        quiet = args.quiet and args.command == "check"
        renderer = ConsoleRenderer(environ=environ, quiet=quiet, progress=not args.verbose)

    try:
        folder = Path.cwd() if base_dir is None else base_dir
        _notice_old_settings(args, folder)
        if args.command == "config":
            return _run_config(args, folder, renderer)
        settings = _load_settings(args)
        renderer.uses_frontend(settings.frontend)
        if args.command == "scan":
            return _run_scan(settings, folder, renderer)
        if args.command == "report":
            return _run_report(args, settings, folder, renderer)
        if args.command == "export":
            return _run_export(args, settings, renderer)
        return _run_check(args, settings, folder, renderer)
    except BeckError as error:
        renderer.error(error)
        return error.exit_code
    except Exception:
        # A bug in BECK: the traceback goes to stderr, for the bug report.
        logging.getLogger(LOGGER_NAME).exception("Unexpected error")
        renderer.unexpected_error()
        return 1
