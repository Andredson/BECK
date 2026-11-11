# SPDX-License-Identifier: GPL-3.0-only
"""beck.hashing: ported from the stage 03 tests (D1, D5, D8), without the printed messages."""

import hashlib
import os
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from beck.hashing import md5_file, scan
from beck.models import LocalFile, ScanResult, Unreadable
from tests.factories import make_bios_file


def write(path: Path, data: bytes = b"\x00\x01") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def relatives(found: tuple[LocalFile, ...]) -> list[str]:
    return [item.relative.as_posix() for item in found]


def test_md5_is_lowercase_and_correct(tmp_path: Path) -> None:
    data = os.urandom(1024)

    digest = md5_file(write(tmp_path / "bios.bin", data))

    assert digest == hashlib.md5(data, usedforsecurity=False).hexdigest()
    assert digest == digest.lower()


def test_md5_of_a_file_larger_than_one_chunk(tmp_path: Path) -> None:
    data = os.urandom(3 * 1024 * 1024)

    digest = md5_file(write(tmp_path / "big.bin", data))

    assert digest == hashlib.md5(data, usedforsecurity=False).hexdigest()


def test_md5_uses_the_chunked_file_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = write(tmp_path / "bios.bin", os.urandom(1024))
    calls = []
    real = hashlib.file_digest

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(hashlib, "file_digest", spy)

    md5_file(file)

    assert len(calls) == 1


def test_a_zip_archive_is_known_by_its_content_not_its_name(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "archive-named.bin", "w") as archive:
        archive.writestr("inside.rom", os.urandom(64))
    write(tmp_path / "raw-named.zip", os.urandom(64))
    write(tmp_path / "raw.bin", os.urandom(64))

    is_zip = {file.relative.as_posix(): file.is_zip for file in scan(tmp_path).files}

    assert is_zip == {"archive-named.bin": True, "raw-named.zip": False, "raw.bin": False}


def test_keep_file_is_ignored(tmp_path: Path) -> None:
    write(tmp_path / ".keep", b"")
    write(tmp_path / "scph5501.bin")

    assert relatives(scan(tmp_path).files) == ["scph5501.bin"]


def test_hidden_folders_are_not_entered(tmp_path: Path) -> None:
    write(tmp_path / ".git" / "config.bin")
    write(tmp_path / "ps1" / ".hidden" / "x.bin")
    write(tmp_path / "ps1" / "visible.bin")

    assert relatives(scan(tmp_path).files) == ["ps1/visible.bin"]


def test_empty_sub_folder_does_not_stop_the_scan(tmp_path: Path) -> None:
    (tmp_path / "aaa-empty").mkdir()
    write(tmp_path / "zzz" / "late.bin")

    assert relatives(scan(tmp_path).files) == ["zzz/late.bin"]


def test_nested_file_has_its_path_hash_and_size(tmp_path: Path) -> None:
    data = os.urandom(64)
    file = write(tmp_path / "a" / "b" / "file.bin", data)

    assert scan(tmp_path).files == (
        LocalFile(
            path=file,
            relative=PurePosixPath("a/b/file.bin"),
            md5=hashlib.md5(data, usedforsecurity=False).hexdigest(),
            size=64,
        ),
    )


def test_relative_folder_argument_gives_the_same_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path / "bios" / "ps1" / "file.bin")
    monkeypatch.chdir(tmp_path)

    found = scan(Path("./bios")).files

    assert relatives(found) == ["ps1/file.bin"]
    assert found[0].path.read_bytes() == b"\x00\x01"


def test_results_are_sorted_by_path(tmp_path: Path) -> None:
    for name in ("z.bin", "a/m.bin", "b.bin"):
        write(tmp_path / name)

    assert relatives(scan(tmp_path).files) == ["a/m.bin", "b.bin", "z.bin"]


def test_paths_sort_as_text_like_stage_03(tmp_path: Path) -> None:
    # As text, "-" sorts before "/". PurePosixPath compares folder by folder, the other way round,
    # and "first by path" decides which file wins a target.
    write(tmp_path / "a" / "x.bin")
    write(tmp_path / "a-b" / "x.bin")

    assert relatives(scan(tmp_path).files) == ["a-b/x.bin", "a/x.bin"]


@pytest.mark.parametrize("hidden", [True, False])
def test_nothing_found_gives_an_empty_list(tmp_path: Path, hidden: bool) -> None:
    (tmp_path / "empty").mkdir()
    if hidden:
        write(tmp_path / ".keep", b"")

    assert scan(tmp_path) == ScanResult()


def test_a_missing_folder_has_nothing_in_it(tmp_path: Path) -> None:
    assert scan(tmp_path / "no-such-folder") == ScanResult()


needs_permissions = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")


@pytest.fixture
def restore_permissions() -> Iterator[list[Path]]:
    """Paths whose permissions a test took away; restored so that pytest can clean them up."""
    changed: list[Path] = []
    yield changed
    for path in changed:
        path.chmod(0o755)


