# SPDX-License-Identifier: GPL-3.0-only
"""``beck export`` against the Samba test server (step 11.12). Every file is random bytes."""

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from beck import cli
from tests.integration.conftest import Samba

pytestmark = pytest.mark.integration

FILES = {
    "ps1/scph1001.bin": os.urandom(512),
    "atari800/ATARIBAS.ROM": os.urandom(256),
    "Machines/MSX - C-BIOS/cbios_main_msx1.Rom": os.urandom(128),
    "top.bin": os.urandom(64),
    "neogeo.zip": os.urandom(64),
    "ps1/readme.txt": b"not a BIOS file",
}
EXPORTED = sorted(name for name in FILES if name.lower().endswith((".rom", ".bin")))


def put(samba: Samba, folder: PurePosixPath, files: dict[str, bytes], tmp_path: Path) -> None:
    """Put each file under ``folder`` on the bios share."""
    local = tmp_path / "to-upload"
    with samba.guest() as transport:
        for relative, data in files.items():
            remote = folder / relative
            transport.makedirs(remote.parent)
            local.write_bytes(data)
            transport.upload(local, remote)


def on_share(samba: Samba, folder: PurePosixPath) -> dict[str, bytes]:
    """Every file under ``folder``, with its content: to check that export changed nothing."""
    with samba.guest() as transport:
        return {
            file.path.as_posix(): transport.read_bytes(file.path)
            for file in transport.list_files()
            if file.path.is_relative_to(folder)
        }


def files_in(local: Path) -> dict[str, bytes]:
    return {
        path.relative_to(local).as_posix(): path.read_bytes()
        for path in local.rglob("*")
        if path.is_file()
    }


def export(
    samba: Samba,
    folder: PurePosixPath,
    out: Path,
    capsys: pytest.CaptureFixture[str],
    *flags: str,
) -> tuple[int, Any]:
    url = f"smb://{samba.host}:{samba.port}/bios/{folder}"
    exit_code = cli.main(["--json", "export", str(out), "--target", url, *flags])
    return exit_code, json.loads(capsys.readouterr().out)


def statuses(document: Any) -> dict[str, str]:
    return {item["path"]: item["status"] for item in document["files"]}


def test_a_full_export_copies_the_rom_and_bin_files_and_changes_nothing(
    samba: Samba, folder: PurePosixPath, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    put(samba, folder, FILES, tmp_path)
    before = on_share(samba, folder)

    exit_code, document = export(samba, folder, tmp_path / "out", capsys)

    assert exit_code == 0
    assert statuses(document) == dict.fromkeys(EXPORTED, "copied")
    assert document["summary"]["left_out"] == 2
    assert files_in(tmp_path / "out") == {name: FILES[name] for name in EXPORTED}
    assert on_share(samba, folder) == before


def test_a_large_file_comes_whole(
    samba: Samba, folder: PurePosixPath, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = os.urandom(8 * 1024 * 1024)
    put(samba, folder, {"big.bin": data}, tmp_path)

    exit_code, _document = export(samba, folder, tmp_path / "out", capsys)

    assert exit_code == 0
    assert (tmp_path / "out" / "big.bin").read_bytes() == data


def test_a_dry_run_writes_nothing(
    samba: Samba, folder: PurePosixPath, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    put(samba, folder, FILES, tmp_path)
    before = on_share(samba, folder)

    exit_code, document = export(samba, folder, tmp_path / "out", capsys, "--dry-run")

    assert exit_code == 0
    assert statuses(document) == dict.fromkeys(EXPORTED, "planned")
    assert not (tmp_path / "out").exists()
    assert on_share(samba, folder) == before


def test_a_file_already_here_is_kept(
    samba: Samba, folder: PurePosixPath, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    put(samba, folder, {"a.bin": os.urandom(64), "b.bin": os.urandom(64)}, tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.bin").write_bytes(b"mine")

    exit_code, document = export(samba, folder, out, capsys)

    assert exit_code == 0
    assert statuses(document) == {"a.bin": "exists", "b.bin": "copied"}
    assert (out / "a.bin").read_bytes() == b"mine"


def test_a_failed_file_is_recorded_and_the_rest_are_copied(
    samba: Samba, folder: PurePosixPath, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    put(samba, folder, {"ps1/a.bin": os.urandom(64), "b.bin": os.urandom(64)}, tmp_path)
    before = on_share(samba, folder)
    out = tmp_path / "out"
    out.mkdir()
    (out / "ps1").write_bytes(b"a file where a folder must go")

    exit_code, document = export(samba, folder, out, capsys)

    assert exit_code == 3
    assert statuses(document) == {"b.bin": "copied", "ps1/a.bin": "failed"}
    assert [error["code"] for error in document["errors"]] == ["write_failed"]
    assert on_share(samba, folder) == before
