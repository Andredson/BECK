"""The Recalbox adapter, from the stage 03 parser tests (D2, D10, DEC-50), and the registry."""

from collections import Counter
from pathlib import PurePosixPath

import pytest

from beck.errors import ReportParseError, UsageError
from beck.frontends import get_adapter
from beck.frontends.base import FrontendAdapter
from beck.frontends.recalbox import RecalboxAdapter
from tests.conftest import REAL_REPORT, REPORT_NAMES, load_expected, load_report

HASH = "490F666E1AFB15B7362B406ED1CEA246"
OTHER_HASH = "8DD7D5296A650FAC7319BCE665A6A53C"

adapter: FrontendAdapter = RecalboxAdapter()  # mypy checks that the class follows the Protocol


def block(
    heading: str = "  MISSING REQUIRED BIOS: scph5501.bin",
    path: str = "    Path: /recalbox/share/bios/scph5501.bin\n",
    hashes: str = f"      {HASH}\n",
) -> str:
    return f"{heading}\n{path}    For: libretro/pcsx_rearmed\n    Possible MD5 List:\n{hashes}\n"


@pytest.mark.parametrize("name", REPORT_NAMES)
def test_parser_matches_the_expected_entries(name: str) -> None:
    # The expected files came from a script that shares no code with the parser (step 03.4).
    parsed = adapter.parse_report(load_report(name))

    assert [(e.name, e.target, set(e.md5s)) for e in parsed] == [
        (
            item["name"],
            PurePosixPath(item["relativePath"] + item["name"]),
            {md5.lower() for md5 in item["hashes"]},
        )
        for item in load_expected(name)
    ]


def test_real_report_with_crlf_keeps_every_entry() -> None:
    # Regression from step 03.3: CRLF merged the whole real report into one entry.
    parsed = adapter.parse_report(load_report(REAL_REPORT))

    assert len(parsed) == 238
    assert len({entry.target for entry in parsed}) == 232
    assert parsed[0].name == "kick39106.A1200"
    assert parsed[0].md5s == {"b7cc148386aa631136f510cd29e42fc3"}


def test_real_report_required_and_system_counts() -> None:
    # Counted separately from the report's text: 123 required, 115 optional, 64 systems.
    parsed = adapter.parse_report(load_report(REAL_REPORT))

    assert Counter(entry.required for entry in parsed) == {True: 123, False: 115}
    assert len({entry.system for entry in parsed}) == 64
    assert None not in {entry.system for entry in parsed}


def test_required_and_system_come_from_the_report() -> None:
    text = (
        "SYSTEM: First\n-----\n\n"
        + block()
        + "SYSTEM: Second\n-----\n\n"
        + block("  MISSING OPTIONAL BIOS: other.bin", "    Path: /recalbox/share/bios/other.bin\n")
    )

    first, second = adapter.parse_report(text)

    assert (first.required, first.system) == (True, "First")
    assert (second.required, second.system) == (False, "Second")


def test_a_block_before_any_system_line_has_no_system() -> None:
    assert adapter.parse_report(block())[0].system is None


@pytest.mark.parametrize(
    "name",
    [
        "7800 BIOS (U).rom",
        "panafz1j-norsa.bin",
        "scpu-dos-1.4.bin",
        "kick40060.CD32.ext",
    ],
)
def test_full_file_names_are_kept(name: str) -> None:
    text = block(f"  MISSING OPTIONAL BIOS: {name}", f"    Path: /recalbox/share/bios/x/{name}\n")

    entry = adapter.parse_report(text)[0]

    assert entry.name == name
    assert entry.target == PurePosixPath("x") / name


def test_two_locations_use_the_first() -> None:
    path = "    Path: /recalbox/share/bios/neogeo.zip or /recalbox/share/roms/neogeo/neogeo.zip\n"

    entry = adapter.parse_report(block("  MISSING REQUIRED BIOS: neogeo.zip", path))[0]

    assert entry.target == PurePosixPath("neogeo.zip")


def test_nested_folder() -> None:
    path = "    Path: /recalbox/share/bios/amiga/bios/kick39106.A1200\n"

    entry = adapter.parse_report(block("  MISSING REQUIRED BIOS: kick39106.A1200", path))[0]

    assert entry.target == PurePosixPath("amiga/bios/kick39106.A1200")


def test_hashes_are_lowercase_without_repeats() -> None:
    text = block(hashes=f"      {OTHER_HASH}\n      {HASH}\n      {OTHER_HASH.lower()}\n")

    assert adapter.parse_report(text)[0].md5s == {OTHER_HASH.lower(), HASH.lower()}


def test_longer_hex_strings_are_not_split_into_fake_hashes() -> None:
    text = block(hashes=f"      {HASH}\n      {OTHER_HASH}FF\n")

    assert adapter.parse_report(text)[0].md5s == {HASH.lower()}


def test_blocks_do_not_need_a_blank_line_between_them() -> None:
    text = block().rstrip("\n") + "\n" + block("  MISSING OPTIONAL BIOS: other.bin")

    assert [e.name for e in adapter.parse_report(text)] == ["scph5501.bin", "other.bin"]


def test_report_with_nothing_missing_has_no_entries() -> None:
    assert adapter.parse_report("MISSING BIOS REPORT\nPlatform: x86_64\n") == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (block(path=""), "No Path line in report block: MISSING REQUIRED BIOS: scph5501.bin"),
        (block(hashes=""), "No MD5 value in report block: MISSING REQUIRED BIOS: scph5501.bin"),
        (block("  MISSING REQUIRED BIOS:"), "No file name in report block: MISSING REQUIRED BIOS:"),
        (
            block(path="    Path: /etc/scph5501.bin\n"),
            "Path is outside /recalbox/share/bios/: MISSING REQUIRED BIOS: scph5501.bin",
        ),
    ],
)
def test_bad_blocks_raise_report_parse_error(text: str, message: str) -> None:
    with pytest.raises(ReportParseError) as error:
        adapter.parse_report(text)

    assert str(error.value) == message


@pytest.mark.parametrize(
    ("heading_name", "path"),
    [
        ("a.bin", "/recalbox/share/bios/../../etc/a.bin"),
        ("a.bin", "/recalbox/share/bios//etc/a.bin"),
        ("..", "/recalbox/share/bios/x/.."),
        ("sub/a.bin", "/recalbox/share/bios/sub/a.bin"),
    ],
)
def test_unsafe_paths_are_a_parse_error_not_a_crash(heading_name: str, path: str) -> None:
    text = block(f"  MISSING REQUIRED BIOS: {heading_name}", f"    Path: {path}\n")

    with pytest.raises(ReportParseError, match="Unsafe path in report block"):
        adapter.parse_report(text)


def test_recalbox_report_location() -> None:
    assert adapter.name == "recalbox"
    assert adapter.report_path == PurePosixPath("missing_bios_report.txt")


def test_registry_returns_the_recalbox_adapter() -> None:
    assert isinstance(get_adapter("recalbox"), RecalboxAdapter)


def test_unknown_frontend_is_a_usage_error_listing_the_known_ones() -> None:
    with pytest.raises(UsageError) as error:
        get_adapter("batocera")

    assert "'batocera'" in str(error.value)
    assert "recalbox" in str(error.value)
