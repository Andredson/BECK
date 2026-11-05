"""The beck package and the check_bios.py shim: entry points, version, and where files are found."""

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
SHIM = ROOT / "check_bios.py"


def forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("this must not run")


def test_version_comes_from_the_package_metadata() -> None:
    assert beck.__version__ == importlib.metadata.version("beck-bios")


def test_version_when_run_from_a_clone_without_installing(monkeypatch: pytest.MonkeyPatch) -> None:
    # The pip route: requirements.txt doesn't install BECK, and check_bios.py imports it from src/.
    def not_installed(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", not_installed)

    module = runpy.run_path(str(ROOT / "src" / "beck" / "__init__.py"))

    assert module["__version__"] == "0+unknown"


def test_help_describes_the_command_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_run", forbidden)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "usage: beck" in output
    assert "Match your BIOS files" in output


def test_an_unknown_argument_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_run", forbidden)

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


def test_importing_the_shim_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "main", forbidden)

    module = runpy.run_path(str(SHIM))

    assert module["ROOT"] == ROOT


def test_the_shim_uses_its_own_folder_from_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Old usage keeps working: config and bios sit next to the script, not the current folder (D9).
    folders: list[Path | None] = []

    def fake_main(argv: list[str] | None = None, *, base_dir: Path | None = None) -> int:
        folders.append(base_dir)
        return 7

    monkeypatch.setattr(cli, "main", fake_main)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(SHIM), run_name="__main__")

    assert exit_info.value.code == 7
    assert folders == [ROOT]
    assert sys.path[0] == str(ROOT / "src")
    captured = capsys.readouterr()
    assert "deprecated" in captured.err  # stderr, so stdout stays the same as before
    assert captured.out == ""


def test_the_shim_runs_as_a_real_script_from_another_folder(tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [sys.executable, SHIM, "--help"], capture_output=True, text=True, check=False, cwd=tmp_path
    )

    assert result.returncode == 0
    assert "usage: beck" in result.stdout
    assert "deprecated" in result.stderr
    assert list(tmp_path.iterdir()) == []
