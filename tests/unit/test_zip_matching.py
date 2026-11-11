# SPDX-License-Identifier: GPL-3.0-only
"""Zip-aware matching (step 11.4, DEC-78): members of zip archives, and zips matched by contents.

Every archive here holds random bytes, never real BIOS content.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from beck import cli, hashing
from beck.hashing import scan
from beck.matcher import plan
from beck.models import LocalFile, Plan
from tests.factories import contents_md5, make_bios_file, make_missing, make_report_text, make_zip
from tests.factories import md5_of as md5


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "source"
    folder.mkdir()
    return folder


@pytest.fixture
def device(tmp_path: Path) -> Path:
    folder = tmp_path / "device"
    folder.mkdir()
    return folder


def report(device: Path, *entries: object) -> None:
    (device / "missing_bios_report.txt").write_text(
        make_report_text(entries),  # type: ignore[arg-type]
        encoding="utf-8",
        newline="",
    )


def check(source: Path, device: Path, *flags: str) -> list[str]:
    return ["check", "--source", str(source), "--target-dir", str(device), *flags]


def members(folder: Path) -> list[LocalFile]:
    return [file for file in scan(folder).files if file.member is not None]


def filled(result: Plan) -> dict[str, str]:
    return {
        u.target.as_posix(): f"{u.source.relative}:{u.source.member or ''}" for u in result.uploads
    }


# Scanning: members, and the contents MD5 Recalbox uses


def test_a_zip_is_listed_with_its_members_in_nested_folders(source: Path) -> None:
    deep, top = os.urandom(64), os.urandom(32)
    make_zip(source, "bios.zip", {"ps1/x/deep.bin": deep, "top.rom": top})

    files = scan(source).files

    assert [(f.relative.as_posix(), f.member, f.md5, f.size) for f in files] == [
        (
            "bios.zip",
            None,
            md5((source / "bios.zip").read_bytes()),
            (source / "bios.zip").stat().st_size,
        ),
        ("bios.zip", "ps1/x/deep.bin", md5(deep), 64),
        ("bios.zip", "top.rom", md5(top), 32),
    ]
    assert files[0].is_zip and not files[1].is_zip


def test_the_contents_md5_follows_the_names_sorted_not_the_order_in_the_archive(
    source: Path,
) -> None:
    # Recalbox's Zip::Md5Composite sorts the names, so the order they were added in doesn't count.
    content = {"z.bin": os.urandom(64), "a.bin": os.urandom(64), "M.bin": os.urandom(64)}
    make_zip(source, "first.zip", content)
    make_zip(source, "second.zip", dict(reversed(content.items())))

    archives = [file for file in scan(source).files if file.member is None]

    expected = md5(content["M.bin"] + content["a.bin"] + content["z.bin"])  # byte order: M < a
    assert [archive.contents_md5 for archive in archives] == [expected, expected]
    assert archives[0].md5 != archives[1].md5


def with_raw_name(path: Path, placeholder: bytes, raw: bytes) -> None:
    """Give a member a name Python wouldn't write: its raw bytes, with no UTF-8 flag."""
    assert len(placeholder) == len(raw)
    data = path.read_bytes()
    assert data.count(placeholder) == 2  # in the local header and in the central directory
    path.write_bytes(data.replace(placeholder, raw))


def test_folders_and_encrypted_members_add_nothing_to_the_contents_md5(source: Path) -> None:
    data = os.urandom(64)
    path = make_zip(source, "a.zip", {"folder/": b"", "folder/a.bin": data, "locked.bin": b"x"})
    # Python clears the encryption flag when it writes, so set it where readers look for it: the
    # central directory entry, 8 bytes in. Recalbox can't open an encrypted member, so it skips it.
    raw = bytearray(path.read_bytes())
    entry = raw.index(b"PK\x01\x02", raw.index(b"PK\x01\x02") + 1)
    entry = raw.index(b"PK\x01\x02", entry + 1)
    assert raw[entry + 46 : entry + 56] == b"locked.bin"
    raw[entry + 8] |= 0x1
    path.write_bytes(bytes(raw))

    files = scan(source).files

    assert files[0].contents_md5 == md5(data)
    assert [file.member for file in files[1:]] == ["folder/a.bin"]


