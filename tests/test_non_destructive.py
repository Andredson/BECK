"""A full run never deletes, renames or changes a local file (DEC-02)."""

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, NoReturn

import pytest

import check_bios
from tests.conftest import use_folder
from tests.fakes import FakeSMBServer, install_fake_smb

Snapshot = dict[str, tuple[int, int, bytes]]


def md5_of(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest().upper()


def block(name: str, *hashes: str) -> str:
    md5s = "".join(f"      {md5}\n" for md5 in hashes)
    return (
        f"  MISSING REQUIRED BIOS: {name}\n"
        f"    Path: /recalbox/share/bios/ps1/{name}\n"
        f"    Possible MD5 List:\n{md5s}\n"
    )


def snapshot(folder: Path) -> Snapshot:
    return {
        path.relative_to(folder).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("a local file was deleted or renamed")


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeSMBServer:
    fake = install_fake_smb(monkeypatch)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yml").write_text(
        'smb: {user: "", passwd: "", server: "beck-test-server", port: 445}\n', encoding="utf-8"
    )
    (tmp_path / "bios").mkdir()
    monkeypatch.chdir(tmp_path)
    use_folder(monkeypatch, tmp_path)
    return fake


def fill_bios_folder(server: FakeSMBServer, bios: Path) -> dict[str, bytes]:
    files = {
        ".keep": b"",
        "a-match.bin": os.urandom(64),
        "b-copy-of-match.bin": b"",
        "c-first-for-target.bin": os.urandom(64),
        "d-second-for-target.bin": os.urandom(64),
        "e-no-match.bin": os.urandom(64),
        "ps1/nested-match.bin": os.urandom(64),
    }
    files["b-copy-of-match.bin"] = files["a-match.bin"]
    for name, data in files.items():
        (bios / name).parent.mkdir(parents=True, exist_ok=True)
        (bios / name).write_bytes(data)
    server.files[("bios", "missing_bios_report.txt")] = (
        block("match.bin", md5_of(files["a-match.bin"]))
        + block(
            "filled.bin",
            md5_of(files["c-first-for-target.bin"]),
            md5_of(files["d-second-for-target.bin"]),
        )
        + block("nested.bin", md5_of(files["ps1/nested-match.bin"]))
    ).encode()
    return files


def test_full_run_leaves_the_bios_folder_exactly_as_it_was(
    server: FakeSMBServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bios = tmp_path / "bios"
    files = fill_bios_folder(server, bios)
    before = snapshot(bios)

    with monkeypatch.context() as blocked:
        for module, names in (
            (os, ("remove", "unlink", "rename", "replace", "rmdir")),
            (Path, ("unlink", "rename", "replace", "rmdir")),
            (shutil, ("rmtree", "move")),
        ):
            for name in names:
                blocked.setattr(module, name, forbidden)
        check_bios.main()

    assert snapshot(bios) == before
    assert server.files[("bios", "ps1/match.bin")] == files["a-match.bin"]
    assert server.files[("bios", "ps1/filled.bin")] == files["c-first-for-target.bin"]
    assert server.files[("bios", "ps1/nested.bin")] == files["ps1/nested-match.bin"]


def test_run_lists_what_happened_to_each_file(
    server: FakeSMBServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_bios_folder(server, tmp_path / "bios")

    check_bios.main()

    output = capsys.readouterr().out
    for line in (
        "a-match.bin: copied -> ps1/match.bin",
        "b-copy-of-match.bin: duplicate of a-match.bin, kept",
        "c-first-for-target.bin: copied -> ps1/filled.bin",
        "d-second-for-target.bin: target already filled, kept",
        "e-no-match.bin: no match, kept",
        "ps1/nested-match.bin: copied -> ps1/nested.bin",
    ):
        assert line in output
    assert ".keep" not in output


def test_failed_upload_leaves_the_bios_folder_as_it_was(
    server: FakeSMBServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bios = tmp_path / "bios"
    fill_bios_folder(server, bios)
    before = snapshot(bios)
    server.failures["storeFile"] = OSError("disk full")

    with pytest.raises(SystemExit) as exit_info:
        check_bios.main()

    assert exit_info.value.code == 1
    assert snapshot(bios) == before
    assert "disk full" in capsys.readouterr().out
