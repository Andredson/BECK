"""The ``beck`` command: connects the parts. Only this module turns errors into exit codes."""

import argparse
import logging
from pathlib import Path
from typing import Any

import yaml

from beck.errors import BeckError, ConfigError, ReportNotFoundError, TransportError
from beck.executor import execute
from beck.frontends import get_adapter
from beck.hashing import scan
from beck.matcher import plan
from beck.output.console import LOGGER_NAME, ConsoleRenderer, configure_logging
from beck.transports.smb import SmbTransport

DESCRIPTION = "Match your BIOS files by MD5 and send them to the right folder on your Recalbox."

SMB_SETTINGS = ("server", "port", "user", "passwd")


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


def _run(base_dir: Path, renderer: ConsoleRenderer) -> int:
    settings = load_legacy_config(base_dir / "config" / "config.yml")
    bios_dir = base_dir / "bios"
    adapter = get_adapter("recalbox")

    with SmbTransport(
        host=settings["server"],
        port=settings["port"],
        share="bios",
        user=settings["user"],
        password=settings["passwd"],
    ) as transport:
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

        local = scan(bios_dir)
        if not local:
            renderer.no_files(bios_dir)
            return 0
        renderer.files_found(len(local))

        result = execute(plan(entries, local), transport, dry_run=False)

    renderer.result(result)
    return TransportError.exit_code if result.errors else 0


def main(argv: list[str] | None = None, *, base_dir: Path | None = None) -> int:
    """Run BECK and return its exit code. Settings and files are found under ``base_dir``.

    With no ``base_dir``, that's the current directory: an installed tool has no folder of its own.
    """
    argparse.ArgumentParser(prog="beck", description=DESCRIPTION).parse_args(argv)
    configure_logging()
    renderer = ConsoleRenderer()

    try:
        return _run(Path.cwd() if base_dir is None else base_dir, renderer)
    except BeckError as error:
        renderer.error(error)
        return error.exit_code
    except Exception:
        # A bug in BECK: the traceback goes to stderr, for the bug report.
        logging.getLogger(LOGGER_NAME).exception("Unexpected error")
        return 1
