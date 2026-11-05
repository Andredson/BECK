"""Fixtures for tests against a real SMB server: the Samba test server in tests/integration/samba/.

They're skipped unless BECK_TEST_SMB_HOST and BECK_TEST_SMB_PORT are set. They write to the server,
so they refuse any server that isn't the test server. Never point them at a real Recalbox.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest
from smb.smb_structs import OperationFailure
from smb.SMBConnection import SMBConnection

from beck.errors import TransportError
from beck.transports.smb import SmbTransport

SEEDED_FILE = PurePosixPath("seeded.txt")
SEEDED_TEXT = b"seeded by the Containerfile\n"
REPORT = "missing_bios_report.txt"
ACCOUNT_CREDENTIAL = "beck-test-password"


@dataclass(frozen=True)
class Samba:
    host: str
    port: int

    def guest(self, share: str = "bios") -> SmbTransport:
        return SmbTransport(self.host, self.port, share, "", "", timeout=20)

    def account(self, share: str, password: str) -> SmbTransport:
        return SmbTransport(self.host, self.port, share, "beck", password, timeout=20)

    def config(self, user: str = "", password: str = "") -> str:
        return (
            f'smb: {{user: "{user}", passwd: "{password}", '
            f'server: "{self.host}", port: {self.port}}}\n'
        )


@pytest.fixture(scope="session")
def samba() -> Samba:
    host, port = os.environ.get("BECK_TEST_SMB_HOST"), os.environ.get("BECK_TEST_SMB_PORT")
    if not host or not port:
        pytest.skip("Set BECK_TEST_SMB_HOST and BECK_TEST_SMB_PORT to run these tests")

    server = Samba(host, int(port))
    try:
        with server.guest("readonly") as transport:
            is_test_server = transport.read_bytes(SEEDED_FILE) == SEEDED_TEXT
    except TransportError as e:
        pytest.fail(f"{host}:{port} isn't the BECK test server, so nothing was written: {e}")
    if not is_test_server:
        pytest.fail(f"{host}:{port} isn't the BECK test server, so nothing was written")
    return server


def _connect(samba: Samba) -> SMBConnection:
    conn = SMBConnection("", "", "beck-tests", samba.host, use_ntlm_v2=True, is_direct_tcp=True)
    assert conn.connect(samba.host, samba.port, timeout=20)
    return conn


def _remove_tree(conn: SMBConnection, folder: str) -> None:
    for entry in conn.listPath("bios", folder):
        path = f"{folder}/{entry.filename}"
        if entry.filename in (".", ".."):
            continue
        if entry.isDirectory:
            _remove_tree(conn, path)
        else:
            conn.deleteFiles("bios", path)
    conn.deleteDirectory("bios", folder)


@pytest.fixture
def folder(samba: Samba) -> Iterator[PurePosixPath]:
    """A folder name only this test uses on the bios share, so tests don't interfere."""
    name = PurePosixPath(f"beck-test-{uuid.uuid4().hex}")
    yield name
    conn = _connect(samba)
    try:
        _remove_tree(conn, name.as_posix())
    except OperationFailure:
        pass  # the test never created it
    finally:
        conn.close()


@pytest.fixture
def private_file(samba: Samba) -> Iterator[PurePosixPath]:
    """A file name only this test uses on the private share, removed afterwards."""
    name = PurePosixPath(f"beck-test-{uuid.uuid4().hex}.bin")
    yield name
    conn = SMBConnection(
        "beck", ACCOUNT_CREDENTIAL, "beck-tests", samba.host, use_ntlm_v2=True, is_direct_tcp=True
    )
    assert conn.connect(samba.host, samba.port, timeout=20)
    try:
        conn.deleteFiles("private", name.as_posix())
    finally:
        conn.close()


@pytest.fixture
def put_report(samba: Samba, tmp_path: Path) -> Iterator[Callable[[str | bytes], None]]:
    """Put a report at the root of the bios share, where BECK reads it, and remove it afterwards.

    Every test using this overwrites the same file, which works because tests run one at a time.
    """

    def put(text: str | bytes) -> None:
        local = tmp_path / "report-to-upload.txt"
        local.write_bytes(text.encode() if isinstance(text, str) else text)
        with samba.guest() as transport:
            transport.upload(local, PurePosixPath(REPORT))

    yield put
    conn = _connect(samba)
    try:
        conn.deleteFiles("bios", REPORT)
    except OperationFailure:
        pass  # the test never put one
    finally:
        conn.close()