def test_names_sort_as_libzip_gives_them_to_recalbox(source: Path) -> None:
    # libzip reads a name as UTF-8 if it's valid UTF-8, and otherwise as CP437, turned into UTF-8.
    # Recalbox then sorts those UTF-8 bytes. Python reads any name without the UTF-8 flag as CP437.
    path = make_zip(
        source,
        "a.zip",
        {"QQ.bin": b"utf8-e", "b.bin": b"b", "\u0219.bin": b"s-comma", "Q1.bin": b"cp437-e"},
    )
    with_raw_name(path, b"QQ.bin", "\u00e9.bin".encode())  # UTF-8 bytes, no flag: C3 A9 2E
    with_raw_name(path, b"Q1.bin", b"\x821.bin")  # CP437 e-acute isn't UTF-8: becomes C3 A9 31

    # b (62) < e-acute then "." (C3 A9 2E) < e-acute then "1" (C3 A9 31) < s-comma (C8 99)
    assert scan(source).files[0].contents_md5 == md5(b"b" + b"utf8-e" + b"cp437-e" + b"s-comma")


def test_a_damaged_zip_is_still_a_file_but_its_members_are_unreadable(source: Path) -> None:
    path = make_zip(source, "bad.zip", {"a.bin": os.urandom(4096)})
    data = bytearray(path.read_bytes())
    data[40:80] = os.urandom(40)  # inside the compressed member
    path.write_bytes(bytes(data))

    result = scan(source)

    assert [(f.relative.as_posix(), f.member, f.contents_md5) for f in result.files] == [
        ("bad.zip", None, None)
    ]
    assert result.unreadable[0].relative.as_posix() == "bad.zip"
    assert result.unreadable[0].reason.startswith("its members weren't read, because ")


def test_an_archive_with_too_many_members_is_not_opened(
    source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hashing, "MAX_MEMBERS", 2)
    make_zip(source, "many.zip", {"a": b"1", "b": b"2", "c": b"3"})

    result = scan(source)

    assert members(source) == []
    assert result.files[0].contents_md5 is None
    assert (
        result.unreadable[0].reason
        == "its members weren't read, because it has more than 2 members"
    )


def test_an_archive_that_unpacks_too_big_is_stopped_while_reading(
    source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hashing, "MAX_UNPACKED", 3 * 2**20)
    make_zip(source, "bomb.zip", {"a.bin": bytes(2 * 2**20), "b.bin": bytes(2 * 2**20)})

    result = scan(source)

    assert members(source) == []
    assert "it unpacks to more than 3 MiB" in result.unreadable[0].reason


def test_the_built_in_limits_are_1000_members_and_512_mib() -> None:
    assert (hashing.MAX_MEMBERS, hashing.MAX_UNPACKED) == (1000, 512 * 2**20)


# Matching


def test_a_member_fills_a_target_that_is_not_a_zip(source: Path) -> None:
    bios = os.urandom(64)
    make_zip(source, "psx.zip", {"bios/scph1001.bin": bios, "readme.txt": b"text"})

    result = plan([make_missing("ps1/scph1001.bin", md5(bios))], scan(source).files)

    assert filled(result) == {"ps1/scph1001.bin": "psx.zip:bios/scph1001.bin"}
    assert result.unmatched == ()


def test_a_zip_fills_a_zip_target_by_its_contents(source: Path) -> None:
    content = {"000-lo.lo": os.urandom(64), "sp-s2.sp1": os.urandom(64)}
    make_zip(source, "my-neogeo.zip", content)

    result = plan([make_missing("neogeo.zip", contents_md5(content))], scan(source).files)

    assert filled(result) == {"neogeo.zip": "my-neogeo.zip:"}


def test_a_zip_still_fills_a_zip_target_by_its_own_md5(source: Path) -> None:
    path = make_zip(source, "a.zip", {"x": os.urandom(8)})

    result = plan([make_missing("a.zip", md5(path.read_bytes()))], scan(source).files)

    assert filled(result) == {"a.zip": "a.zip:"}


