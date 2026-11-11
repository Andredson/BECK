# SPDX-License-Identifier: GPL-3.0-only
"""Tests for scripts/check_repo_hygiene.py: fake file lists, plus one run on the real repository."""

from pathlib import Path

import pytest

from scripts import check_repo_hygiene as hygiene
from scripts.check_repo_hygiene import (
    ALLOWED,
    MAX_BYTES,
    find_passwords,
    find_problems,
    tracked_entries,
)

ROOT = Path(__file__).resolve().parent.parent


def test_clean_list_has_no_problems() -> None:
    entries = [
        ("bios/.keep", 0),
        ("src/beck/cli.py", 30_000),
        ("config/config.example.yml", 80),
        # GitHub's issue-form config is not a BECK config.
        (".github/ISSUE_TEMPLATE/config.yml", 200),
        ("uv.lock", 160_000),
    ]
    assert find_problems(entries) == []


@pytest.mark.parametrize(
    "path", ["scph5501.bin", "roms/neogeo.zip", "dc/dc_boot.BIN", "x.rom", "a.7z", "b.chd"]
)
def test_bios_like_files_are_rejected(path: str) -> None:
    assert any("BIOS/ROM-type file" in p for p in find_problems([(path, 10)]))


def test_anything_inside_bios_folder_except_keep_is_rejected() -> None:
    problems = find_problems([("bios/notes.txt", 10), ("bios/.keep", 0)])
    assert problems == ["bios/notes.txt: only bios/.keep may be tracked inside bios/"]


def test_large_files_are_rejected() -> None:
    assert find_problems([("data.json", MAX_BYTES)]) == []
    assert "over the" in find_problems([("data.json", MAX_BYTES + 1)])[0]


@pytest.mark.parametrize("path", ["config.toml", "settings/config.yml", "config/config.yaml"])
def test_real_config_files_are_rejected(path: str) -> None:
    assert any("real config file" in p for p in find_problems([(path, 50)]))


def test_one_file_can_break_several_rules() -> None:
    assert len(find_problems([("bios/huge.zip", MAX_BYTES + 1)])) == 3


def test_allow_list_entries_name_the_step_that_removes_them() -> None:
    for path, reason in ALLOWED.items():
        assert "step" in reason, f"{path}: say which roadmap step removes this exception"


def test_repository_is_currently_clean() -> None:
    assert find_problems(tracked_entries()) == []


@pytest.mark.parametrize(
    "line",
    [
        'password = "x"',
        'passwd = "x"',
        '  password = "x"',
        'PASSWORD = "x"',
        'Passwd="x"',
        "password = 1234",
    ],
)
def test_a_toml_file_holding_a_password_is_rejected_whatever_its_name(
    tmp_path: Path, line: str
) -> None:
    file = tmp_path / "my-settings.toml"
    file.write_text(f"[smb]\n{line}\n", encoding="utf-8")

    problems = find_passwords(tmp_path, ["my-settings.toml"])

    assert len(problems) == 1
    assert problems[0].startswith("my-settings.toml: holds a password")


def test_a_problem_never_repeats_the_password(tmp_path: Path) -> None:
    (tmp_path / "a.toml").write_text('password = "beck-test-password"\n', encoding="utf-8")

    assert "beck-test-password" not in find_passwords(tmp_path, ["a.toml"])[0]


@pytest.mark.parametrize(
    "text",
    [
        '[smb]\nuser = "x"\n',
        "# password = comes from BECK_SMB_PASSWORD\n",
        'password_hint = "x"\n',
        'user = "password = x"\n',
        "",
    ],
)
def test_a_toml_file_with_no_password_is_fine(tmp_path: Path, text: str) -> None:
    (tmp_path / "a.toml").write_text(text, encoding="utf-8")

    assert find_passwords(tmp_path, ["a.toml"]) == []


def test_only_toml_files_are_read(tmp_path: Path) -> None:
    """Other files can mention a password key for good reasons, and gitleaks looks at them."""
    (tmp_path / "workflow.yml").write_text("password: x\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text('password = "x"\n', encoding="utf-8")

    assert find_passwords(tmp_path, ["workflow.yml", "notes.md"]) == []


def test_a_toml_file_with_a_capital_extension_is_read_too(tmp_path: Path) -> None:
    (tmp_path / "A.TOML").write_text('password = "x"\n', encoding="utf-8")

    assert find_passwords(tmp_path, ["A.TOML"]) != []


def test_a_file_in_the_index_but_not_on_disk_is_skipped(tmp_path: Path) -> None:
    assert find_passwords(tmp_path, ["gone.toml"]) == []


def test_a_toml_file_that_is_not_text_does_not_stop_the_check(tmp_path: Path) -> None:
    (tmp_path / "a.toml").write_bytes(b'\xff\xfe\npassword = "x"\n')

    assert find_passwords(tmp_path, ["a.toml"]) != []


def test_this_repository_has_no_such_file() -> None:
    assert find_passwords(ROOT, [path for path, _size in tracked_entries()]) == []


def test_main_fails_on_a_password_in_a_toml_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.toml").write_text('password = "x"\n', encoding="utf-8")
    monkeypatch.setattr(hygiene, "ROOT", tmp_path)
    monkeypatch.setattr(hygiene, "tracked_entries", lambda: [("a.toml", 16)])

    assert hygiene.main() == 1

    assert "a.toml: holds a password" in capsys.readouterr().err


def test_a_config_file_message_no_longer_mentions_an_example() -> None:
    message = find_problems([("config.toml", 50)])[0]

    assert "example" not in message
