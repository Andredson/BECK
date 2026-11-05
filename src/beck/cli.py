"""The ``beck`` command: connects the parts. Only this module turns errors into exit codes."""

import argparse
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from beck import __version__
from beck.errors import BeckError, ConfigError, ReportNotFoundError, TransportError, UsageError
from beck.executor import execute
from beck.frontends import get_adapter
from beck.hashing import scan
from beck.matcher import plan
from beck.output.console import LOGGER_NAME, ConsoleRenderer, configure_logging
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


def _run(args: argparse.Namespace, base_dir: Path, renderer: ConsoleRenderer) -> int:
    bios_dir = base_dir / "bios"
    adapter = get_adapter(args.frontend)

    with _open_target(args, base_dir) as transport:
        if not transport.exists(adapter.report_path):
            raise ReportNotFoundError(
                f"{adapter.report_path} not found on {transport.describe()}. "
                "Generate the report on the device first."
            )
        text = transport.read_bytes(adapter.report_path).decode("utf-8", errors="replace")
        entries = adapter.parse_report(text)
        if not entries:
            renderer.nothing_missing()
            return 0
        renderer.incorrect([entry for entry in entries if entry.incorrect])
        missing = {entry.target for entry in entries if not entry.incorrect}
        if not missing:
            return 0
        renderer.missing_count(len(missing))

        scanned = scan(bios_dir)
        renderer.unreadable(scanned.unreadable)
        if not scanned.files:
            renderer.no_files(bios_dir)
            return 0
        renderer.files_found(len(scanned.files))

        result = execute(plan(entries, scanned.files), transport, dry_run=False)

    renderer.result(result)
    return TransportError.exit_code if result.errors else 0


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


def _add_target_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--target", metavar="URL", help=f"an SMB target: {URL_FORM}")
    group.add_argument(
        "--target-dir",
        metavar="DIR",
        help="a folder: a mounted SD card or USB drive, or the device itself",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
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
            help=summary,
            description=summary,
            epilog=example,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        _add_global_options(command, on_a_command=True)
        if name in ("check", "report"):
            _add_target_options(command)
        if name == "check":
            command.add_argument(
                "--frontend",
                default=DEFAULT_FRONTEND,
                metavar="NAME",
                help=f"the kind of device (default: {DEFAULT_FRONTEND})",
            )
    parser.set_defaults(target=None, target_dir=None, frontend=DEFAULT_FRONTEND)
    return parser


def main(argv: list[str] | None = None, *, base_dir: Path | None = None) -> int:
    """Run BECK and return its exit code. Settings and files are found under ``base_dir``.

    With no ``base_dir``, that's the current directory: an installed tool has no folder of its own.
    """
    args = _build_parser().parse_args(argv)
    logger = configure_logging()
    environ = {**os.environ, "NO_COLOR": "1"} if args.no_color else None
    renderer = ConsoleRenderer(environ=environ)
    if args.command is None:
        logger.warning("Hint: use 'beck check'. Running beck with no command is going away.")

    try:
        if args.command in ("scan", "report"):
            raise UsageError(f"beck {args.command} isn't available yet")
        return _run(args, Path.cwd() if base_dir is None else base_dir, renderer)
    except BeckError as error:
        renderer.error(error)
        return error.exit_code
    except Exception:
        # A bug in BECK: the traceback goes to stderr, for the bug report.
        logging.getLogger(LOGGER_NAME).exception("Unexpected error")
        return 1
