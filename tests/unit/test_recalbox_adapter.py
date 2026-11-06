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
def test_unsafe_paths_are_refused_not_a_crash(heading_name: str, path: str) -> None:
    text = block(f"  MISSING REQUIRED BIOS: {heading_name}", f"    Path: {path}\n")

    assert adapter.parse_report(text) == []
    assert [error.code for error in adapter.rejected_entries(text)] == ["unsafe_path"]


def test_hyphens_in_a_name() -> None:
    text = block(
        "  MISSING REQUIRED BIOS: scph-1001.bin", "    Path: /recalbox/share/bios/scph-1001.bin\n"
    )

    assert adapter.parse_report(text)[0].name == "scph-1001.bin"  # the old regex kept 1001.bin (D2)


def test_spaces_and_parentheses_in_a_name() -> None:
    name = "7800 BIOS (U).rom"
    text = block(f"  MISSING REQUIRED BIOS: {name}", f"    Path: /recalbox/share/bios/{name}\n")

    assert adapter.parse_report(text)[0].target == PurePosixPath(name)


def test_multiple_dots_in_a_name() -> None:
    name = "kick40060.CD32.ext"
    text = block(f"  MISSING REQUIRED BIOS: {name}", f"    Path: /recalbox/share/bios/{name}\n")

    assert adapter.parse_report(text)[0].name == name


def test_spaces_in_a_folder() -> None:
    path = "    Path: /recalbox/share/bios/some folder/a b/x.bin\n"

    entry = adapter.parse_report(block("  MISSING REQUIRED BIOS: x.bin", path))[0]

    assert entry.target == PurePosixPath("some folder/a b/x.bin")


def test_the_word_or_in_a_file_name_keeps_the_name_and_folder() -> None:
    name = "this or that.bin"
    text = block(f"  MISSING REQUIRED BIOS: {name}", f"    Path: /recalbox/share/bios/ps1/{name}\n")

    assert adapter.parse_report(text)[0].target == PurePosixPath("ps1") / name


def test_two_entries_can_share_an_md5() -> None:
    first = block("  MISSING REQUIRED BIOS: a.bin", "    Path: /recalbox/share/bios/a.bin\n")
    second = block("  MISSING REQUIRED BIOS: b.bin", "    Path: /recalbox/share/bios/b.bin\n")

    a, b = adapter.parse_report(first + second)

    assert a.md5s == b.md5s == {HASH.lower()}


def test_entries_for_one_target_stay_separate() -> None:
    text = "SYSTEM: One\n" + block() + "SYSTEM: Two\n" + block()

    one, two = adapter.parse_report(text)

    assert one.target == two.target
    assert (one.system, two.system) == ("One", "Two")


@pytest.mark.parametrize(
    "md5",
    [HASH, HASH.lower(), HASH.title()],
    ids=["uppercase", "lowercase", "mixed"],
)
def test_hash_case_doesnt_matter(md5: str) -> None:
    assert adapter.parse_report(block(hashes=f"      {md5}\n"))[0].md5s == {HASH.lower()}


def test_crlf_and_lf_give_the_same_entries() -> None:
    text = "SYSTEM: One\n---\n\n" + block() + block("  MISSING OPTIONAL BIOS: other.bin")

    assert adapter.parse_report(text.replace("\n", "\r\n")) == adapter.parse_report(text)


def test_crlf_leaves_no_carriage_return_in_any_field() -> None:
    entry = adapter.parse_report(("SYSTEM: One\n" + block()).replace("\n", "\r\n"))[0]

    assert "\r" not in f"{entry.name}{entry.target}{entry.system}"


def test_a_bom_before_the_header_changes_nothing() -> None:
    text = "MISSING BIOS REPORT\n\n" + block()

    assert adapter.parse_report(f"\ufeff{text}") == adapter.parse_report(text)


def test_a_bom_right_before_the_first_block_doesnt_lose_it() -> None:
    assert [entry.name for entry in adapter.parse_report(f"\ufeff{block()}")] == ["scph5501.bin"]


def test_a_bom_right_before_the_first_system_line_keeps_the_system() -> None:
    entry = adapter.parse_report(f"\ufeffSYSTEM: One\n{block()}")[0]

    assert entry.system == "One"


def test_a_bom_decoded_from_real_bytes_is_handled() -> None:
    raw = b"\xef\xbb\xbf" + block().encode()

    assert len(adapter.parse_report(raw.decode("utf-8", errors="replace"))) == 1


def test_bytes_that_arent_utf8_dont_crash_and_keep_the_entry() -> None:
    # Decoded with replacement, as cli.py does. Here the bad byte is outside the fields BECK uses.
    raw = b"Platform: caf\xe9\n" + block("  MISSING REQUIRED BIOS: a.bin").encode()

    entry = adapter.parse_report(raw.decode("utf-8", errors="replace"))[0]

    assert entry.name == "a.bin"


