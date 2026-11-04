"""MD5 values are compared in lowercase and files are hashed in chunks (D5)."""

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import check_bios
from tests.fakes import install_fake_smb

BLOCK = """\
  MISSING REQUIRED BIOS: scph5501.bin
    Path: /recalbox/share/bios/scph5501.bin
    For: libretro/pcsx_rearmed
    Possible MD5 List:
      {md5}
"""


def test_file_md5_is_lowercase_and_correct(tmp_path: Path) -> None:
    file = tmp_path / "bios.bin"
    data = os.urandom(1024)
    file.write_bytes(data)

    digest = check_bios.file_md5(str(file))

    assert digest == hashlib.md5(data, usedforsecurity=False).hexdigest()
    assert digest == digest.lower()


def test_file_md5_of_a_file_larger_than_one_chunk(tmp_path: Path) -> None:
    file = tmp_path / "big.bin"
    data = os.urandom(3 * 1024 * 1024)
    file.write_bytes(data)

    assert check_bios.file_md5(str(file)) == hashlib.md5(data, usedforsecurity=False).hexdigest()


def test_file_md5_uses_the_chunked_file_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "bios.bin"
    file.write_bytes(os.urandom(1024))
    calls = []
    real = hashlib.file_digest

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(hashlib, "file_digest", spy)

    check_bios.file_md5(str(file))

    assert len(calls) == 1


def test_parser_lowercases_and_removes_repeats_across_case() -> None:
    upper = "490F666E1AFB15B7362B406ED1CEA246"
    text = BLOCK.format(md5=f"{upper}\n      {upper.lower()}")

    assert check_bios.parse_report(text)[0]["hashes"] == [upper.lower()]


@pytest.mark.parametrize("case", [str.upper, str.lower, str.title])
def test_full_run_matches_whatever_the_case_in_the_report(
    case: Callable[[str], str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = install_fake_smb(monkeypatch)
    data = os.urandom(1024)
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    server.files[("bios", "missing_bios_report.txt")] = BLOCK.format(md5=case(md5)).encode()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yml").write_text(
        'smb: {user: "", passwd: "", server: "beck-test-server", port: 445}\n', encoding="utf-8"
    )
    (tmp_path / "bios").mkdir()
    (tmp_path / "bios" / "my-copy.bin").write_bytes(data)
    monkeypatch.chdir(tmp_path)
    # Until step 03.11, validate_bios looks for the bios folder next to the script.
    monkeypatch.setattr(check_bios, "__file__", str(tmp_path / "check_bios.py"))

    check_bios.main()

    assert server.files[("bios", "scph5501.bin")] == data
