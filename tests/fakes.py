"""In-memory stand-in for pysmb's SMBConnection, so that no test touches a network or a Recalbox.

Install it with ``install_fake_smb(monkeypatch)``. Every ``SMBConnection(...)`` that check_bios
creates is then a ``FakeSMBConnection`` bound to one ``FakeSMBServer``, which holds the shares,
files and folders, and remembers every connection made to it.
"""

from dataclasses import dataclass
from typing import IO, Any

import pytest
from smb.smb_structs import OperationFailure

import check_bios


@dataclass(frozen=True)
class FakeShare:
    """The part of pysmb's SharedDevice that check_bios reads."""

    name: str


@dataclass(frozen=True)
class FakeEntry:
    """The part of pysmb's SharedFile that check_bios reads."""

    filename: str
    isDirectory: bool  # pysmb's spelling


def _norm(path: str) -> str:
    return path.strip("/")


def _parent(path: str) -> str:
    return path.rpartition("/")[0]


class FakeSMBServer:
    """Shares, files and folders in dicts. ``failures`` makes a method raise instead of working."""

    def __init__(self, shares: tuple[str, ...] = ("bios",)) -> None:
        self.shares = shares
        self.files: dict[tuple[str, str], bytes] = {}
        self.dirs: set[tuple[str, str]] = set()
        self.connections: list[FakeSMBConnection] = []
        self.login_succeeds = True
        self.failures: dict[str, Exception] = {}

    def new_connection(self, *args: Any, **kwargs: Any) -> "FakeSMBConnection":
        """Stands in for the ``SMBConnection`` class: same arguments, returns a bound fake."""
        conn = FakeSMBConnection(self, *args, **kwargs)
        self.connections.append(conn)
        return conn

    def exists(self, share: str, path: str) -> bool:
        return path == "" or (share, path) in self.dirs or (share, path) in self.files


class FakeSMBConnection:
    """Behaves like pysmb's SMBConnection (same method names) for the calls check_bios makes."""

    def __init__(
        self,
        server: FakeSMBServer,
        username: str,
        password: str,
        my_name: str,
        remote_name: str,
        domain: str = "",
        use_ntlm_v2: bool = True,
        sign_options: int = 2,
        is_direct_tcp: bool = False,
    ) -> None:
        self.server = server
        self.username = username
        self.password = password
        self.my_name = my_name
        self.remote_name = remote_name
        self.is_direct_tcp = is_direct_tcp
        self.calls: list[str] = []
        self.connected = False
        self.closed = False
        self.stored_files: list[IO[bytes]] = []

    def _call(self, name: str, *, needs_connection: bool = True) -> None:
        self.calls.append(name)
        if name in self.server.failures:
            raise self.server.failures[name]
        if needs_connection and (not self.connected or self.closed):
            raise AssertionError(f"{name}() called on a connection that isn't open")

    def connect(self, ip: str, port: int = 139, sock_family: Any = None, timeout: int = 60) -> bool:
        self._call("connect", needs_connection=False)
        self.connected = True
        return self.server.login_succeeds

    def close(self) -> None:
        self.calls.append("close")
        self.closed = True

    def listShares(self, timeout: int = 30) -> list[FakeShare]:
        self._call("listShares")
        return [FakeShare(name) for name in self.server.shares]

    def retrieveFile(
        self, service_name: str, path: str, file_obj: IO[bytes], timeout: int = 30
    ) -> None:
        self._call("retrieveFile")
        content = self.server.files.get((service_name, _norm(path)))
        if content is None:
            raise OperationFailure(f"Failed to retrieve {path} on {service_name}", [])
        file_obj.write(content)

    def storeFile(
        self, service_name: str, path: str, file_obj: IO[bytes], timeout: int = 30
    ) -> None:
        self._call("storeFile")
        self.stored_files.append(file_obj)
        if not self.server.exists(service_name, _parent(_norm(path))):
            raise OperationFailure(
                f"Failed to store {path} on {service_name}: no parent folder", []
            )
        self.server.files[(service_name, _norm(path))] = file_obj.read()

    def createDirectory(self, service_name: str, path: str, timeout: int = 30) -> None:
        self._call("createDirectory")
        folder = _norm(path)
        if self.server.exists(service_name, folder) or not self.server.exists(
            service_name, _parent(folder)
        ):
            raise OperationFailure(f"Failed to create directory {path} on {service_name}", [])
        self.server.dirs.add((service_name, folder))

    def listPath(self, service_name: str, path: str, *args: Any, **kwargs: Any) -> list[FakeEntry]:
        self._call("listPath")
        folder = _norm(path)
        if not self.server.exists(service_name, folder):
            raise OperationFailure(f"Failed to list {path} on {service_name}", [])
        entries = [FakeEntry(".", True), FakeEntry("..", True)]
        for share, child in sorted(self.server.dirs):
            if share == service_name and _parent(child) == folder:
                entries.append(FakeEntry(child.rpartition("/")[2], True))
        for share, child in sorted(self.server.files):
            if share == service_name and _parent(child) == folder:
                entries.append(FakeEntry(child.rpartition("/")[2], False))
        return entries


def install_fake_smb(
    monkeypatch: pytest.MonkeyPatch, server: FakeSMBServer | None = None
) -> FakeSMBServer:
    """Make check_bios use a fake SMB server, and make any real socket connection fail the test."""
    server = server or FakeSMBServer()
    monkeypatch.setattr(check_bios, "SMBConnection", server.new_connection)

    def no_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a test tried to open a real network connection")

    monkeypatch.setattr("socket.socket.connect", no_network)
    monkeypatch.setattr("socket.create_connection", no_network)
    return server
