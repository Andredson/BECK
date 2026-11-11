# SPDX-License-Identifier: GPL-3.0-only
"""``beck export``, through ``cli.main``: output, exit codes and warnings (step 11.12)."""

import json
from pathlib import Path

import pytest

from beck import cli
from tests.factories import make_bios_file, settings_text, snapshot
from tests.fakes import install_fake_smb

HOSTILE = "evil\x1b[2J\x07‮gnp"
HOSTILE_SHOWN = "evil\\x1b[2J\\x07\\u202egnp"


@pytest.fixture
def device(tmp_path: Path) -> Path:
    folder = tmp_path / "device"
    folder.mkdir()
    return folder


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "out"


def export(out: Path, device: Path, *flags: str) -> list[str]:
    return ["export", str(out), "--target-dir", str(device), *flags]


def test_an_export_prints_each_file_and_what_it_left_out(
    device: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(device, "ps1/scph1001.bin")
    make_bios_file(device, "atari800/ATARIBAS.ROM")
    make_bios_file(device, "neogeo.zip")
    make_bios_file(device, "a.png")
    before = snapshot(device)

    assert cli.main(export(out, device)) == 0

    assert capsys.readouterr().out.splitlines() == [
        "atari800/ATARIBAS.ROM: copied",
        "ps1/scph1001.bin: copied",
        f"Copied 2 of 2 .rom and .bin files to {out}.",
        "Left out 2 other files on the device, which aren't .rom or .bin. This isn't a complete "
        "backup of its BIOS files: see docs/cli.md.",
    ]
    assert (out / "atari800" / "ATARIBAS.ROM").read_bytes() == (
        device / "atari800" / "ATARIBAS.ROM"
    ).read_bytes()
    assert snapshot(device) == before


def test_a_dry_run_says_what_it_would_copy_and_writes_nothing(
    device: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(device, "a.bin")

    assert cli.main(export(out, device, "--dry-run")) == 0

    assert capsys.readouterr().out.splitlines() == [
        "a.bin: would copy",
        f"Dry run: would copy 1 of 1 .rom and .bin files to {out}.",
    ]
    assert not out.exists()


def test_files_already_here_are_kept_and_counted(
    device: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(device, "a.bin")
    make_bios_file(out, "a.bin", b"mine")

    assert cli.main(export(out, device)) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"a.bin: already in {out}, kept",
        f"Copied 0 of 1 .rom and .bin files to {out}.",
        f"1 were already in {out}, and were kept: export never replaces a file.",
    ]
    assert (out / "a.bin").read_bytes() == b"mine"


def test_a_failed_file_exits_with_3_and_the_rest_are_copied(
    device: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(device, "ps1/a.bin")
    make_bios_file(device, "b.bin")
    make_bios_file(out, "ps1", b"a file, not a folder")

    assert cli.main(export(out, device)) == 3

    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ["b.bin: copied", "ps1/a.bin: failed"]
    assert lines[2].startswith(f"Error: Couldn't create the folder {out / 'ps1'}: ")
    assert lines[3] == f"Copied 1 of 2 .rom and .bin files to {out}, and 1 failed."


def test_a_device_with_no_rom_or_bin_files_says_so(
    device: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(device, "neogeo.zip")

    assert cli.main(export(out, device)) == 0

    assert capsys.readouterr().out.splitlines()[0] == (
        "No .rom or .bin files were found on the device."
    )


def test_a_destination_that_is_a_file_is_a_usage_error_and_nothing_connects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(tmp_path, "out")

    assert cli.main(["export", str(tmp_path / "out"), "--target-dir", str(tmp_path / "nope")]) == 2

    assert capsys.readouterr().out == f"Error: {tmp_path / 'out'} isn't a folder\n"


def test_export_needs_a_folder() -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["export"])

    assert stopped.value.code == 2


def test_a_destination_inside_a_git_repository_gets_a_warning_and_still_exports(
    device: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(device, "a.bin")
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    out = tmp_path / "repo" / "backup"

    assert cli.main(["--json", *export(out, device)]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["summary"]["copied"] == 1
    assert f"{out} is inside the git repository in {tmp_path / 'repo'}" in captured.err
    assert "never commit them" in captured.err


def test_no_warning_outside_a_git_repository(
    device: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(device, "a.bin")

    assert cli.main(export(out, device)) == 0

    assert "git" not in capsys.readouterr().err


def test_names_from_the_device_are_escaped(
    device: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(device, f"{HOSTILE}.bin")

    assert cli.main(export(out, device)) == 0

    assert f"{HOSTILE_SHOWN}.bin: copied" in capsys.readouterr().out
    assert (out / f"{HOSTILE}.bin").exists()


def test_an_export_over_smb_reads_and_never_writes_the_share(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = install_fake_smb(monkeypatch)
    server.dirs.add(("bios", "ps1"))
    server.files[("bios", "ps1/scph1001.bin")] = b"beck-test-bytes"
    server.files[("bios", "readme.txt")] = b"text"
    settings = tmp_path / "settings.toml"
    settings.write_text(settings_text("smb://beck-test-server/bios"), encoding="utf-8")
    settings.chmod(0o600)
    monkeypatch.setenv("BECK_CONFIG", str(settings))
    files_before = dict(server.files)

    assert cli.main(["--json", "export", str(tmp_path / "out")]) == 0

    document = json.loads(capsys.readouterr().out)
    assert document["target"] == "smb://beck-test-server:445/bios"
    assert [(f["path"], f["status"]) for f in document["files"]] == [("ps1/scph1001.bin", "copied")]
    assert (tmp_path / "out" / "ps1" / "scph1001.bin").read_bytes() == b"beck-test-bytes"
    assert server.files == files_before
    calls = {call for connection in server.connections for call in connection.calls}
    assert not {"storeFile", "createDirectory", "deleteFiles", "rename"} & calls
