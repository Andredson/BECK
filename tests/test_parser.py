"""parse_report on real and derived reports (D2, D10, DEC-50), and the CRLF regression from 03.3."""

from typing import Any

import pytest

import check_bios
from tests.conftest import REAL_REPORT, REPORT_NAMES, load_expected, load_report
from tests.fakes import FakeSMBServer, install_fake_smb

HASH = "490F666E1AFB15B7362B406ED1CEA246"
OTHER_HASH = "8DD7D5296A650FAC7319BCE665A6A53C"


def block(
    heading: str = "  MISSING REQUIRED BIOS: scph5501.bin",
    path: str = "    Path: /recalbox/share/bios/scph5501.bin\n",
    hashes: str = f"      {HASH}\n",
) -> str:
    return f"{heading}\n{path}    For: libretro/pcsx_rearmed\n    Possible MD5 List:\n{hashes}\n"


def with_lowercase_hashes(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Step 03.6 lowercases every MD5, so these tests compare without regard to case.
    return [{**e, "hashes": [h.lower() for h in e["hashes"]]} for e in entries]


@pytest.mark.parametrize("name", REPORT_NAMES)
def test_parser_matches_the_expected_entries(name: str) -> None:
    parsed = check_bios.parse_report(load_report(name))

    assert with_lowercase_hashes(parsed) == with_lowercase_hashes(load_expected(name))


def test_crlf_report_read_over_smb_keeps_every_entry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Regression from step 03.3: CRLF merged the whole real report into one entry.
    server: FakeSMBServer = install_fake_smb(monkeypatch)
    server.files[("bios", "missing_bios_report.txt")] = load_report(REAL_REPORT).encode()

    with check_bios.SmbSession("beck-test-server", 445, "", "", "bios") as session:
        missing = check_bios.get_missing_bios(session)

    assert len(missing) == 238
    assert missing[0]["name"] == "kick39106.A1200"
    assert missing[0]["hashes"] == ["B7CC148386AA631136F510CD29E42FC3"]
    assert "238" in capsys.readouterr().out


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

    assert check_bios.parse_report(text)[0]["name"] == name


def test_two_locations_use_the_first() -> None:
    path = "    Path: /recalbox/share/bios/neogeo.zip or /recalbox/share/roms/neogeo/neogeo.zip\n"

    entry = check_bios.parse_report(block("  MISSING REQUIRED BIOS: neogeo.zip", path))[0]

    assert entry["path"] == "/recalbox/share/bios/"
    assert entry["relativePath"] == ""


def test_nested_folder() -> None:
    path = "    Path: /recalbox/share/bios/amiga/bios/kick39106.A1200\n"

    entry = check_bios.parse_report(block("  MISSING REQUIRED BIOS: kick39106.A1200", path))[0]

    assert entry["path"] == "/recalbox/share/bios/amiga/bios/"
    assert entry["relativePath"] == "amiga/bios/"


def test_repeated_hashes_are_removed_in_first_seen_order() -> None:
    text = block(hashes=f"      {OTHER_HASH}\n      {HASH}\n      {OTHER_HASH}\n")

    assert check_bios.parse_report(text)[0]["hashes"] == [OTHER_HASH, HASH]


def test_longer_hex_strings_are_not_split_into_fake_hashes() -> None:
    text = block(hashes=f"      {HASH}\n      {OTHER_HASH}FF\n")

    assert check_bios.parse_report(text)[0]["hashes"] == [HASH]


def test_blocks_do_not_need_a_blank_line_between_them() -> None:
    text = block().rstrip("\n") + "\n" + block("  MISSING OPTIONAL BIOS: other.bin")

    assert [e["name"] for e in check_bios.parse_report(text)] == ["scph5501.bin", "other.bin"]


def test_report_with_nothing_missing_has_no_entries() -> None:
    assert check_bios.parse_report("MISSING BIOS REPORT\nPlatform: x86_64\n") == []


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
    with pytest.raises(check_bios.ReportParseError) as error:
        check_bios.parse_report(text)

    assert str(error.value) == message


def test_no_missing_bios_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = install_fake_smb(monkeypatch)
    server.files[("bios", "missing_bios_report.txt")] = b"MISSING BIOS REPORT\r\n"

    with (
        pytest.raises(SystemExit),
        check_bios.SmbSession("beck-test-server", 445, "", "", "bios") as session,
    ):
        check_bios.get_missing_bios(session)

    assert "No missing bios" in capsys.readouterr().out
    assert server.connections[0].closed
