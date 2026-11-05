"""The local scanner skips hidden files, walks sub-folders and doesn't stop early (D1, D8)."""

import hashlib
import os
from pathlib import Path

import pytest

import check_bios
from tests.conftest import use_folder
from tests.fakes import FakeSMBServer, install_fake_smb


def write(path: Path, data: bytes = b"\x00\x01") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def paths(bios: list[dict[str, str]]) -> list[str]:
    return [item["path"] for item in bios]


def test_keep_file_is_ignored(tmp_path: Path) -> None:
    write(tmp_path / ".keep", b"")
    write(tmp_path / "scph5501.bin")

    assert paths(check_bios.get_possible_bios(tmp_path)) == ["scph5501.bin"]


def test_hidden_folders_are_not_entered(tmp_path: Path) -> None:
    write(tmp_path / ".git" / "config.bin")
    write(tmp_path / "ps1" / ".hidden" / "x.bin")
    write(tmp_path / "ps1" / "visible.bin")

    assert paths(check_bios.get_possible_bios(tmp_path)) == ["ps1/visible.bin"]


def test_empty_sub_folder_does_not_stop_the_scan(tmp_path: Path) -> None:
    (tmp_path / "aaa-empty").mkdir()
    write(tmp_path / "zzz" / "late.bin")

    assert paths(check_bios.get_possible_bios(tmp_path)) == ["zzz/late.bin"]


def test_nested_file_has_its_name_path_and_hash(tmp_path: Path) -> None:
    data = os.urandom(64)
    write(tmp_path / "a" / "b" / "file.bin", data)

    assert check_bios.get_possible_bios(tmp_path) == [
        {
            "name": "file.bin",
            "path": "a/b/file.bin",
            "hash": hashlib.md5(data, usedforsecurity=False).hexdigest(),
        }
    ]


def test_relative_folder_argument_gives_the_same_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path / "bios" / "ps1" / "file.bin")
    monkeypatch.chdir(tmp_path)

    assert paths(check_bios.get_possible_bios(Path("./bios"))) == ["ps1/file.bin"]


def test_results_are_sorted_by_path(tmp_path: Path) -> None:
    for name in ("z.bin", "a/m.bin", "b.bin"):
        write(tmp_path / name)

    assert paths(check_bios.get_possible_bios(tmp_path)) == ["a/m.bin", "b.bin", "z.bin"]


def test_prints_one_total(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name in ("a.bin", "sub/b.bin", "sub/deeper/c.bin"):
        write(tmp_path / name)

    check_bios.get_possible_bios(tmp_path)

    output = capsys.readouterr().out
    assert output.count("possible bios") == 1
    assert "3" in output


@pytest.mark.parametrize("hidden", [True, False])
def test_says_so_only_when_nothing_was_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], hidden: bool
) -> None:
    (tmp_path / "empty").mkdir()
    if hidden:
        write(tmp_path / ".keep", b"")

    assert check_bios.get_possible_bios(tmp_path) == []
    assert "No BIOS files found" in capsys.readouterr().out


@pytest.fixture
def run_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeSMBServer:
    server = install_fake_smb(monkeypatch)
    write(
        tmp_path / "config" / "config.yml",
        b'smb: {user: "", passwd: "", server: "beck-test-server", port: 445}\n',
    )
    write(tmp_path / "bios" / ".keep", b"")
    monkeypatch.chdir(tmp_path)
    use_folder(monkeypatch, tmp_path)
    return server


def report_for(data: bytes) -> bytes:
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest().upper()
    return (
        "  MISSING REQUIRED BIOS: scph5501.bin\n"
        "    Path: /recalbox/share/bios/scph5501.bin\n"
        f"    Possible MD5 List:\n      {md5}\n"
    ).encode()


def test_full_run_uploads_a_matching_file_from_a_sub_folder(
    run_setup: FakeSMBServer, tmp_path: Path
) -> None:
    data = os.urandom(64)
    run_setup.files[("bios", "missing_bios_report.txt")] = report_for(data)
    write(tmp_path / "bios" / "ps1" / "my-copy.bin", data)

    check_bios.main()

    assert run_setup.files[("bios", "scph5501.bin")] == data


def test_full_run_with_the_right_name_in_a_sub_folder(
    run_setup: FakeSMBServer, tmp_path: Path
) -> None:
    data = os.urandom(64)
    run_setup.files[("bios", "missing_bios_report.txt")] = report_for(data)
    write(tmp_path / "bios" / "ps1" / "scph5501.bin", data)

    check_bios.main()

    assert run_setup.files[("bios", "scph5501.bin")] == data


def test_full_run_never_touches_the_keep_file(run_setup: FakeSMBServer, tmp_path: Path) -> None:
    data = os.urandom(64)
    run_setup.files[("bios", "missing_bios_report.txt")] = report_for(data)
    write(tmp_path / "bios" / "unrelated.bin", b"no match")

    check_bios.main()

    assert (tmp_path / "bios" / ".keep").exists()


def test_full_run_with_nothing_to_analyse_stops_cleanly(
    run_setup: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    run_setup.files[("bios", "missing_bios_report.txt")] = report_for(b"anything")

    check_bios.main()

    output = capsys.readouterr().out
    assert "No BIOS files found" in output
    assert "Final result" not in output
    assert run_setup.connections[0].closed
