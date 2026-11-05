"""LocalTransport: file operations under one folder, and no way out of that folder."""

import os
from pathlib import Path, PurePosixPath

import pytest

from beck.errors import TransportError
from beck.transports.base import Transport
from beck.transports.local import LocalTransport


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "bios"
    folder.mkdir()
    return folder


@pytest.fixture
def transport(root: Path) -> Transport:  # mypy checks that the class follows the Protocol
    return LocalTransport(root)


def source(tmp_path: Path, data: bytes = b"\x00\x01\x02") -> Path:
    file = tmp_path / "local.bin"
    file.write_bytes(data)
    return file


def test_used_as_a_context_manager(root: Path) -> None:
    with LocalTransport(root) as opened:
        assert opened.exists(PurePosixPath("."))


def test_a_missing_root_is_a_transport_error(tmp_path: Path) -> None:
    with (
        pytest.raises(TransportError, match="doesn't exist"),
        LocalTransport(tmp_path / "no-such-folder"),
    ):
        pass


def test_a_file_as_root_is_a_transport_error(tmp_path: Path) -> None:
    with pytest.raises(TransportError, match="doesn't exist"), LocalTransport(source(tmp_path)):
        pass


def test_makedirs_creates_every_level(root: Path, transport: Transport) -> None:
    transport.makedirs(PurePosixPath("a/b/c"))

    assert (root / "a" / "b" / "c").is_dir()


def test_makedirs_on_an_existing_folder_is_fine(root: Path, transport: Transport) -> None:
    (root / "a").mkdir()
    (root / "a" / "keep.bin").write_bytes(b"keep")

    transport.makedirs(PurePosixPath("a"))

    assert (root / "a" / "keep.bin").read_bytes() == b"keep"


def test_makedirs_with_a_file_in_the_way_is_a_transport_error(
    root: Path, transport: Transport
) -> None:
    (root / "a").write_bytes(b"a file")

    with pytest.raises(TransportError, match="Error creating folder a/b"):
        transport.makedirs(PurePosixPath("a/b"))


def test_upload_copies_the_file_and_returns_its_size(
    tmp_path: Path, root: Path, transport: Transport
) -> None:
    data = os.urandom(5000)
    transport.makedirs(PurePosixPath("ps1"))

    written = transport.upload(source(tmp_path, data), PurePosixPath("ps1/scph.bin"))

    assert written == 5000
    assert (root / "ps1" / "scph.bin").read_bytes() == data


def test_upload_leaves_the_source_untouched(tmp_path: Path, transport: Transport) -> None:
    local = source(tmp_path)
    before = local.stat()

    transport.upload(local, PurePosixPath("copy.bin"))

    assert local.read_bytes() == b"\x00\x01\x02"
    assert local.stat().st_mtime_ns == before.st_mtime_ns


def test_upload_replaces_an_existing_file(tmp_path: Path, root: Path, transport: Transport) -> None:
    (root / "a.bin").write_bytes(b"old content")

    assert transport.upload(source(tmp_path, b"new"), PurePosixPath("a.bin")) == 3
    assert (root / "a.bin").read_bytes() == b"new"


def test_upload_needs_the_folder_to_exist(tmp_path: Path, transport: Transport) -> None:
    with pytest.raises(TransportError, match="Error copying"):
        transport.upload(source(tmp_path), PurePosixPath("missing/a.bin"))


def test_upload_of_a_missing_local_file_is_a_transport_error(
    tmp_path: Path, transport: Transport
) -> None:
    with pytest.raises(TransportError, match="Error copying"):
        transport.upload(tmp_path / "no-such-file", PurePosixPath("a.bin"))


def test_read_bytes(root: Path, transport: Transport) -> None:
    (root / "report.txt").write_bytes(b"line\r\n")

    assert transport.read_bytes(PurePosixPath("report.txt")) == b"line\r\n"


def test_reading_a_missing_file_is_a_transport_error(transport: Transport) -> None:
    with pytest.raises(TransportError, match=r"Error reading missing\.txt"):
        transport.read_bytes(PurePosixPath("missing.txt"))


def test_size(root: Path, transport: Transport) -> None:
    (root / "a.bin").write_bytes(b"12345")

    assert transport.size(PurePosixPath("a.bin")) == 5


def test_size_of_a_missing_file_is_a_transport_error(transport: Transport) -> None:
    with pytest.raises(TransportError, match=r"Error getting the size of missing\.bin"):
        transport.size(PurePosixPath("missing.bin"))


def test_exists(root: Path, transport: Transport) -> None:
    (root / "a.bin").write_bytes(b"")
    (root / "folder").mkdir()

    assert transport.exists(PurePosixPath("a.bin"))
    assert transport.exists(PurePosixPath("folder"))
    assert not transport.exists(PurePosixPath("missing"))


ESCAPES = [
    "../outside.bin",
    "a/../../outside.bin",
    "/etc/outside.bin",
    "../bios-evil/outside.bin",  # shares the root's name as a prefix
]


@pytest.mark.parametrize("path", ESCAPES)
def test_every_operation_refuses_a_path_outside_the_root(
    tmp_path: Path, transport: Transport, path: str
) -> None:
    remote = PurePosixPath(path)
    local = source(tmp_path)
    (tmp_path / "bios-evil").mkdir()
    before = sorted(p.name for p in tmp_path.rglob("*"))

    for action in (
        lambda: transport.read_bytes(remote),
        lambda: transport.exists(remote),
        lambda: transport.size(remote),
        lambda: transport.makedirs(remote),
        lambda: transport.upload(local, remote),
    ):
        with pytest.raises(TransportError, match="is outside"):
            action()

    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_a_symlink_out_of_the_root_is_refused(
    tmp_path: Path, root: Path, transport: Transport
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)

    with pytest.raises(TransportError, match="is outside"):
        transport.upload(source(tmp_path), PurePosixPath("link/a.bin"))

    assert list(outside.iterdir()) == []


def test_a_symlink_inside_the_root_is_allowed(
    tmp_path: Path, root: Path, transport: Transport
) -> None:
    (root / "real").mkdir()
    (root / "link").symlink_to(root / "real")

    transport.upload(source(tmp_path), PurePosixPath("link/a.bin"))

    assert (root / "real" / "a.bin").exists()


def test_a_root_reached_through_a_symlink_works(tmp_path: Path, root: Path) -> None:
    link = tmp_path / "root-link"
    link.symlink_to(root)

    with LocalTransport(link) as transport:
        transport.upload(source(tmp_path), PurePosixPath("a.bin"))

    assert (root / "a.bin").exists()


def test_describe_names_the_folder(root: Path, transport: Transport) -> None:
    assert transport.describe() == f"local folder {root.resolve()}"