def test_a_one_file_zip_does_not_fill_a_bin_target_by_its_contents(source: Path) -> None:
    bios = os.urandom(64)
    make_zip(source, "neocd.zip", {"neocd.bin": bios})  # contents MD5 == neocd.bin's MD5

    result = plan([make_missing("neocd/neocd.bin", md5(bios))], scan(source).files)

    assert filled(result) == {"neocd/neocd.bin": "neocd.zip:neocd.bin"}  # the member, not the zip


def test_a_member_never_fills_a_zip_target(source: Path) -> None:
    bios = os.urandom(64)
    make_zip(source, "cd.zip", {"neocd.bin": bios, "other": os.urandom(8)})

    result = plan([make_missing("neocdz.zip", md5(bios))], scan(source).files)

    assert result.uploads == ()
    assert [(u.source.member, u.target.as_posix()) for u in result.not_a_zip] == [
        ("neocd.bin", "neocdz.zip")
    ]


def test_a_plain_file_wins_over_an_identical_member(source: Path) -> None:
    bios = os.urandom(64)
    make_zip(source, "a.zip", {"scph1001.bin": bios})
    make_bios_file(source, "z/scph1001.bin", bios)

    result = plan([make_missing("ps1/scph1001.bin", md5(bios))], scan(source).files)

    assert filled(result) == {"ps1/scph1001.bin": "z/scph1001.bin:"}
    assert [(d.file.member, d.of.member) for d in result.duplicates] == [("scph1001.bin", None)]


def test_an_archive_is_unmatched_only_if_nothing_in_it_matched(source: Path) -> None:
    bios = os.urandom(64)
    make_zip(source, "used.zip", {"a.bin": bios, "junk": os.urandom(8)})
    make_zip(source, "unused.zip", {"b.bin": os.urandom(64)})

    result = plan([make_missing("a.bin", md5(bios))], scan(source).files)

    assert [(f.relative.as_posix(), f.member) for f in result.unmatched] == [("unused.zip", None)]


# Running: uploads, deleting