def test_a_bad_byte_in_a_name_is_refused_not_a_crash() -> None:
    raw = b"  MISSING REQUIRED BIOS: caf\xe9.bin\n    Path: /recalbox/share/bios/caf\xe9.bin\n"
    raw += f"    Possible MD5 List:\n      {HASH}\n".encode()

    text = raw.decode("utf-8", errors="replace")

    assert adapter.parse_report(text) == []
    assert adapter.rejected_entries(text)[0].item == "caf\ufffd.bin"


@pytest.mark.parametrize("text", ["", "\n", "\r\n\r\n", "   \n\t\n", "\ufeff"])
def test_an_empty_file_is_not_a_report_with_nothing_missing(text: str) -> None:
    # Recalbox always writes the header, so an empty file means something went wrong.
    with pytest.raises(ReportParseError, match="doesn't look like a report"):
        adapter.parse_report(text)


def test_a_real_header_with_nothing_missing_has_no_entries() -> None:
    real_header = load_report(REAL_REPORT).split("SYSTEM:")[0]

    assert "MISSING BIOS REPORT" in real_header
    assert adapter.parse_report(real_header) == []


def test_a_malformed_block_names_itself_not_its_neighbours() -> None:
    good = block("  MISSING REQUIRED BIOS: good.bin", "    Path: /recalbox/share/bios/good.bin\n")
    bad = block("  MISSING OPTIONAL BIOS: bad.bin", "    Path: /recalbox/share/bios/bad.bin\n", "")

    with pytest.raises(ReportParseError) as error:
        adapter.parse_report(good + bad + good)

    assert "MISSING OPTIONAL BIOS: bad.bin" in str(error.value)
    assert "good.bin" not in str(error.value)


def test_a_block_doesnt_borrow_the_hash_of_the_next_block() -> None:
    no_hash = block("  MISSING REQUIRED BIOS: a.bin", "    Path: /recalbox/share/bios/a.bin\n", "")

    with pytest.raises(ReportParseError, match=r"No MD5 value in report block.*a\.bin"):
        adapter.parse_report(no_hash + block())


def test_a_block_doesnt_borrow_the_path_of_the_next_block() -> None:
    no_path = block("  MISSING REQUIRED BIOS: a.bin", "")

    with pytest.raises(ReportParseError, match=r"No Path line in report block.*a\.bin"):
        adapter.parse_report(no_path + block())


CURRENT = "C" * 32


def incorrect_block(name: str = "b.bin", valid: str = OTHER_HASH) -> str:
    # In the order of Recalbox's Bios::GenerateReport: Path, Notes, For, Current MD5, the list.
    return (
        f"  INCORRECT REQUIRED BIOS: {name}\n"
        f"    Path: /recalbox/share/bios/two/{name}\n"
        "    Notes: a note\n"
        "    For: libretro/x\n"
        f"    Current MD5: {CURRENT}\n"
        f"    Possible MD5 List:\n      {valid}\n\n"
    )


def test_a_real_report_marks_only_its_incorrect_blocks() -> None:
    # Written by Recalbox 10.1.1 after random bytes were placed at two targets on a VM.
    parsed = adapter.parse_report(load_report("recalbox-10.1.1/incorrect-files"))

    assert len(parsed) == 81
    incorrect = {entry.name: entry for entry in parsed if entry.incorrect}
    assert set(incorrect) == {"mcpx_1.0.bin", "MT32_CONTROL.ROM"}

    required = incorrect["mcpx_1.0.bin"]
    assert required.required is True
    assert required.system == "Microsoft Xbox"
    assert required.current_md5 == "d7aa7a14d24dbf344fa702685f5e14f5"
    assert required.md5s == {"d49c52a4102f6df7bcf8d0617ac475ed"}

    optional = incorrect["MT32_CONTROL.ROM"]
    assert optional.required is False
    assert optional.target == PurePosixPath("scummvm/MT32_CONTROL.ROM")
    assert optional.current_md5 == "cd8c839aa6b47dc4ab2c3f96766366fa"

    all_candidates = {md5 for entry in parsed for md5 in entry.md5s}
    assert not {required.current_md5, optional.current_md5} & all_candidates


def test_an_incorrect_block_is_its_own_entry() -> None:
    entry = adapter.parse_report(f"SYSTEM: Two\n{incorrect_block()}")[0]

    assert entry.incorrect is True
    assert entry.name == "b.bin"
    assert entry.target == PurePosixPath("two/b.bin")
    assert entry.md5s == {OTHER_HASH.lower()}
    assert entry.current_md5 == CURRENT.lower()
    assert (entry.required, entry.system) == (True, "Two")