def test_a_broken_symlink_is_recorded_and_the_scan_carries_on(tmp_path: Path) -> None:
    write(tmp_path / "a-good.bin")
    (tmp_path / "broken.bin").symlink_to(tmp_path / "no-such-target")
    write(tmp_path / "z-good.bin")

    result = scan(tmp_path)

    assert relatives(result.files) == ["a-good.bin", "z-good.bin"]
    assert result.unreadable == (Unreadable(PurePosixPath("broken.bin"), "broken symlink"),)


def test_a_symlink_loop_is_recorded(tmp_path: Path) -> None:
    (tmp_path / "loop.bin").symlink_to(tmp_path / "loop.bin")

    assert scan(tmp_path).unreadable == (Unreadable(PurePosixPath("loop.bin"), "broken symlink"),)


def test_a_symlink_to_a_real_file_is_hashed(tmp_path: Path) -> None:
    target = write(tmp_path / "real" / "file.bin")
    (tmp_path / "link.bin").symlink_to(target)

    result = scan(tmp_path)

    assert relatives(result.files) == ["link.bin", "real/file.bin"]
    assert result.files[0].md5 == result.files[1].md5
    assert result.unreadable == ()


def test_a_named_pipe_is_recorded_without_being_opened(tmp_path: Path) -> None:
    # Opening it would wait forever for a writer, so a failure here shows up as a hang.
    os.mkfifo(tmp_path / "pipe.bin")
    write(tmp_path / "good.bin")

    result = scan(tmp_path)

    assert relatives(result.files) == ["good.bin"]
    assert result.unreadable == (Unreadable(PurePosixPath("pipe.bin"), "not a regular file"),)


def test_a_hidden_broken_symlink_is_ignored_like_other_hidden_files(tmp_path: Path) -> None:
    (tmp_path / ".hidden").symlink_to(tmp_path / "no-such-target")

    assert scan(tmp_path) == ScanResult()


@needs_permissions
def test_a_file_with_no_read_permission_is_recorded(
    tmp_path: Path, restore_permissions: list[Path]
) -> None:
    secret = write(tmp_path / "secret.bin")
    write(tmp_path / "good.bin")
    secret.chmod(0o000)
    restore_permissions.append(secret)

    result = scan(tmp_path)

    assert relatives(result.files) == ["good.bin"]
    assert result.unreadable == (Unreadable(PurePosixPath("secret.bin"), "Permission denied"),)


@needs_permissions
def test_a_folder_with_no_read_permission_is_recorded(
    tmp_path: Path, restore_permissions: list[Path]
) -> None:
    # os.walk would otherwise skip it silently, and every file in it would just go missing.
    write(tmp_path / "locked" / "inside.bin")
    write(tmp_path / "good.bin")
    (tmp_path / "locked").chmod(0o000)
    restore_permissions.append(tmp_path / "locked")

    result = scan(tmp_path)

    assert relatives(result.files) == ["good.bin"]
    assert result.unreadable == (Unreadable(PurePosixPath("locked"), "Permission denied"),)


@needs_permissions
def test_the_scanned_folder_itself_with_no_read_permission_is_recorded(
    tmp_path: Path, restore_permissions: list[Path]
) -> None:
    folder = tmp_path / "bios"
    write(folder / "file.bin")
    folder.chmod(0o000)
    restore_permissions.append(folder)

    assert scan(folder).unreadable == (Unreadable(PurePosixPath("."), "Permission denied"),)


def test_unreadable_items_are_sorted_by_path_as_text(tmp_path: Path) -> None:
    (tmp_path / "z.bin").symlink_to(tmp_path / "gone")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.bin").symlink_to(tmp_path / "gone")
    (tmp_path / "a-b").mkdir()
    (tmp_path / "a-b" / "x.bin").symlink_to(tmp_path / "gone")

    assert [item.relative.as_posix() for item in scan(tmp_path).unreadable] == [
        "a-b/x.bin",
        "a/x.bin",
        "z.bin",
    ]


def test_scanning_prints_nothing_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = write(tmp_path / "ps1" / "file.bin")
    before = file.stat().st_mtime_ns

    scan(tmp_path)

    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert file.stat().st_mtime_ns == before


def test_scan_counts_each_file_as_it_goes(tmp_path: Path) -> None:
    make_bios_file(tmp_path, "a.bin")
    make_bios_file(tmp_path, "sub/b.bin")
    (tmp_path / "broken").symlink_to(tmp_path / "nowhere")
    counts: list[int] = []

    scan(tmp_path, counts.append)

    assert counts == [1, 2, 3]


def test_scan_skips_what_it_does_not_count(tmp_path: Path) -> None:
    make_bios_file(tmp_path, ".hidden")
    counts: list[int] = []

    scan(tmp_path, counts.append)

    assert counts == []