def test_a_run_uploads_a_member_and_a_zip_and_leaves_the_archives(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bios = os.urandom(64)
    psx = make_zip(source, "psx.zip", {"bios/scph1001.bin": bios})
    neogeo = {"000-lo.lo": os.urandom(64), "sp-s2.sp1": os.urandom(64)}
    mine = make_zip(source, "my-neogeo.zip", neogeo)
    before = {path: path.read_bytes() for path in (psx, mine)}
    report(
        device,
        make_missing("ps1/scph1001.bin", md5(bios)),
        make_missing("neogeo.zip", contents_md5(neogeo)),
    )

    assert cli.main(check(source, device, "--verify")) == 0

    assert (device / "ps1" / "scph1001.bin").read_bytes() == bios
    assert (device / "neogeo.zip").read_bytes() == before[mine]
    assert {path: path.read_bytes() for path in before} == before
    output = capsys.readouterr().out
    assert "bios/scph1001.bin (in psx.zip): copied -> ps1/scph1001.bin" in output
    assert "my-neogeo.zip: copied -> neogeo.zip" in output


def test_the_temporary_copy_of_a_member_is_gone_afterwards(
    source: Path, device: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setenv("TMPDIR", str(temporary))
    monkeypatch.setattr("tempfile.tempdir", None)
    bios = os.urandom(64)
    make_zip(source, "psx.zip", {"scph1001.bin": bios})
    report(device, make_missing("scph1001.bin", md5(bios)))

    assert cli.main(check(source, device)) == 0

    assert (device / "scph1001.bin").read_bytes() == bios
    assert list(temporary.iterdir()) == []


def test_move_never_deletes_an_archive_because_of_a_member(source: Path, device: Path) -> None:
    bios = os.urandom(64)
    psx = make_zip(source, "psx.zip", {"scph1001.bin": bios})
    report(device, make_missing("scph1001.bin", md5(bios)))

    assert cli.main(check(source, device, "--move", "--yes")) == 0

    assert psx.exists()


def test_move_deletes_an_archive_uploaded_whole_once_all_its_uploads_worked(
    source: Path, device: Path
) -> None:
    bios = os.urandom(64)
    content = {"scph1001.bin": bios, "other": os.urandom(8)}
    archive = make_zip(source, "a.zip", content)
    report(
        device,
        make_missing("a.zip", contents_md5(content)),
        make_missing("scph1001.bin", md5(bios)),
    )

    assert cli.main(check(source, device, "--move", "--yes")) == 0

    assert (device / "a.zip").exists() and (device / "scph1001.bin").exists()
    assert not archive.exists()


def test_move_keeps_an_archive_if_an_upload_from_it_failed(source: Path, device: Path) -> None:
    bios = os.urandom(64)
    content = {"scph1001.bin": bios, "other": os.urandom(8)}
    archive = make_zip(source, "a.zip", content)
    (device / "ps1").write_bytes(b"a file where a folder must go")
    report(
        device,
        make_missing("a.zip", contents_md5(content)),
        make_missing("ps1/scph1001.bin", md5(bios)),
    )

    assert cli.main(check(source, device, "--move", "--yes")) == 3

    assert (device / "a.zip").exists()
    assert archive.exists()


def test_clean_unmatched_keeps_an_archive_with_a_used_member(source: Path, device: Path) -> None:
    bios = os.urandom(64)
    used = make_zip(source, "used.zip", {"a.bin": bios})
    unused = make_zip(source, "unused.zip", {"b.bin": os.urandom(64)})
    report(device, make_missing("a.bin", md5(bios)))

    assert cli.main(check(source, device, "--clean-unmatched", "--yes")) == 0

    assert used.exists()
    assert not unused.exists()


def test_clean_unmatched_keeps_an_archive_with_a_member_valid_for_an_incorrect_file(
    source: Path, device: Path
) -> None:
    bios = os.urandom(64)
    archive = make_zip(source, "fix.zip", {"bad.bin": bios})
    make_bios_file(device, "bad.bin")
    report(
        device, make_missing("bad.bin", md5(bios), incorrect=True), make_missing("x.bin", "a" * 32)
    )

    assert cli.main(check(source, device, "--clean-unmatched", "--yes")) == 0

    assert archive.exists()


def test_a_member_that_changed_since_the_scan_fails_its_upload(
    source: Path, device: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bios = os.urandom(64)
    path = make_zip(source, "psx.zip", {"scph1001.bin": bios})
    report(device, make_missing("scph1001.bin", md5(bios)))
    real_scan = scan

    def scan_then_replace(folder: Path, on_file: object = None) -> object:
        result = real_scan(folder)
        make_zip(source, "psx.zip", {"other.bin": b"x"})
        return result

    monkeypatch.setattr(cli, "scan", scan_then_replace)

    assert cli.main(["--json", *check(source, device)]) == 3

    assert path.exists()
    assert not (device / "scph1001.bin").exists()


def test_scan_shows_members_and_the_contents_md5(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = {"000-lo.lo": b"lo", "sp-s2.sp1": b"sp"}
    archive = make_zip(source, "neogeo.zip", content)

    assert cli.main(["scan", "--source", str(source)]) == 0

    lines = capsys.readouterr().out.splitlines()
    whole = md5(archive.read_bytes())
    assert lines[0].startswith(f"{whole}  ")
    assert lines[0].endswith("  neogeo.zip")
    assert lines[1].endswith("  neogeo.zip (contents)")
    assert lines[1].startswith(contents_md5(content))
    assert lines[2].endswith("  000-lo.lo (in neogeo.zip)")
    assert lines[3].endswith("  sp-s2.sp1 (in neogeo.zip)")


def test_json_check_names_the_member_of_an_upload(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bios = os.urandom(64)
    make_zip(source, "psx.zip", {"bios/scph1001.bin": bios})
    report(device, make_missing("ps1/scph1001.bin", md5(bios)))

    assert cli.main(["--json", *check(source, device)]) == 0

    upload = json.loads(capsys.readouterr().out)["uploads"][0]
    assert (upload["source"], upload["member"], upload["md5"]) == (
        "psx.zip",
        "bios/scph1001.bin",
        hashlib.md5(bios, usedforsecurity=False).hexdigest(),
    )
