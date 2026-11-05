"""The executor: normal runs, dry runs, failures that don't stop the run, and no local changes."""

import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, Self

import pytest

from beck.errors import TransportError
from beck.executor import execute
from beck.hashing import scan
from beck.matcher import plan
from beck.models import LocalFile, MissingBios, Plan, PlannedUpload, RunResult
from beck.transports.local import LocalTransport
from beck.transports.smb import SmbTransport
from tests.fakes import install_fake_smb


def md5_of(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def entry(target: str, *md5s: str) -> MissingBios:
    path = PurePosixPath(target)
    return MissingBios(name=path.name, target=path, md5s=frozenset(md5s))


def snapshot(folder: Path) -> dict[str, tuple[int, int, bytes]]:
    return {
        path.relative_to(folder).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in folder.rglob("*")
        if path.is_file()
    }


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


def write(path: Path, data: bytes | None = None) -> bytes:
    content = os.urandom(64) if data is None else data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def run(plan_to_run: Plan, target: Path, *, dry_run: bool = False) -> RunResult:
    with LocalTransport(target) as transport:
        return execute(plan_to_run, transport, dry_run=dry_run)


def targets(uploads: tuple[PlannedUpload, ...]) -> list[str]:
    return [upload.target.as_posix() for upload in uploads]


def test_normal_run_creates_folders_and_uploads(source: Path, target: Path) -> None:
    nested, top = write(source / "ps1" / "copy.bin"), write(source / "top.bin")
    report = [entry("amiga/bios/kick.rom", md5_of(nested)), entry("root.bin", md5_of(top))]

    result = run(plan(report, scan(source)), target)

    assert (target / "amiga" / "bios" / "kick.rom").read_bytes() == nested
    assert (target / "root.bin").read_bytes() == top
    assert targets(result.completed) == ["amiga/bios/kick.rom", "root.bin"]
    assert not (result.skipped or result.errors)
    assert result.dry_run is False


def test_the_result_carries_the_plan(source: Path, target: Path) -> None:
    data = write(source / "copy.bin")
    built = plan([entry("a.bin", md5_of(data))], scan(source))

    assert run(built, target).plan == built


def test_one_file_reaches_all_its_targets(source: Path, target: Path) -> None:
    # The old code deleted the file after the first upload, so the next one failed (D3).
    data = write(source / "copy.bin")
    md5 = md5_of(data)

    run(
        plan([entry("a.bin", md5), entry("b.bin", md5), entry("c/d.bin", md5)], scan(source)),
        target,
    )

    assert snapshot(target).keys() == {"a.bin", "b.bin", "c/d.bin"}
    assert (source / "copy.bin").read_bytes() == data


def test_an_empty_plan_does_nothing(target: Path) -> None:
    result = run(Plan(), target)

    assert result == RunResult(plan=Plan())
    assert list(target.iterdir()) == []


def test_dry_run_changes_nothing_and_skips_every_upload(source: Path, target: Path) -> None:
    data = write(source / "copy.bin")
    (target / "existing.bin").write_bytes(b"old content")
    before = snapshot(target), snapshot(source)
    report = [entry("ps1/a.bin", md5_of(data)), entry("existing.bin", md5_of(data))]
    built = plan(report, scan(source))

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
    data = write(source / "copy.bin")
    built = plan([entry("ps1/a.bin", md5_of(data))], scan(source))

    assert execute(built, Untouchable(), dry_run=True).skipped == built.uploads


def test_a_failed_upload_is_recorded_and_the_run_continues(source: Path, target: Path) -> None:
    good_a, bad, good_z = write(source / "a.bin"), write(source / "b.bin"), write(source / "z.bin")
    report = [
        entry("a.bin", md5_of(good_a)),
        entry("b.bin", md5_of(bad)),
        entry("z.bin", md5_of(good_z)),
    ]
    (target / "b.bin").mkdir()  # uploading over a folder fails

    result = run(plan(report, scan(source)), target)

    assert targets(result.completed) == ["a.bin", "z.bin"]
    assert [error.item for error in result.errors] == ["b.bin"]
    assert "b.bin" in result.errors[0].message
    assert (target / "a.bin").read_bytes() == good_a
    assert (target / "z.bin").read_bytes() == good_z


def test_a_local_file_that_vanished_is_a_failed_item(source: Path, target: Path) -> None:
    gone, kept = write(source / "gone.bin"), write(source / "kept.bin")
    report = [entry("a.bin", md5_of(gone)), entry("b.bin", md5_of(kept))]
    built = plan(report, scan(source))
    (source / "gone.bin").unlink()

    result = run(built, target)

    assert [error.item for error in result.errors] == ["a.bin"]
    assert targets(result.completed) == ["b.bin"]


def test_a_failed_folder_skips_its_uploads_and_the_run_continues(
    source: Path, target: Path
) -> None:
    data = write(source / "copy.bin")
    md5 = md5_of(data)
    (target / "blocked").write_bytes(b"a file where a folder should go")
    report = [
        entry("blocked/a.bin", md5),
        entry("blocked/b.bin", md5),
        entry("ps1/c.bin", md5),
        entry("root.bin", md5),
    ]

    result = run(plan(report, scan(source)), target)

    assert [error.item for error in result.errors] == ["blocked"]
    assert targets(result.skipped) == ["blocked/a.bin", "blocked/b.bin"]
    assert targets(result.completed) == ["ps1/c.bin", "root.bin"]
    assert (target / "ps1" / "c.bin").read_bytes() == data


def test_an_unexpected_error_is_not_swallowed(source: Path, tmp_path: Path) -> None:
    class Broken(LocalTransport):
        def upload(self, local: Path, remote: PurePosixPath) -> int:
            raise RuntimeError("a bug in BECK")

    data = write(source / "copy.bin")

    with Broken(tmp_path) as transport, pytest.raises(RuntimeError, match="a bug in BECK"):
        execute(plan([entry("a.bin", md5_of(data))], scan(source)), transport, dry_run=False)


def test_an_existing_remote_file_is_replaced_as_in_stage_03(source: Path, target: Path) -> None:
    data = write(source / "copy.bin")
    (target / "a.bin").write_bytes(b"old content")

    run(plan([entry("a.bin", md5_of(data))], scan(source)), target)

    assert (target / "a.bin").read_bytes() == data


@pytest.mark.parametrize("dry_run", [False, True])
def test_the_source_folder_is_unchanged_afterwards(
    source: Path, target: Path, dry_run: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise AssertionError("a local file was deleted or renamed")

    for name in ("rename", "replace", "unlink", "rmdir"):
        monkeypatch.setattr(Path, name, forbidden)
    for name in ("rename", "replace", "remove", "unlink", "rmdir"):
        monkeypatch.setattr(os, name, forbidden)
    data = write(source / "ps1" / "copy.bin")
    write(source / "ps1" / "duplicate.bin", data)
    write(source / "junk.bin")
    write(source / ".keep", b"")
    before = snapshot(source)

    result = run(plan([entry("x/a.bin", md5_of(data))], scan(source)), target, dry_run=dry_run)

    assert snapshot(source) == before
    assert len(result.plan.duplicates) == 1


def test_the_source_path_is_what_gets_uploaded(source: Path, target: Path) -> None:
    # Uploaded straight from its own path, under the target's name.
    data = write(source / "ps1" / "my-copy.bin")
    file = LocalFile(
        path=source / "ps1" / "my-copy.bin",
        relative=PurePosixPath("ps1/my-copy.bin"),
        md5=md5_of(data),
        size=len(data),
    )

    run(plan([entry("scph5501.bin", file.md5)], [file]), target)

    assert (target / "scph5501.bin").read_bytes() == data
    assert (source / "ps1" / "my-copy.bin").exists()


def test_a_full_run_through_the_smb_transport(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = install_fake_smb(monkeypatch)
    monkeypatch.chdir(tmp_path)
    data = write(source / "copy.bin")
    built = plan([entry("amiga/bios/kick.rom", md5_of(data))], scan(source))

    with SmbTransport("beck-test-server", 445, "bios", "", "") as transport:
        result = execute(built, transport, dry_run=False)

    assert targets(result.completed) == ["amiga/bios/kick.rom"]
    assert server.files[("bios", "amiga/bios/kick.rom")] == data
    assert len(server.connections) == 1
    assert server.connections[0].closed


def test_transport_errors_through_smb_are_item_errors(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = install_fake_smb(monkeypatch)
    monkeypatch.chdir(tmp_path)
    data = write(source / "copy.bin")
    built = plan([entry("a.bin", md5_of(data))], scan(source))

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

    data = write(source / "copy.bin")

    with Refusing(tmp_path) as transport:
        result = execute(
            plan([entry("a.bin", md5_of(data))], scan(source)), transport, dry_run=False
        )

    assert result.errors[0].message == "refused"
