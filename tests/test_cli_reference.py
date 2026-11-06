"""docs/cli-reference.md says what the command really does."""

import os
from pathlib import Path

import pytest

from beck import cli
from scripts.gen_cli_reference import REFERENCE, render, rewrap_usage, write


def test_the_reference_is_up_to_date() -> None:
    assert REFERENCE.read_text(encoding="utf-8") == render(), (
        "docs/cli-reference.md is out of date: run uv run python scripts/gen_cli_reference.py"
    )


@pytest.mark.parametrize(
    "command",
    [
        "beck",
        "beck check",
        "beck scan",
        "beck report",
        "beck config",
        "beck config path",
        "beck config init",
        "beck config show",
    ],
)
def test_every_command_has_a_section(command: str) -> None:
    assert f"## `{command}`\n" in render()


def test_a_changed_help_text_changes_the_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    before = render()

    monkeypatch.setattr(cli, "REPORT_FILE_HELP", "beck-test-changed-help")

    assert "beck-test-changed-help" not in before
    assert "beck-test-changed-help" in render()


def test_the_terminal_does_not_change_the_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = render()

    monkeypatch.setenv("COLUMNS", "40")
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("PYTHON_COLORS", "1")
    monkeypatch.delenv("NO_COLOR")

    assert render() == expected


def test_making_the_reference_leaves_the_environment_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLUMNS", "40")

    render()

    assert os.environ["COLUMNS"] == "40"


@pytest.mark.parametrize(
    "usage",
    [
        "usage: beck report [-h] [--json]\n                   [--target URL | --report-file FILE]",
        "usage: beck report [-h] [--json] [--target URL |\n                   --report-file FILE]",
    ],
    ids=["python-3.11", "python-3.13"],
)
def test_the_usage_is_wrapped_the_same_on_every_python(usage: str) -> None:
    assert rewrap_usage(f"{usage}\n\nThe rest\n  stays as it was.\n") == (
        "usage: beck report [-h] [--json] [--target URL | --report-file FILE]\n\n"
        "The rest\n  stays as it was.\n"
    )


def test_a_long_usage_is_wrapped_under_its_first_option() -> None:
    usage = "usage: beck check [-h] " + " ".join(f"[--long-option-{n}]" for n in range(20))

    lines = rewrap_usage(f"{usage}\n").splitlines()

    assert " ".join(lines).split() == usage.split(), "A flag was broken across two lines"
    assert len(lines) > 1
    assert max(len(line) for line in lines) <= 100
    assert all(line.startswith(" " * len("usage: beck check ") + "[") for line in lines[1:])


@pytest.mark.parametrize("command", [["check"], ["config", "init"]], ids=" ".join)
def test_the_reference_holds_what_help_prints(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
) -> None:
    monkeypatch.setenv("COLUMNS", "100")

    with pytest.raises(SystemExit) as stopped:
        cli.main([*command, "--help"], base_dir=tmp_path)

    assert stopped.value.code == 0
    assert " ".join(capsys.readouterr().out.split()) in " ".join(render().split())


def test_write_saves_what_render_returns(tmp_path: Path) -> None:
    path = tmp_path / "reference.md"

    write(path)

    assert path.read_text(encoding="utf-8") == render()
