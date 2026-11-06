# SPDX-License-Identifier: GPL-3.0-only
"""The shared factories: they must produce what the real code and the real reports do."""

import hashlib
from pathlib import Path, PurePosixPath

from beck.frontends.recalbox import RecalboxAdapter
from beck.hashing import scan
from tests.conftest import REAL_REPORT, load_report
from tests.factories import (
    make_bios_file,
    make_local_file,
    make_missing,
    make_report_text,
    md5_of,
    snapshot,
)

A, B = "a" * 32, "b" * 32
adapter = RecalboxAdapter()


def test_bios_file_is_random_bytes_on_disk_with_its_real_md5(tmp_path: Path) -> None:
    file = make_bios_file(tmp_path, "ps1/copy.bin")
    other = make_bios_file(tmp_path, "other.bin")
    data = (tmp_path / "ps1" / "copy.bin").read_bytes()

    assert file.path == tmp_path / "ps1" / "copy.bin"
    assert file.relative == PurePosixPath("ps1/copy.bin")
    assert file.md5 == hashlib.md5(data, usedforsecurity=False).hexdigest()
    assert file.size == len(data) > 0
    assert other.md5 != file.md5


def test_bios_file_with_given_content(tmp_path: Path) -> None:
    file = make_bios_file(tmp_path, "empty.bin", b"")

    assert file.path.read_bytes() == b""
    assert file.size == 0
    assert file.md5 == md5_of(b"")


def test_bios_file_matches_what_the_scanner_finds(tmp_path: Path) -> None:
    file = make_bios_file(tmp_path, "a/b/file.bin")

    assert scan(tmp_path).files == (file,)


def test_local_file_touches_nothing_on_disk() -> None:
    file = make_local_file("ps1/copy.bin", A, size=4)

    assert not file.path.exists()
    assert (file.relative, file.md5, file.size) == (PurePosixPath("ps1/copy.bin"), A, 4)


def test_missing_entry_takes_its_name_from_the_target() -> None:
    entry = make_missing("amiga/bios/kick.rom", A, B, required=False, system="Amiga")

    assert entry.name == "kick.rom"
    assert entry.target == PurePosixPath("amiga/bios/kick.rom")
    assert entry.md5s == {A, B}
    assert (entry.required, entry.system) == (False, "Amiga")


def test_a_rendered_report_parses_back_to_the_same_entries() -> None:
    entries = [
        make_missing("7800 BIOS (U).rom", A, system="Atari 7800"),
        make_missing("ps1/scph-1001.bin", A, B, system="PlayStation"),
        make_missing("amiga/bios/kick.CD32.ext", B, required=False, system="PlayStation"),
        make_missing("no-system-repeats.bin", A, required=False, system="Other"),
    ]

    assert adapter.parse_report(make_report_text(entries)) == entries


def test_a_system_heading_appears_once_for_entries_in_a_row() -> None:
    entries = [make_missing(name, A, system="PlayStation") for name in ("a.bin", "b.bin")]

    assert make_report_text(entries).count("SYSTEM: PlayStation") == 1


def test_an_incorrect_entry_parses_back_the_same() -> None:
    entries = [
        make_missing("a.bin", A, system="One"),
        make_missing("b.bin", B, system="One", incorrect=True, current_md5="c" * 32),
    ]

    assert adapter.parse_report(make_report_text(entries)) == entries


def test_every_real_entry_survives_rendering_and_parsing() -> None:
    real = adapter.parse_report(load_report(REAL_REPORT))

    assert len(real) == 238
    assert adapter.parse_report(make_report_text(real)) == real


def test_the_rendered_text_has_the_real_format() -> None:
    real_text = load_report(REAL_REPORT)
    first = adapter.parse_report(real_text)[0]

    rendered = make_report_text([first])
    same_for_line = rendered.replace("libretro/beck-test", "amiberry")

    # Word for word the same as the real report, except for the "For" line, which BECK ignores.
    assert same_for_line == real_text[: len(same_for_line)]
    assert "\r\n" in rendered
    assert "\n" not in rendered.replace("\r\n", "")


def test_a_report_with_no_entries_has_nothing_missing() -> None:
    assert adapter.parse_report(make_report_text([])) == []


def test_snapshot_notices_each_kind_of_change(tmp_path: Path) -> None:
    file = make_bios_file(tmp_path, "sub/a.bin", b"1234")
    before = snapshot(tmp_path)

    assert snapshot(tmp_path) == before
    assert set(before) == {"sub/a.bin"}

    file.path.write_bytes(b"12345")
    assert snapshot(tmp_path) != before

    file.path.unlink()
    assert snapshot(tmp_path) == {}
