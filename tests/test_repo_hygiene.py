"""Tests for scripts/check_repo_hygiene.py: fake file lists, plus one run on the real repository."""

import pytest

from scripts.check_repo_hygiene import ALLOWED, MAX_BYTES, find_problems, tracked_entries


def test_clean_list_has_no_problems() -> None:
    entries = [
        ("bios/.keep", 0),
        ("check_bios.py", 9_000),
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
