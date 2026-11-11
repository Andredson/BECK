# SPDX-License-Identifier: GPL-3.0-only
"""beck.exporter: copying a target's .rom and .bin files to a local folder (step 11.12)."""

import os
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from beck.errors import TransportError, UsageError
from beck.exporter import export, is_exported
from beck.models import ExportResult, RemoteFile
from beck.transports.local import LocalTransport
from tests.factories import make_bios_file, snapshot


@pytest.fixture
def device(tmp_path: Path) -> Path:
    folder = tmp_path / "device"
    folder.mkdir()
    return folder


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "out"


def run(device: Path, out: Path, *, dry_run: bool = False) -> ExportResult:
    with LocalTransport(device) as transport:
        return export(transport, out, dry_run=dry_run)


def paths(files: tuple[RemoteFile, ...]) -> list[str]:
    return [file.path.as_posix() for file in files]


def files_in(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize(
    ("name", "exported"),
    [
        ("a.rom", True),
        ("a.bin", True),
        ("ATARIBAS.ROM", True),
        ("Scph.Bin", True),
        ("neogeo.zip", False),
        ("tos.img", False),
        ("kick34005.A500", False),
        ("a.bin.txt", False),
        ("rom", False),
    ],
)
def test_only_rom_and_bin_files_in_any_case_are_exported(name: str, exported: bool) -> None:
    assert is_exported(RemoteFile(PurePosixPath(name), 1)) is exported


def test_a_full_export_copies_each_file_in_its_folder(device: Path, out: Path) -> None:
    make_bios_file(device, "ps1/scph1001.bin")
    make_bios_file(device, "atari800/ATARIBAS.ROM")
    make_bios_file(device, "Machines/MSX - C-BIOS/cbios_main_msx1.rom")
    make_bios_file(device, "top.bin")
    make_bios_file(device, "neogeo.zip")
    make_bios_file(device, "atarist/tos.img")
    make_bios_file(device, "ps1/readme.txt")
    before = snapshot(device)

    result = run(device, out)

    assert paths(result.copied) == [
        "Machines/MSX - C-BIOS/cbios_main_msx1.rom",
        "atari800/ATARIBAS.ROM",
        "ps1/scph1001.bin",
        "top.bin",
    ]
    assert files_in(out) == {
        path: data for path, data in files_in(device).items() if path in paths(result.copied)
    }
    assert result.on_target == 7
    assert result.left_out == 3
    assert not (result.errors or result.existing or result.planned or result.failed)
    assert snapshot(device) == before  # the target is unchanged


def test_each_copy_has_the_size_the_target_listed(device: Path, out: Path) -> None:
    make_bios_file(device, "big.bin", os.urandom(300_000))

    result = run(device, out)

    assert result.copied[0].size == 300_000 == (out / "big.bin").stat().st_size


def test_a_dry_run_writes_nothing_not_even_the_folder(device: Path, out: Path) -> None:
    make_bios_file(device, "ps1/scph1001.bin")
    make_bios_file(device, "neogeo.zip")

    result = run(device, out, dry_run=True)

    assert paths(result.planned) == ["ps1/scph1001.bin"]
    assert result.copied == ()
    assert result.left_out == 1
    assert not out.exists()


def test_a_dry_run_lists_files_already_here_as_existing(device: Path, out: Path) -> None:
    make_bios_file(device, "a.bin")
    make_bios_file(device, "b.bin")
    make_bios_file(out, "a.bin")

    result = run(device, out, dry_run=True)

    assert paths(result.existing) == ["a.bin"]
    assert paths(result.planned) == ["b.bin"]


def test_a_file_already_here_is_kept_as_it_is(device: Path, out: Path) -> None:
    make_bios_file(device, "ps1/a.bin")
    mine = make_bios_file(out, "ps1/a.bin", b"the user's own copy")
    make_bios_file(device, "ps1/b.bin")

    result = run(device, out)

    assert paths(result.existing) == ["ps1/a.bin"]
    assert paths(result.copied) == ["ps1/b.bin"]
    assert mine.path.read_bytes() == b"the user's own copy"


def test_a_link_already_here_counts_as_a_file_and_is_kept(
    device: Path, out: Path, tmp_path: Path
) -> None:
    make_bios_file(device, "a.bin")
    out.mkdir()
    (out / "a.bin").symlink_to(tmp_path / "nowhere")

    result = run(device, out)

    assert paths(result.existing) == ["a.bin"]
    assert not (tmp_path / "nowhere").exists()


def test_running_again_copies_nothing_and_changes_nothing(device: Path, out: Path) -> None:
    make_bios_file(device, "ps1/a.bin")
    run(device, out)
    after_first = snapshot(out)

    second = run(device, out)

    assert paths(second.existing) == ["ps1/a.bin"]
    assert second.copied == ()
    assert snapshot(out) == after_first


def test_a_file_that_cannot_be_read_fails_and_the_rest_carry_on(
    device: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_bios_file(device, "a.bin")
    make_bios_file(device, "b.bin")
    real = LocalTransport.read_bytes

    def refuse_a(self: LocalTransport, path: PurePosixPath) -> bytes:
        if path.name == "a.bin":
            raise TransportError("Error reading a.bin: refused")
        return real(self, path)

    monkeypatch.setattr(LocalTransport, "read_bytes", refuse_a)

    result = run(device, out)

    assert paths(result.failed) == ["a.bin"]
    assert paths(result.copied) == ["b.bin"]
    assert [(e.item, e.code, e.message) for e in result.errors] == [
        ("a.bin", "transport", "Error reading a.bin: refused")
    ]
    assert not (out / "a.bin").exists()  # a failed read leaves nothing behind


def test_a_file_whose_size_changed_is_not_written(
    device: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_bios_file(device, "a.bin")
    monkeypatch.setattr(LocalTransport, "read_bytes", lambda _self, _path: b"short")

    result = run(device, out)

    assert paths(result.failed) == ["a.bin"]
    assert [e.code for e in result.errors] == ["size_mismatch"]
    assert "a.bin has 5 bytes when read, but the target listed 64" in result.errors[0].message
    assert not (out / "a.bin").exists()


def test_a_file_where_a_folder_must_go_fails_that_file_only(device: Path, out: Path) -> None:
    make_bios_file(device, "ps1/a.bin")
    make_bios_file(device, "b.bin")
    make_bios_file(out, "ps1", b"a file, not a folder")

    result = run(device, out)

    assert paths(result.failed) == ["ps1/a.bin"]
    assert paths(result.copied) == ["b.bin"]
    assert [e.code for e in result.errors] == ["write_failed"]
    assert result.errors[0].message.startswith(f"Couldn't create the folder {out / 'ps1'}: ")


def test_a_file_that_cannot_be_written_fails_that_file_only(
    device: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_bios_file(device, "a.bin")
    make_bios_file(device, "b.bin")
    real_open: Any = Path.open

    def full_disk(self: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
        if self.name == "a.bin" and mode == "xb":
            raise OSError(28, "No space left on device")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", full_disk)

    result = run(device, out)

    assert paths(result.failed) == ["a.bin"]
    assert result.errors[0].message == f"Couldn't write {out / 'a.bin'}: No space left on device"
    assert paths(result.copied) == ["b.bin"]


def test_a_write_that_fails_partway_says_to_delete_what_is_left(
    device: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_bios_file(device, "a.bin")

    class FailingFile:
        def __enter__(self) -> "FailingFile":
            return self

        def __exit__(self, *_exc: object) -> None:
            pass

        def write(self, _data: bytes) -> int:
            raise OSError(28, "No space left on device")

    real_open: Any = Path.open

    def failing(self: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
        if mode == "xb":
            return FailingFile()
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing)

    result = run(device, out)

    assert [e.code for e in result.errors] == ["write_failed"]
    assert "Part of it may be there: delete it before you export again" in result.errors[0].message


def test_a_file_that_appears_meanwhile_is_kept(
    device: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_bios_file(device, "a.bin")
    real = LocalTransport.read_bytes

    def someone_writes_it_meanwhile(self: LocalTransport, path: PurePosixPath) -> bytes:
        data = real(self, path)
        make_bios_file(out, "a.bin", b"written meanwhile")
        return data

    monkeypatch.setattr(LocalTransport, "read_bytes", someone_writes_it_meanwhile)

    result = run(device, out)

    assert paths(result.existing) == ["a.bin"]
    assert (out / "a.bin").read_bytes() == b"written meanwhile"


def test_a_link_in_the_destination_is_not_followed(device: Path, out: Path, tmp_path: Path) -> None:
    make_bios_file(device, "ps1/a.bin")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out.mkdir()
    (out / "ps1").symlink_to(elsewhere)

    result = run(device, out)

    assert paths(result.failed) == ["ps1/a.bin"]
    assert [e.code for e in result.errors] == ["unsafe_path"]
    assert result.errors[0].message == (
        f"Refused ps1/a.bin: {out / 'ps1'} is a link, and export doesn't follow links"
    )
    assert list(elsewhere.iterdir()) == []


def test_a_destination_that_cannot_be_created_is_a_usage_error(
    device: Path, tmp_path: Path
) -> None:
    make_bios_file(device, "a.bin")
    make_bios_file(tmp_path, "file")

    with pytest.raises(UsageError, match=r"^Can't create the folder .*/file/out: "):
        run(device, tmp_path / "file" / "out")


def test_a_target_with_nothing_to_export_gives_an_empty_result(device: Path, out: Path) -> None:
    make_bios_file(device, "neogeo.zip")

    result = run(device, out)

    assert result.chosen == ()
    assert result.left_out == 1


def test_a_target_that_cannot_be_listed_raises(device: Path, out: Path) -> None:
    with LocalTransport(device) as transport:
        device.rmdir()
        with pytest.raises(TransportError):
            export(transport, out, dry_run=False)
    assert not out.exists()
