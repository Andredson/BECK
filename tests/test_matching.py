"""validate_bios: one file can fill many targets, and local files are never renamed (D3)."""

import hashlib
import os
from pathlib import Path
from typing import Any, NoReturn

import pytest

import check_bios
from tests.conftest import REAL_REPORT, load_report, use_folder
from tests.fakes import FakeSMBServer, install_fake_smb


def md5_of(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def entry(name: str, *hashes: str, folder: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "path": f"/recalbox/share/bios/{folder}",
        "relativePath": folder,
        "hashes": list(hashes),
    }


@pytest.fixture
def bios_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "bios"
    folder.mkdir()
    monkeypatch.chdir(tmp_path)
    use_folder(monkeypatch, tmp_path)
    return folder


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeSMBServer:
    return install_fake_smb(monkeypatch)


def run(bios_dir: Path, report: list[dict[str, Any]]) -> int:
    bios = check_bios.get_possible_bios(bios_dir)
    with check_bios.SmbSession("beck-test-server", 445, "", "", "bios") as session:
        return check_bios.validate_bios(bios, report, session)


def test_one_file_two_entries_gives_two_uploads(server: FakeSMBServer, bios_dir: Path) -> None:
    data = os.urandom(64)
    (bios_dir / "my-copy.bin").write_bytes(data)
    md5 = md5_of(data)

    count = run(bios_dir, [entry("a.bin", md5), entry("b.bin", md5, folder="ps1/")])

    assert count == 2
    assert server.files[("bios", "a.bin")] == data
    assert server.files[("bios", "ps1/b.bin")] == data


def test_two_identical_local_files_give_one_upload_and_a_notice(
    server: FakeSMBServer, bios_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = os.urandom(64)
    (bios_dir / "b-second.bin").write_bytes(data)
    (bios_dir / "a-first.bin").write_bytes(data)

    count = run(bios_dir, [entry("target.bin", md5_of(data))])

    assert count == 1
    stored = server.connections[0].stored_files
    assert [Path(str(f.name)).name for f in stored] == ["a-first.bin"]
    output = capsys.readouterr().out
    assert "b-second.bin: duplicate of a-first.bin, kept" in output
    assert (bios_dir / "b-second.bin").exists()


def test_local_files_are_never_renamed(
    server: FakeSMBServer, bios_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise AssertionError("a local file was renamed")

    monkeypatch.setattr(os, "rename", forbidden)
    monkeypatch.setattr(os, "replace", forbidden)
    monkeypatch.setattr(Path, "rename", forbidden)
    monkeypatch.setattr(Path, "replace", forbidden)
    data = os.urandom(64)
    (bios_dir / "ps1").mkdir()
    (bios_dir / "ps1" / "my-copy.bin").write_bytes(data)

    run(bios_dir, [entry("scph5501.bin", md5_of(data))])

    # Uploaded from its own path, under the target's name.
    assert str(server.connections[0].stored_files[0].name).endswith("ps1/my-copy.bin")
    assert server.files[("bios", "scph5501.bin")] == data


def test_same_target_in_several_entries_uploads_once(server: FakeSMBServer, bios_dir: Path) -> None:
    data = os.urandom(64)
    (bios_dir / "game.pce").write_bytes(data)
    md5 = md5_of(data)
    report = [entry("gexpress.pce", md5, folder="pcengine/") for _ in range(3)]

    count = run(bios_dir, report)

    assert count == 1
    assert len(server.connections[0].stored_files) == 1
    assert check_bios.count_targets(report) == 1


def test_second_different_file_does_not_overwrite_a_filled_target(
    server: FakeSMBServer, bios_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = os.urandom(64), os.urandom(64)
    (bios_dir / "a.img").write_bytes(first)
    (bios_dir / "b.img").write_bytes(second)

    count = run(bios_dir, [entry("tos.img", md5_of(first), md5_of(second), folder="atarist/")])

    assert count == 1
    assert server.files[("bios", "atarist/tos.img")] == first
    assert "b.img: target already filled, kept" in capsys.readouterr().out
    assert (bios_dir / "b.img").exists()


def test_file_named_like_the_target_beats_an_earlier_file(
    server: FakeSMBServer, bios_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # On the real report, falcon.img sorted first and took the place of the user's real tos.img.
    other, real = os.urandom(64), os.urandom(64)
    (bios_dir / "falcon.img").write_bytes(other)
    (bios_dir / "tos.img").write_bytes(real)

    count = run(bios_dir, [entry("tos.img", md5_of(other), md5_of(real), folder="atarist/")])

    assert count == 1
    assert server.files[("bios", "atarist/tos.img")] == real
    assert len(server.connections[0].stored_files) == 1
    output = capsys.readouterr().out
    assert "falcon.img: target already filled, kept" in output
    assert "tos.img: copied -> atarist/tos.img" in output


def test_identical_copy_named_like_the_target_is_the_one_uploaded(
    server: FakeSMBServer, bios_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = os.urandom(64)
    (bios_dir / "a-copy.img").write_bytes(data)
    (bios_dir / "tos.img").write_bytes(data)

    run(bios_dir, [entry("tos.img", md5_of(data))])

    stored = server.connections[0].stored_files
    assert [Path(str(f.name)).name for f in stored] == ["tos.img"]
    assert "a-copy.img: duplicate of tos.img, kept" in capsys.readouterr().out


def test_a_file_does_not_take_a_target_from_the_file_named_like_it(
    server: FakeSMBServer, bios_dir: Path
) -> None:
    # a.img also fits target b.img, and comes first, but the local b.img must fill that target.
    first, second = os.urandom(64), os.urandom(64)
    (bios_dir / "a.img").write_bytes(first)
    (bios_dir / "b.img").write_bytes(second)
    report = [entry("a.img", md5_of(first)), entry("b.img", md5_of(first), md5_of(second))]

    count = run(bios_dir, report)

    assert count == 2
    assert server.files[("bios", "a.img")] == first
    assert server.files[("bios", "b.img")] == second


def test_file_named_like_a_target_still_fills_its_other_targets(
    server: FakeSMBServer, bios_dir: Path
) -> None:
    data = os.urandom(64)
    (bios_dir / "tos.img").write_bytes(data)
    md5 = md5_of(data)

    count = run(bios_dir, [entry("st.img", md5), entry("tos.img", md5)])

    assert count == 2
    assert server.files[("bios", "st.img")] == data
    assert server.files[("bios", "tos.img")] == data


def test_the_name_only_counts_when_the_md5_fits_that_target(
    server: FakeSMBServer, bios_dir: Path
) -> None:
    # A local tos.img whose MD5 isn't on the tos.img entry gets no priority for that target.
    fits, named = os.urandom(64), os.urandom(64)
    (bios_dir / "falcon.img").write_bytes(fits)
    (bios_dir / "tos.img").write_bytes(named)
    report = [entry("tos.img", md5_of(fits)), entry("st.img", md5_of(named))]

    count = run(bios_dir, report)

    assert count == 2
    assert server.files[("bios", "tos.img")] == fits
    assert server.files[("bios", "st.img")] == named


def test_one_file_reaches_all_its_targets(server: FakeSMBServer, bios_dir: Path) -> None:
    # The old code deleted the file after the first upload, so the next one failed (D3).
    data = os.urandom(64)
    (bios_dir / "copy.bin").write_bytes(data)
    md5 = md5_of(data)

    run(bios_dir, [entry("a.bin", md5), entry("b.bin", md5), entry("c.bin", md5)])

    assert {("bios", "a.bin"), ("bios", "b.bin"), ("bios", "c.bin")} <= set(server.files)
    assert (bios_dir / "copy.bin").read_bytes() == data


def test_folder_is_created_only_once_for_two_targets(server: FakeSMBServer, bios_dir: Path) -> None:
    data = os.urandom(64)
    (bios_dir / "copy.bin").write_bytes(data)
    md5 = md5_of(data)

    run(bios_dir, [entry("a.bin", md5, folder="ps1/"), entry("b.bin", md5, folder="ps1/")])

    assert server.connections[0].calls.count("createDirectory") == 1


def test_real_report_shared_md5_and_repeated_target(server: FakeSMBServer, bios_dir: Path) -> None:
    # Hashes come from the real report; the file content is random bytes, not a BIOS.
    local = bios_dir / "copy.bin"
    local.write_bytes(os.urandom(64))
    report = check_bios.parse_report(load_report(REAL_REPORT))
    shared = {"name": "copy.bin", "path": "copy.bin", "hash": "c87a52c277f7952b41c639fc7bf0a43b"}
    repeated = {"name": "copy.bin", "path": "copy.bin", "hash": "6d2cb14fc3e1f65ceb135633d1694122"}

    with check_bios.SmbSession("beck-test-server", 445, "", "", "bios") as session:
        assert check_bios.validate_bios([shared], report, session) == 2
        assert {("bios", "atarist/tos.img"), ("bios", "atarist/st.img")} <= set(server.files)

        assert check_bios.validate_bios([repeated], report, session) == 1
        assert ("bios", "pcengine/gexpress.pce") in server.files


def test_summary_counts_entries_and_files(
    server: FakeSMBServer,
    bios_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = os.urandom(64)
    (bios_dir / "copy.bin").write_bytes(data)
    md5 = md5_of(data).upper()
    server.files[("bios", "missing_bios_report.txt")] = (
        "".join(
            f"  MISSING REQUIRED BIOS: {name}\n"
            f"    Path: /recalbox/share/bios/{name}\n"
            f"    Possible MD5 List:\n      {md5}\n\n"
            for name in ("a.bin", "b.bin")
        )
        + "  MISSING REQUIRED BIOS: c.bin\n    Path: /recalbox/share/bios/c.bin\n"
        + f"    Possible MD5 List:\n      {'0' * 32}\n"
    ).encode()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yml").write_text(
        'smb: {user: "", passwd: "", server: "beck-test-server", port: 445}\n', encoding="utf-8"
    )

    check_bios.main()

    output = capsys.readouterr().out
    assert "\033[92m2\033[0m/\033[94m3\033[0m missing entries satisfied, 1 files analysed" in output
