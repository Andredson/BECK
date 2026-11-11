# SPDX-License-Identifier: GPL-3.0-only
"""The beck package: entry points, version, and where files are found."""

import importlib.metadata
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import pytest

import beck
from beck import cli

ROOT = Path(__file__).resolve().parent.parent


def forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("this must not run")


def test_version_comes_from_the_package_metadata() -> None:
    assert beck.__version__ == importlib.metadata.version("beck-bios")


def test_version_when_run_from_a_clone_without_installing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Running from src/ without installing, as with PYTHONPATH=src.
    def not_installed(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", not_installed)

    module = runpy.run_path(str(ROOT / "src" / "beck" / "__init__.py"))

    assert module["__version__"] == "0+unknown"


def test_help_describes_the_command_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_run_check", forbidden)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "usage: beck" in output
    assert "Match your BIOS files" in output


def test_an_unknown_argument_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_run_check", forbidden)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--no-such-flag"])

    assert exit_info.value.code == 2


def test_python_dash_m_beck_runs_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str] | None] = []

    def fake_main(argv: list[str] | None = None) -> int:
        calls.append(argv)
        return 7

    monkeypatch.setattr(cli, "main", fake_main)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("beck", run_name="__main__")

    assert exit_info.value.code == 7
    assert calls == [None]


def test_the_console_command_is_installed() -> None:
    command = Path(sys.executable).with_name("beck")
    result = subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [command, "--help"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0
    assert "usage: beck" in result.stdout