def test_a_missing_block_is_not_incorrect() -> None:
    entry = adapter.parse_report(block())[0]

    assert entry.incorrect is False
    assert entry.current_md5 is None


def test_an_optional_incorrect_block() -> None:
    text = incorrect_block().replace("INCORRECT REQUIRED", "INCORRECT OPTIONAL")

    assert adapter.parse_report(text)[0].required is False


def test_an_incorrect_block_does_not_merge_into_the_entry_above() -> None:
    # The bug: the hashes of b.bin, and its wrong current hash, became candidates for a.bin.
    above = block("  MISSING REQUIRED BIOS: a.bin", "    Path: /recalbox/share/bios/a.bin\n")

    first, second = adapter.parse_report(above + incorrect_block())

    assert first.md5s == {HASH.lower()}
    assert first.target == PurePosixPath("a.bin")
    assert second.name == "b.bin"


def test_an_incorrect_block_does_not_merge_into_the_entry_below() -> None:
    first, second = adapter.parse_report(incorrect_block() + block())

    assert first.md5s == {OTHER_HASH.lower()}
    assert second.md5s == {HASH.lower()}


def test_a_report_with_only_incorrect_blocks_is_not_empty() -> None:
    assert [entry.name for entry in adapter.parse_report(incorrect_block())] == ["b.bin"]


def test_a_current_md5_is_never_a_candidate() -> None:
    entry = adapter.parse_report(incorrect_block())[0]

    assert CURRENT.lower() not in entry.md5s


def test_a_hash_in_a_note_is_not_a_candidate() -> None:
    text = (
        "  MISSING REQUIRED BIOS: a.bin\n"
        "    Path: /recalbox/share/bios/a.bin\n"
        f"    Notes: replaces {OTHER_HASH}\n"
        f"    Possible MD5 List:\n      {HASH}\n"
    )

    assert adapter.parse_report(text)[0].md5s == {HASH.lower()}


def test_hashes_with_no_list_heading_are_an_error() -> None:
    text = f"  MISSING REQUIRED BIOS: a.bin\n    Path: /recalbox/share/bios/a.bin\n      {HASH}\n"

    with pytest.raises(ReportParseError, match="No MD5 value"):
        adapter.parse_report(text)


@pytest.mark.parametrize(
    "heading",
    [
        "ABSENT REQUIRED BIOS: a.bin",
        "MISSING BIOS: a.bin",
        "MISSING MANDATORY BIOS: a.bin",
        "INCORRECT BIOS: a.bin",
        "MISSING: a.bin",
        "MISSING REQUIRED FIRMWARE: a.bin",
    ],
)
@pytest.mark.parametrize("with_a_known_block", [False, True], ids=["alone", "beside-a-known-one"])
def test_a_changed_heading_is_an_error_not_nothing_missing(
    heading: str, with_a_known_block: bool
) -> None:
    text = f"MISSING BIOS REPORT\n\n  {heading}\n    Path: /recalbox/share/bios/a.bin\n"
    if with_a_known_block:
        text += block()

    with pytest.raises(ReportParseError) as error:
        adapter.parse_report(text)

    assert f"Unrecognized heading in the report: {heading}" in str(error.value)


def test_a_changed_title_with_no_blocks_is_an_error() -> None:
    with pytest.raises(ReportParseError, match="no MISSING BIOS REPORT title"):
        adapter.parse_report("BIOS STATUS\nPlatform: x86_64\n")


def test_a_changed_title_with_known_blocks_still_parses() -> None:
    assert len(adapter.parse_report(f"BIOS STATUS\n\n{block()}")) == 1


@pytest.mark.parametrize(
    "text",
    [
        "MISSING BIOS REPORT\n\nSYSTEM: One\n---\n\n",
        f"MISSING BIOS REPORT\n\nSYSTEM: One\n---\n\nSYSTEM: Two\n---\n\n{block()}",
        f"MISSING BIOS REPORT\n\nSYSTEM: Two\n---\n\n{block()}SYSTEM: One\n---\n\n",
    ],
    ids=["only", "first", "last"],
)
def test_a_system_with_no_block_is_an_error(text: str) -> None:
    with pytest.raises(ReportParseError, match="No BIOS block under: SYSTEM:"):
        adapter.parse_report(text)


def test_words_in_a_note_or_path_are_not_headings() -> None:
    text = (
        "  MISSING REQUIRED BIOS: a.bin\n"
        "    Path: /recalbox/share/bios/a.bin\n"
        "    Notes: MISSING BIOS files stop this core\n"
        f"    Possible MD5 List:\n      {HASH}\n"
    )

    assert len(adapter.parse_report(text)) == 1


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
