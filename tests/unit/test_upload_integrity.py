"""What arrived is what was sent: the size always, and with --verify the MD5 too (07.7)."""

import json
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

import pytest

from beck import cli
from beck.errors import TransportError
from beck.executor import execute
from beck.matcher import plan
from beck.models import LocalFile
from beck.output import upload_status
from beck.transports.local import LocalTransport
from tests.factories import make_bios_file, make_missing, make_report_text, md5_of
from tests.fakes import FakeSMBConnection, install_fake_smb


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    source, device = tmp_path / "source", tmp_path / "device"
    source.mkdir()
    device.mkdir()
    return source, device


def put_report(device: Path, *entries: Any) -> None:
    (device / "missing_bios_report.txt").write_text(
        make_report_text(entries), encoding="utf-8", newline=""
    )


def check(folders: tuple[Path, Path], *flags: str) -> list[str]:
    return ["check", "--source", str(folders[0]), "--target-dir", str(folders[1]), *flags]


def wrong_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LocalTransport, "size", lambda _self, _path: 1)


def arrives_damaged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The upload writes other bytes of the same size, so that only the MD5 can tell."""

    def upload(self: LocalTransport, local: Path, remote: PurePosixPath) -> int:
        data = local.read_bytes()
        (self.root / remote).write_bytes(bytes(reversed(data)))
        return len(data)

    monkeypatch.setattr(LocalTransport, "upload", upload)


def must_not_read(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("this must not read the file back")


def run(folder: Path, file: LocalFile, **options: Any) -> Any:
    built = plan([make_missing("a.bin", file.md5)], [file])
    with LocalTransport(folder) as transport:
        return execute(built, transport, dry_run=False, **options), built.uploads[0]


# The size, on every upload


def test_integrity_a_good_upload_is_completed(folders: tuple[Path, Path]) -> None:
    source, device = folders

    result, upload = run(device, make_bios_file(source, "a.bin"))

    assert result.completed == (upload,)
    assert result.errors == ()


def test_integrity_a_wrong_size_is_not_an_upload_that_worked(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    wrong_size(monkeypatch)

    result, upload = run(device, make_bios_file(source, "a.bin"))

    assert result.completed == ()
    assert upload_status(upload, result) == "failed"
    assert [(e.code, e.item) for e in result.errors] == [("size_mismatch", "a.bin")]
    assert "1 bytes" in result.errors[0].message
    assert "--overwrite" in result.errors[0].message, "the damaged file would otherwise be kept"


def test_integrity_a_size_it_can_not_get_is_a_failed_item(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders

    def no_size(*_args: Any) -> NoReturn:
        raise TransportError("the network went away")

    monkeypatch.setattr(LocalTransport, "size", no_size)

    result, upload = run(device, make_bios_file(source, "a.bin"))

    assert result.completed == ()
    assert upload_status(upload, result) == "failed"
    assert result.errors[0].message == "the network went away"


def test_integrity_a_file_that_changed_after_the_scan_is_noticed(
    folders: tuple[Path, Path],
) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    file.path.write_bytes(b"longer than it was when it was scanned" * 10)

    result, _upload = run(device, file)

    assert result.completed == ()
    assert result.errors[0].code == "size_mismatch"


def test_integrity_the_others_carry_on(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    bad, good = make_bios_file(source, "bad.bin"), make_bios_file(source, "good.bin")
    put_report(device, make_missing("bad.bin", bad.md5), make_missing("good.bin", good.md5))
    real_size = LocalTransport.size

    def size(self: LocalTransport, path: PurePosixPath) -> int:
        return 1 if path.name == "bad.bin" else real_size(self, path)

    monkeypatch.setattr(LocalTransport, "size", size)

    assert cli.main(check(folders)) == 3

    assert (device / "good.bin").exists()


def test_integrity_a_wrong_size_on_a_replaced_file_does_not_say_replaced(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    make_bios_file(device, "a.bin")
    wrong_size(monkeypatch)

    result, upload = run(device, file, overwrite=True)

    assert upload not in result.replaced
    assert upload_status(upload, result) == "failed"


def test_integrity_a_kept_file_is_not_checked(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    make_bios_file(device, "a.bin")
    monkeypatch.setattr(LocalTransport, "size", must_not_read)
    monkeypatch.setattr(LocalTransport, "read_bytes", must_not_read)

    result, upload = run(device, make_bios_file(source, "a.bin"), verify=True)

    assert result.kept == (upload,)
    assert result.errors == ()


def test_integrity_a_dry_run_checks_nothing(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    built = plan([make_missing("a.bin", file.md5)], [file])

    def no_size(*_args: Any) -> NoReturn:
        raise AssertionError("a dry run uploads nothing, so there's nothing to check")

    monkeypatch.setattr(LocalTransport, "size", no_size)
    monkeypatch.setattr(LocalTransport, "read_bytes", must_not_read)

    with LocalTransport(device) as transport:
        result = execute(built, transport, dry_run=True, verify=True)

    assert result.errors == ()


def test_integrity_through_the_command_it_is_exit_3_and_no_scan_message(
    folders: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    wrong_size(monkeypatch)

    assert cli.main(check(folders)) == 3

    output = capsys.readouterr().out
    assert "a.bin: failed -> a.bin" in output
    assert "FOUND" not in output
    assert "PLEASE SCAN" not in output
    assert "Final result: 0/1" in output


def test_integrity_in_json_it_is_failed_and_not_satisfied(
    folders: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """DEC-64."""
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    wrong_size(monkeypatch)

    assert cli.main(["--json", *check(folders)]) == 3

    document = json.loads(capsys.readouterr().out)
    assert document["uploads"][0]["status"] == "failed"
    assert document["uploads"][0]["error"] == document["errors"][0]["message"]
    assert document["errors"][0]["code"] == "size_mismatch"
    assert document["summary"]["satisfied"] == 0
    assert document["summary"]["uploaded"] == 0


@pytest.mark.parametrize("flags", [("--move", "--yes"), ("--move", "--yes", "--verify")])
def test_integrity_move_keeps_the_local_file_if_the_size_is_wrong(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, flags: tuple[str, ...]
) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    wrong_size(monkeypatch)

    assert cli.main(check(folders, *flags)) == 3

    assert file.path.exists()


def test_integrity_move_deletes_once_it_all_matches(folders: tuple[Path, Path]) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))

    assert cli.main(check(folders, "--move", "--yes")) == 0

    assert not file.path.exists()


def test_integrity_move_checks_the_size_only_once_per_upload(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    real_size = LocalTransport.size
    calls: list[PurePosixPath] = []

    def size(self: LocalTransport, path: PurePosixPath) -> int:
        calls.append(path)
        return real_size(self, path)

    monkeypatch.setattr(LocalTransport, "size", size)

    assert cli.main(check(folders, "--move", "--yes")) == 0

    assert calls == [PurePosixPath("a.bin")]


def test_integrity_a_file_with_two_targets_stays_if_one_is_wrong(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5), make_missing("b.bin", file.md5))
    real_size = LocalTransport.size

    def size(self: LocalTransport, path: PurePosixPath) -> int:
        return 1 if path.name == "b.bin" else real_size(self, path)

    monkeypatch.setattr(LocalTransport, "size", size)

    assert cli.main(check(folders, "--move", "--yes")) == 3

    assert file.path.exists()


# --verify


def test_verify_is_off_by_default_because_it_reads_everything_back(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    monkeypatch.setattr(LocalTransport, "read_bytes", must_not_read_the_upload(device))

    assert cli.main(check(folders)) == 0


def must_not_read_the_upload(device: Path) -> Any:
    """The report is read through this too, so only reading anything else is a failure."""
    real_read = LocalTransport.read_bytes

    def read_bytes(self: LocalTransport, path: PurePosixPath) -> bytes:
        assert path.name == "missing_bios_report.txt", f"it read back {path}"
        return real_read(self, path)

    return read_bytes


def test_verify_a_good_upload_passes(folders: tuple[Path, Path]) -> None:
    source, device = folders

    result, upload = run(device, make_bios_file(source, "a.bin"), verify=True)

    assert result.completed == (upload,)
    assert result.errors == ()


def test_verify_a_different_md5_of_the_same_size_is_a_failed_item(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    arrives_damaged(monkeypatch)

    result, upload = run(device, make_bios_file(source, "a.bin"), verify=True)

    assert result.completed == ()
    assert upload_status(upload, result) == "failed"
    assert [(e.code, e.item) for e in result.errors] == [("md5_mismatch", "a.bin")]
    assert "--overwrite" in result.errors[0].message


def test_verify_without_it_the_same_damage_goes_unnoticed_which_is_why_it_exists(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    arrives_damaged(monkeypatch)

    result, _upload = run(device, make_bios_file(source, "a.bin"))

    assert result.errors == ()


def test_verify_a_wrong_size_needs_no_reading_back(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    wrong_size(monkeypatch)
    monkeypatch.setattr(LocalTransport, "read_bytes", must_not_read)

    result, _upload = run(device, make_bios_file(source, "a.bin"), verify=True)

    assert result.errors[0].code == "size_mismatch"


def test_verify_a_read_that_fails_is_a_failed_item(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders

    def no_read(*_args: Any) -> NoReturn:
        raise TransportError("the network went away")

    monkeypatch.setattr(LocalTransport, "read_bytes", no_read)

    result, upload = run(device, make_bios_file(source, "a.bin"), verify=True)

    assert upload_status(upload, result) == "failed"
    assert result.errors[0].message == "the network went away"


def test_verify_move_keeps_the_local_file_if_the_md5_is_wrong(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    arrives_damaged(monkeypatch)

    assert cli.main(check(folders, "--move", "--yes", "--verify")) == 3

    assert file.path.exists()


def test_verify_through_the_command_says_what_failed(
    folders: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    arrives_damaged(monkeypatch)

    assert cli.main(["--json", *check(folders, "--verify")]) == 3

    document = json.loads(capsys.readouterr().out)
    assert document["uploads"][0]["status"] == "failed"
    assert document["errors"][0]["code"] == "md5_mismatch"


def test_verify_a_good_run_through_the_command(folders: tuple[Path, Path]) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))

    assert cli.main(check(folders, "--verify")) == 0

    assert (device / "a.bin").read_bytes() == file.path.read_bytes()


def test_verify_a_dry_run_with_the_flag_changes_nothing(folders: tuple[Path, Path]) -> None:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))

    assert cli.main(check(folders, "--verify", "--dry-run")) == 0

    assert not (device / "a.bin").exists()


def test_verify_reads_back_over_smb_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = install_fake_smb(monkeypatch)
    data = make_bios_file(tmp_path / "source", "a.bin")
    server.files[("bios", "missing_bios_report.txt")] = make_report_text(
        [make_missing("a.bin", data.md5)]
    ).encode()
    real_store = FakeSMBConnection.storeFile

    def store(self: FakeSMBConnection, share: str, path: str, file: Any, **kwargs: Any) -> int:
        written = real_store(self, share, path, file, **kwargs)
        server.files[(share, path)] = bytes(reversed(server.files[(share, path)]))
        return written

    monkeypatch.setattr(FakeSMBConnection, "storeFile", store)
    arguments = ["check", "--source", str(tmp_path / "source"), "--target", "smb://host/bios"]

    assert cli.main([*arguments, "--verify"], base_dir=tmp_path) == 3
    assert "a different MD5" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [["report", "--verify", "--report-file", "x"], ["scan", "--verify"], ["--verify", "check"]],
    ids=["report", "scan", "before-the-command"],
)
def test_verify_belongs_to_check(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(arguments)

    assert stop.value.code == 2


def test_verify_compares_against_the_md5_from_the_scan(folders: tuple[Path, Path]) -> None:
    """Not against the file as it is now: that could have changed too."""
    source, device = folders
    file = make_bios_file(source, "a.bin", b"x" * 64)
    swapped = b"y" * 64
    file.path.write_bytes(swapped)
    assert md5_of(swapped) != file.md5

    result, _upload = run(device, file, verify=True)

    assert result.errors[0].code == "md5_mismatch"
