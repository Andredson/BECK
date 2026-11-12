# SPDX-License-Identifier: GPL-3.0-only
"""The summary by system (step 11.3): how each system stands, for people and in --json."""

import json
from pathlib import Path, PurePosixPath

import pytest

from beck import cli
from beck.models import MissingBios
from beck.output import SystemCounts, by_system
from tests.factories import make_bios_file, make_missing, make_report_text

A, B, C = "a" * 32, "b" * 32, "c" * 32


# Counting


def test_each_system_counts_its_targets_by_how_they_stand() -> None:
    entries = [
        make_missing("dc/naomi.zip", A, system="Sega Naomi"),
        make_missing("dc/airlbios.zip", A, required=False, system="Sega Naomi"),
        make_missing("dc/unsure.bin", A, required=None, system="Sega Naomi"),
        make_missing("dc/bad.bin", A, incorrect=True, system="Sega Naomi"),
        make_missing("dc/done.bin", A, system="Sega Naomi"),
    ]

    assert by_system(entries, [PurePosixPath("dc/done.bin")]) == [
        SystemCounts("Sega Naomi", 1, 1, 1, 1, 1)
    ]


def test_a_target_two_systems_list_counts_in_both() -> None:
    entries = [
        make_missing("neogeo.zip", A, system="SNK Neo-Geo"),
        make_missing("neogeo.zip", A, system="SNK Neo-Geo CD"),
    ]

    assert by_system(entries) == [
        SystemCounts("SNK Neo-Geo", missing_required=1),
        SystemCounts("SNK Neo-Geo CD", missing_required=1),
    ]


@pytest.mark.parametrize("required_first", [True, False])
def test_a_target_listed_twice_by_one_system_counts_once_and_required_wins(
    required_first: bool,
) -> None:
    required = make_missing("x.pce", A, system="PC Engine")
    optional = make_missing("x.pce", B, required=False, system="PC Engine")

    entries = [required, optional] if required_first else [optional, required]

    assert by_system(entries) == [SystemCounts("PC Engine", missing_required=1)]


def test_an_incorrect_target_replaced_by_the_run_counts_as_satisfied() -> None:
    entries = [make_missing("bad.bin", A, incorrect=True, system="One")]

    assert by_system(entries, [PurePosixPath("bad.bin")]) == [SystemCounts("One", satisfied=1)]


def test_an_incorrect_target_wins_over_the_same_target_listed_as_missing() -> None:
    # DEC-54: BECK keeps a file that's incorrect on the device, even if another entry asks for it.
    entries = [
        make_missing("x.bin", A, system="One"),
        make_missing("x.bin", B, incorrect=True, system="One"),
    ]

    assert by_system(entries) == [SystemCounts("One", incorrect=1)]


def test_systems_are_sorted_by_name_with_no_system_last() -> None:
    entries = [
        make_missing("a.bin", A),
        make_missing("b.bin", A, system="Zeta"),
        make_missing("c.bin", A, system="Alpha"),
    ]

    assert [counts.system for counts in by_system(entries)] == ["Alpha", "Zeta", None]


def test_nothing_listed_has_no_systems() -> None:
    assert by_system([]) == []


# For people


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    source, device = tmp_path / "source", tmp_path / "device"
    source.mkdir()
    device.mkdir()
    return source, device


def put_report(device: Path, *entries: MissingBios) -> None:
    (device / "missing_bios_report.txt").write_text(
        make_report_text(entries),
        encoding="utf-8",
        newline="",
    )


def check(folders: tuple[Path, Path], *flags: str) -> list[str]:
    source, device = folders
    return ["check", "--source", str(source), "--target-dir", str(device), *flags]


def a_run_with_two_systems(folders: tuple[Path, Path]) -> None:
    source, device = folders
    good = make_bios_file(source, "good.bin")
    put_report(
        device,
        make_missing("dc/dc_boot.bin", good.md5, system="Sega Dreamcast"),
        make_missing("dc/airlbios.zip", A, required=False, system="Sega Dreamcast"),
        make_missing("dc/awbios.zip", B, system="Sega Dreamcast"),
        make_missing("vice/a.bin", A, required=False, system="Commodore 64"),
        make_missing("vice/b.bin", B, required=False, system="Commodore 64"),
    )


def test_check_prints_each_system_before_the_final_line(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_run_with_two_systems(folders)

    assert cli.main(check(folders)) == 0

    lines = capsys.readouterr().out.splitlines()
    start = lines.index("By system:")
    assert lines[start : start + 4] == [
        "By system:",
        "  Commodore 64: 2 still missing (all optional)",
        "  Sega Dreamcast: 1 copied, 2 still missing (1 required)",
        "Final result: 1/5 missing entries satisfied, 1 files analysed",
    ]


def test_a_dry_run_says_what_would_be_copied(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_run_with_two_systems(folders)

    assert cli.main(check(folders, "--dry-run")) == 0

    output = capsys.readouterr().out
    assert "  Sega Dreamcast: 1 would be copied, 2 still missing (1 required)" in output


def test_quiet_hides_the_lines_by_system(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_run_with_two_systems(folders)

    assert cli.main(["-q", *check(folders)]) == 0

    assert "By system:" not in capsys.readouterr().out


def test_a_run_with_no_local_files_still_says_how_each_system_stands(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    put_report(folders[1], make_missing("vice/a.bin", A, system="Commodore 64"))

    assert cli.main(check(folders)) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[-2:] == ["By system:", "  Commodore 64: 1 still missing (all required)"]


def test_nothing_missing_prints_no_lines_by_system(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    put_report(folders[1])

    assert cli.main(check(folders)) == 0

    assert "By system:" not in capsys.readouterr().out


def test_report_ends_with_each_system(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = tmp_path / "report.txt"
    report.write_text(
        make_report_text(
            [
                make_missing("x.bin", C, required=False),  # first: no SYSTEM line comes before it
                make_missing("dc/naomi.zip", A, system="Sega Dreamcast"),
                make_missing("dc/bad.bin", B, incorrect=True, system="Sega Dreamcast"),
            ]
        ),
        encoding="utf-8",
        newline="",
    )

    assert cli.main(["report", "--report-file", str(report)]) == 0

    assert capsys.readouterr().out.splitlines()[-3:] == [
        "By system:",
        "  Sega Dreamcast: 1 missing (all required), 1 incorrect",
        "  Other: 1 missing (all optional)",
    ]


# In --json


def test_json_check_counts_what_a_dry_run_would_satisfy(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_run_with_two_systems(folders)

    assert cli.main(["--json", *check(folders, "--dry-run")]) == 0

    systems = json.loads(capsys.readouterr().out)["systems"]
    assert systems[1] == {
        "system": "Sega Dreamcast",
        "satisfied": 1,
        "missing_required": 1,
        "missing_optional": 1,
        "missing_unknown": 0,
        "incorrect": 0,
    }


def test_a_run_that_stops_has_no_systems(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, _device = folders

    assert cli.main(["--json", "check", "--source", str(source), "--target-dir", "/nowhere"]) == 3

    assert json.loads(capsys.readouterr().out)["systems"] == []
