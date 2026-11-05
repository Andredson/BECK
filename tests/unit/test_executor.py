"""The executor: normal runs, dry runs, failures that don't stop the run, and no local changes."""

import os
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, Self

import pytest

from beck.errors import TransportError
from beck.executor import execute
from beck.hashing import scan
from beck.matcher import plan
from beck.models import Plan, PlannedUpload, RunResult
from beck.transports.local import LocalTransport
from beck.transports.smb import SmbTransport
from tests.factories import make_bios_file, make_missing, snapshot
from tests.fakes import install_fake_smb


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "source"
    folder.mkdir()
    return folder


@pytest.fixture
def target(tmp_path: Path) -> Path:
    folder = tmp_path / "target"
    folder.mkdir()
    return folder


def source_state(planned: Plan) -> dict[Path, tuple[int, bytes]]:
    files = {upload.source for upload in planned.uploads}
    files.update(duplicate.file for duplicate in planned.duplicates)
    files.update(planned.unmatched, planned.already_filled)
    return {
        file.path: (file.path.stat().st_mtime_ns, file.path.read_bytes())
        for file in files
        if file.path.exists()
    }


def run(plan_to_run: Plan, target: Path, *, dry_run: bool = False) -> RunResult:
    """Execute a plan, and check that every local file is untouched in every scenario (DEC-02)."""
    before = source_state(plan_to_run)
    with LocalTransport(target) as transport:
        result = execute(plan_to_run, transport, dry_run=dry_run)
    assert source_state(plan_to_run) == before
    return result


def targets(uploads: tuple[PlannedUpload, ...]) -> list[str]:
    return [upload.target.as_posix() for upload in uploads]


def test_normal_run_creates_folders_and_uploads(source: Path, target: Path) -> None:
    nested, top = make_bios_file(source, "ps1/copy.bin"), make_bios_file(source, "top.bin")
    report = [make_missing("amiga/bios/kick.rom", nested.md5), make_missing("root.bin", top.md5)]

    result = run(plan(report, scan(source).files), target)

    assert (target / "amiga" / "bios" / "kick.rom").read_bytes() == nested.path.read_bytes()
    assert (target / "root.bin").read_bytes() == top.path.read_bytes()
    assert targets(result.completed) == ["amiga/bios/kick.rom", "root.bin"]
    assert not (result.skipped or result.errors)
    assert result.dry_run is False


def test_the_result_carries_the_plan(source: Path, target: Path) -> None:
    file = make_bios_file(source, "copy.bin")
    built = plan([make_missing("a.bin", file.md5)], scan(source).files)

    assert run(built, target).plan == built


def test_one_file_reaches_all_its_targets(source: Path, target: Path) -> None:
    # The old code deleted the file after the first upload, so the next one failed (D3).
    file = make_bios_file(source, "copy.bin")
    report = [make_missing(name, file.md5) for name in ("a.bin", "b.bin", "c/d.bin")]
    data = file.path.read_bytes()

    run(plan(report, scan(source).files), target)

    assert snapshot(target).keys() == {"a.bin", "b.bin", "c/d.bin"}
    assert file.path.read_bytes() == data


def test_an_empty_plan_does_nothing(target: Path) -> None:
    result = run(Plan(), target)

    assert result == RunResult(plan=Plan())
    assert list(target.iterdir()) == []


def test_dry_run_changes_nothing_and_skips_every_upload(source: Path, target: Path) -> None:
    file = make_bios_file(source, "copy.bin")
    (target / "existing.bin").write_bytes(b"old content")
    before = snapshot(target), snapshot(source)
    report = [make_missing("ps1/a.bin", file.md5), make_missing("existing.bin", file.md5)]
    built = plan(report, scan(source).files)

    result = run(built, target, dry_run=True)

    assert (snapshot(target), snapshot(source)) == before
    assert not (target / "ps1").exists()
    assert result == RunResult(plan=built, skipped=built.uploads, dry_run=True)


