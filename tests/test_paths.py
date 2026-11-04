"""The config and bios folders are found from the script, not the working directory (D9)."""

import hashlib
import os
import runpy
from pathlib import Path

import pytest

import check_bios
from tests.conftest import use_folder
from tests.fakes import install_fake_smb


def test_paths_come_from_the_script_when_loaded_from_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Path(check_bios.__file__).resolve()
    monkeypatch.chdir(tmp_path)

    # Loaded fresh, because the constants are computed when the module loads.
    module = runpy.run_path(str(script))

    assert module["BASE_DIR"] == script.parent
    assert module["CONFIG_PATH"] == script.parent / "config" / "config.yml"
    assert module["BIOS_DIR"] == script.parent / "bios"
    assert module["BASE_DIR"].is_absolute()


def test_full_run_works_from_an_unrelated_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "app"
    elsewhere = tmp_path / "elsewhere"
    (app / "config").mkdir(parents=True)
    (app / "bios" / "ps1").mkdir(parents=True)
    elsewhere.mkdir()
    (app / "config" / "config.yml").write_text(
        'smb: {user: "", passwd: "", server: "beck-test-server", port: 445}\n', encoding="utf-8"
    )
    data = os.urandom(64)
    (app / "bios" / "ps1" / "my-copy.bin").write_bytes(data)
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    server = install_fake_smb(monkeypatch)
    server.files[("bios", "missing_bios_report.txt")] = (
        "  MISSING REQUIRED BIOS: scph5501.bin\n"
        "    Path: /recalbox/share/bios/scph5501.bin\n"
        f"    Possible MD5 List:\n      {md5}\n"
    ).encode()
    use_folder(monkeypatch, app)
    monkeypatch.chdir(elsewhere)

    check_bios.main()

    assert server.files[("bios", "scph5501.bin")] == data
    assert list(elsewhere.iterdir()) == []
