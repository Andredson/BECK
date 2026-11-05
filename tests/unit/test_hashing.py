"""beck.hashing: ported from the stage 03 tests (D1, D5, D8), without the printed messages."""

import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from beck.hashing import md5_file, scan
from beck.models import LocalFile


def write(path: Path, data: bytes = b"\x00\x01") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def relatives(found: list[LocalFile]) -> list[str]:
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


def test_keep_file_is_ignored(tmp_path: Path) -> None:
    write(tmp_path / ".keep", b"")
    write(tmp_path / "scph5501.bin")

    assert relatives(scan(tmp_path)) == ["scph5501.bin"]


def test_hidden_folders_are_not_entered(tmp_path: Path) -> None:
    write(tmp_path / ".git" / "config.bin")
    write(tmp_path / "ps1" / ".hidden" / "x.bin")
    write(tmp_path / "ps1" / "visible.bin")

    assert relatives(scan(tmp_path)) == ["ps1/visible.bin"]


def test_empty_sub_folder_does_not_stop_the_scan(tmp_path: Path) -> None:
    (tmp_path / "aaa-empty").mkdir()
    write(tmp_path / "zzz" / "late.bin")

    assert relatives(scan(tmp_path)) == ["zzz/late.bin"]


def test_nested_file_has_its_path_hash_and_size(tmp_path: Path) -> None:
    data = os.urandom(64)
    file = write(tmp_path / "a" / "b" / "file.bin", data)

    assert scan(tmp_path) == [
        LocalFile(
            path=file,
            relative=PurePosixPath("a/b/file.bin"),
            md5=hashlib.md5(data, usedforsecurity=False).hexdigest(),
            size=64,
        )
    ]


def test_relative_folder_argument_gives_the_same_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path / "bios" / "ps1" / "file.bin")
    monkeypatch.chdir(tmp_path)

    found = scan(Path("./bios"))

    assert relatives(found) == ["ps1/file.bin"]
    assert found[0].path.read_bytes() == b"\x00\x01"


def test_results_are_sorted_by_path(tmp_path: Path) -> None:
    for name in ("z.bin", "a/m.bin", "b.bin"):
        write(tmp_path / name)

    assert relatives(scan(tmp_path)) == ["a/m.bin", "b.bin", "z.bin"]


def test_paths_sort_as_text_like_stage_03(tmp_path: Path) -> None:
    # As text, "-" sorts before "/". PurePosixPath compares folder by folder, the other way round,
    # and "first by path" decides which file wins a target.
    write(tmp_path / "a" / "x.bin")
    write(tmp_path / "a-b" / "x.bin")

    assert relatives(scan(tmp_path)) == ["a-b/x.bin", "a/x.bin"]


@pytest.mark.parametrize("hidden", [True, False])
def test_nothing_found_gives_an_empty_list(tmp_path: Path, hidden: bool) -> None:
    (tmp_path / "empty").mkdir()
    if hidden:
        write(tmp_path / ".keep", b"")

    assert scan(tmp_path) == []


def test_a_missing_folder_gives_an_empty_list(tmp_path: Path) -> None:
    assert scan(tmp_path / "no-such-folder") == []


def test_scanning_prints_nothing_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = write(tmp_path / "ps1" / "file.bin")
    before = file.stat().st_mtime_ns

    scan(tmp_path)

    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert file.stat().st_mtime_ns == before