class Untouchable:
    """A Transport whose every method fails the test, except opening and closing."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def read_bytes(self, path: PurePosixPath) -> bytes:
        raise AssertionError("a dry run read a file")

    def exists(self, path: PurePosixPath) -> bool:
        raise AssertionError("a dry run checked a file")

    def size(self, path: PurePosixPath) -> int:
        raise AssertionError("a dry run checked a size")

    def makedirs(self, path: PurePosixPath) -> None:
        raise AssertionError("a dry run created a folder")

    def upload(self, local: Path, remote: PurePosixPath) -> int:
        raise AssertionError("a dry run uploaded a file")

    def describe(self) -> str:
        raise AssertionError("a dry run has nothing to describe")


def test_dry_run_calls_no_transport_method(source: Path) -> None:
    file = make_bios_file(source, "copy.bin")
    built = plan([make_missing("ps1/a.bin", file.md5)], scan(source).files)

    assert execute(built, Untouchable(), dry_run=True).skipped == built.uploads


def test_running_again_gives_the_same_result_and_files(source: Path, target: Path) -> None:
    file = make_bios_file(source, "copy.bin")
    make_bios_file(source, "junk.bin")
    report = [make_missing("a.bin", file.md5), make_missing("ps1/x/b.bin", file.md5)]
    built = plan(report, scan(source).files)

    first = run(built, target)
    files_after_first = {name: state[2] for name, state in snapshot(target).items()}
    second = run(built, target)

    assert second == first
    assert not second.errors
    assert {name: state[2] for name, state in snapshot(target).items()} == files_after_first


def test_a_dry_run_after_a_real_run_changes_nothing(source: Path, target: Path) -> None:
    file = make_bios_file(source, "copy.bin")
    built = plan([make_missing("ps1/a.bin", file.md5)], scan(source).files)
    run(built, target)
    before = snapshot(target)

    run(built, target, dry_run=True)

    assert snapshot(target) == before


needs_permissions = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")


@pytest.fixture
def restore_permissions() -> Iterator[list[Path]]:
    """Paths whose permissions a test took away; restored so that pytest can clean them up."""
    changed: list[Path] = []
    yield changed
    for path in changed:
        path.chmod(0o755)


@needs_permissions
def test_a_read_only_folder_is_recorded_and_the_run_continues(
    source: Path, target: Path, restore_permissions: list[Path]
) -> None:
    file = make_bios_file(source, "copy.bin")
    locked = target / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    restore_permissions.append(locked)
    report = [
        make_missing("a.bin", file.md5),
        make_missing("locked/b.bin", file.md5),
        make_missing("z.bin", file.md5),
    ]

    result = run(plan(report, scan(source).files), target)

    assert targets(result.completed) == ["a.bin", "z.bin"]
    assert [error.item for error in result.errors] == ["locked/b.bin"]
    assert "Permission denied" in result.errors[0].message
    assert list(locked.iterdir()) == []


@needs_permissions
def test_a_read_only_target_file_is_recorded_and_kept(
    source: Path, target: Path, restore_permissions: list[Path]
) -> None:
    file = make_bios_file(source, "copy.bin")
    existing = target / "a.bin"
    existing.write_bytes(b"old content")
    existing.chmod(0o444)
    restore_permissions.append(existing)

    result = run(plan([make_missing("a.bin", file.md5)], scan(source).files), target)

    assert [error.item for error in result.errors] == ["a.bin"]
    assert existing.read_bytes() == b"old content"


@needs_permissions
def test_a_folder_it_cannot_create_skips_its_uploads_and_continues(
    source: Path, target: Path, restore_permissions: list[Path]
) -> None:
    file = make_bios_file(source, "copy.bin")
    locked = target / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    restore_permissions.append(locked)
    report = [make_missing("locked/new/b.bin", file.md5), make_missing("z.bin", file.md5)]

    result = run(plan(report, scan(source).files), target)

    assert [error.item for error in result.errors] == ["locked/new"]
    assert targets(result.skipped) == ["locked/new/b.bin"]
    assert targets(result.completed) == ["z.bin"]


@needs_permissions
def test_a_local_file_it_cannot_read_is_recorded_and_the_run_continues(
    source: Path, target: Path, restore_permissions: list[Path]
) -> None:
    unreadable, kept = make_bios_file(source, "a.bin"), make_bios_file(source, "b.bin")
    report = [make_missing("x.bin", unreadable.md5), make_missing("y.bin", kept.md5)]
    built = plan(report, scan(source).files)
    unreadable.path.chmod(0o000)
    restore_permissions.append(unreadable.path)

    with LocalTransport(target) as transport:
        result = execute(built, transport, dry_run=False)

    assert [error.item for error in result.errors] == ["x.bin"]
    assert targets(result.completed) == ["y.bin"]
    assert not (target / "x.bin").exists()


def test_a_failed_upload_is_recorded_and_the_run_continues(source: Path, target: Path) -> None:
    first = make_bios_file(source, "a.bin")
    bad = make_bios_file(source, "b.bin")
    last = make_bios_file(source, "z.bin")
    report = [
        make_missing("a.bin", first.md5),
        make_missing("b.bin", bad.md5),
        make_missing("z.bin", last.md5),
    ]
    (target / "b.bin").mkdir()  # uploading over a folder fails

    result = run(plan(report, scan(source).files), target)

    assert targets(result.completed) == ["a.bin", "z.bin"]
    assert [error.item for error in result.errors] == ["b.bin"]
    assert "b.bin" in result.errors[0].message
    assert (target / "a.bin").read_bytes() == first.path.read_bytes()
    assert (target / "z.bin").read_bytes() == last.path.read_bytes()


def test_a_local_file_that_vanished_is_a_failed_item(source: Path, target: Path) -> None:
    gone, kept = make_bios_file(source, "gone.bin"), make_bios_file(source, "kept.bin")
    report = [make_missing("a.bin", gone.md5), make_missing("b.bin", kept.md5)]
    built = plan(report, scan(source).files)
    gone.path.unlink()

    result = run(built, target)

    assert [error.item for error in result.errors] == ["a.bin"]
    assert targets(result.completed) == ["b.bin"]


def test_a_failed_folder_skips_its_uploads_and_the_run_continues(
    source: Path, target: Path
) -> None:
    file = make_bios_file(source, "copy.bin")
    (target / "blocked").write_bytes(b"a file where a folder should go")
    names = ("blocked/a.bin", "blocked/b.bin", "ps1/c.bin", "root.bin")
    report = [make_missing(name, file.md5) for name in names]

    result = run(plan(report, scan(source).files), target)

    assert [error.item for error in result.errors] == ["blocked"]
    assert targets(result.skipped) == ["blocked/a.bin", "blocked/b.bin"]
    assert targets(result.completed) == ["ps1/c.bin", "root.bin"]
    assert (target / "ps1" / "c.bin").read_bytes() == file.path.read_bytes()


def test_an_unexpected_error_is_not_swallowed(source: Path, tmp_path: Path) -> None:
    class Broken(LocalTransport):
        def upload(self, local: Path, remote: PurePosixPath) -> int:
            raise RuntimeError("a bug in BECK")

    file = make_bios_file(source, "copy.bin")
    built = plan([make_missing("a.bin", file.md5)], scan(source).files)

    with Broken(tmp_path) as transport, pytest.raises(RuntimeError, match="a bug in BECK"):
        execute(built, transport, dry_run=False)


def test_an_existing_remote_file_is_replaced_as_in_stage_03(source: Path, target: Path) -> None:
    file = make_bios_file(source, "copy.bin")
    (target / "a.bin").write_bytes(b"old content")

    run(plan([make_missing("a.bin", file.md5)], scan(source).files), target)

    assert (target / "a.bin").read_bytes() == file.path.read_bytes()


@pytest.mark.parametrize("dry_run", [False, True])
def test_the_source_folder_is_unchanged_afterwards(
    source: Path, target: Path, dry_run: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise AssertionError("a local file was deleted or renamed")

    file = make_bios_file(source, "ps1/copy.bin")
    make_bios_file(source, "ps1/duplicate.bin", file.path.read_bytes())
    make_bios_file(source, "junk.bin")
    make_bios_file(source, ".keep", b"")
    built = plan([make_missing("x/a.bin", file.md5)], scan(source).files)
    before = snapshot(source)
    for name in ("rename", "replace", "unlink", "rmdir"):
        monkeypatch.setattr(Path, name, forbidden)
    for name in ("rename", "replace", "remove", "unlink", "rmdir"):
        monkeypatch.setattr(os, name, forbidden)

    result = run(built, target, dry_run=dry_run)

    assert snapshot(source) == before
    assert len(result.plan.duplicates) == 1


def test_the_source_path_is_what_gets_uploaded(source: Path, target: Path) -> None:
    # Uploaded straight from its own path, under the target's name.
    file = make_bios_file(source, "ps1/my-copy.bin")

    run(plan([make_missing("scph5501.bin", file.md5)], [file]), target)

    assert (target / "scph5501.bin").read_bytes() == file.path.read_bytes()
    assert file.path.exists()


def test_a_full_run_through_the_smb_transport(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = install_fake_smb(monkeypatch)
    monkeypatch.chdir(tmp_path)
    file = make_bios_file(source, "copy.bin")
    built = plan([make_missing("amiga/bios/kick.rom", file.md5)], scan(source).files)

    with SmbTransport("beck-test-server", 445, "bios", "", "") as transport:
        result = execute(built, transport, dry_run=False)

    assert targets(result.completed) == ["amiga/bios/kick.rom"]
    assert server.files[("bios", "amiga/bios/kick.rom")] == file.path.read_bytes()
    assert len(server.connections) == 1
    assert server.connections[0].closed


def test_transport_errors_through_smb_are_item_errors(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = install_fake_smb(monkeypatch)
    monkeypatch.chdir(tmp_path)
    file = make_bios_file(source, "copy.bin")
    built = plan([make_missing("a.bin", file.md5)], scan(source).files)

    with SmbTransport("beck-test-server", 445, "bios", "", "") as transport:
        server.failures["storeFile"] = TimeoutError()
        result = execute(built, transport, dry_run=False)

    assert result.completed == ()
    assert [error.item for error in result.errors] == ["a.bin"]
    assert "Timed out" in result.errors[0].message


def test_transport_error_type_is_the_item_failure(source: Path, tmp_path: Path) -> None:
    class Refusing(LocalTransport):
        def upload(self, local: Path, remote: PurePosixPath) -> int:
            raise TransportError("refused")

    file = make_bios_file(source, "copy.bin")
    built = plan([make_missing("a.bin", file.md5)], scan(source).files)

    with Refusing(tmp_path) as transport:
        result = execute(built, transport, dry_run=False)

    assert result.errors[0].message == "refused"
