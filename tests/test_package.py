"""The beck package (step 04.3): it installs a command that still runs the legacy script."""

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

import beck
import check_bios
from beck import cli
from tests.conftest import use_folder
from tests.fakes import install_fake_smb


def test_version_comes_from_the_package_metadata() -> None:
    assert beck.__version__


def test_help_describes_the_command_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden() -> int:
        raise AssertionError("--help must not run BECK")

    monkeypatch.setattr(cli, "run_legacy", forbidden)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "usage: beck" in output
    assert "Match your BIOS files" in output


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


def test_no_arguments_run_the_same_code_as_the_script(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(check_bios, "main", lambda: calls.append("legacy"))

    assert cli.main([]) == 0
    assert calls == ["legacy"]


def test_legacy_failure_keeps_its_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_folder(monkeypatch, tmp_path)  # no config file here, so the legacy script exits 1
    install_fake_smb(monkeypatch)

    with pytest.raises(SystemExit) as exit_info:
        cli.main([])

    assert exit_info.value.code == 1
    assert "Copy config/config.example.yml" in capsys.readouterr().out


def test_an_installed_copy_without_the_script_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    installed = tmp_path / "site-packages" / "beck" / "cli.py"
    monkeypatch.setattr(cli, "__file__", str(installed))

    assert cli.run_legacy() == 1
    assert "Use a clone of the repository" in capsys.readouterr().err


def test_the_console_command_is_installed() -> None:
    command = Path(sys.executable).with_name("beck")
    result = subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [command, "--help"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0
    assert "usage: beck" in result.stdout
