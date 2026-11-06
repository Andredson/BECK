"""A share on an SMB server, through pysmb (DEC-53). Only this module talks to pysmb."""

import io
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Self

from smb.base import SMBTimeout
from smb.smb_structs import OperationFailure
from smb.SMBConnection import SMBConnection

from beck.errors import TransportError
from beck.models import SHARE_ROOT


@contextmanager
def _reporting(action: str) -> Iterator[None]:
    """Turn any pysmb failure into a TransportError. It raises many unrelated exception types."""
    try:
        yield
    except (SMBTimeout, TimeoutError) as e:
        raise TransportError(f"Timed out {action}") from e
    except OperationFailure as e:
        raise TransportError(f"Error {action}: {e.message}") from e  # str(e) dumps SMB messages
    except Exception as e:
        raise TransportError(f"Error {action}: {e}") from e


def _same_name(name: str, names: list[str]) -> str | None:
    """A file's real name, ignoring case as Samba does: uploading A.BIN would overwrite a.bin."""
    wanted = name.casefold()
    return next((candidate for candidate in names if candidate.casefold() == wanted), None)


def client_name() -> str:
    """The name BECK gives itself on the connection: this computer's host name, or "BECK"."""
    try:
        return socket.gethostname() or "BECK"
    except OSError:
        return "BECK"


class SmbTransport:
    """One connection to one share for the whole run. It connects once and always closes."""

    def __init__(
        self,
        host: str,
        port: int,
        share: str,
        user: str,
        password: str,
        timeout: float = 30,
        root: PurePosixPath = SHARE_ROOT,
    ) -> None:
        self.host = host
        self.port = port
        self.share = share
        self.user = user
        self.password = password
        self.timeout = timeout
        self.root = root  # the BIOS folder, relative to the share
        self._conn: Any = None

    def __enter__(self) -> Self:
        # Port 445 is SMB over plain TCP; other ports need a NetBIOS session first (D16).
        conn = SMBConnection(
            self.user,
            self.password,
            client_name(),
            self.host,
            use_ntlm_v2=True,
            is_direct_tcp=self.port == 445,
        )
        try:
            self._open(conn)
        except BaseException:
            conn.close()  # __exit__ doesn't run when __enter__ fails
            raise
        self._conn = conn
        return self

    def __exit__(self, *exc: object) -> None:
        self._conn.close()

    def _open(self, conn: Any) -> None:
        with _reporting(f"connecting to SMB server {self.host}"):
            logged_in = conn.connect(self.host, self.port, timeout=self.timeout)
        if not logged_in:
            raise TransportError(
                f"SMB server {self.host} refused the login: check the user and password"
            )
        with _reporting(f"listing the shares of SMB server {self.host}"):
            shares = conn.listShares(timeout=self.timeout)
        if not any(s.name == self.share for s in shares):
            raise TransportError(f"The share {self.share} doesn't exist on SMB server {self.host}")

    def _list_dirs(self, parent: str) -> list[str]:
        return [e.filename for e in self._list(parent) if e.isDirectory]

    def _list(self, parent: str) -> list[Any]:
        with _reporting(f"listing folder {parent!r} on share {self.share}"):
            entries = self._conn.listPath(self.share, parent, timeout=self.timeout)
        return [e for e in entries if e.filename not in (".", "..")]

    def read_bytes(self, path: PurePosixPath) -> bytes:
        buffer = io.BytesIO()  # in memory: no local or temporary file is written (D6)
        with _reporting(f"reading {path} from share {self.share}"):
            self._conn.retrieveFile(
                self.share, (self.root / path).as_posix(), buffer, timeout=self.timeout
            )
        return buffer.getvalue()

    def exists(self, path: PurePosixPath) -> bool:
        # Walks down the listings, because pysmb raises the same exception for "not found" and for
        # a real failure such as "access denied". A failed listing stays an error here.
        parent = ""
        for name in (self.root / path).parts:
            actual = _same_name(name, [e.filename for e in self._list(parent)])
            if actual is None:
                return False
            parent = f"{parent}{actual}/"
        return True

    def size(self, path: PurePosixPath) -> int:
        with _reporting(f"getting the size of {path} on share {self.share}"):
            attributes = self._conn.getAttributes(
                self.share, (self.root / path).as_posix(), timeout=self.timeout
            )
            return int(attributes.file_size)

    def makedirs(self, path: PurePosixPath) -> None:
        # createDirectory isn't recursive, so each missing level is created in order (D4).
        parent = ""
        for name in (self.root / path).parts:
            actual = _same_name(name, self._list_dirs(parent))
            if actual is None:
                actual = name
                with _reporting(f"creating folder {parent}{name} on share {self.share}"):
                    self._conn.createDirectory(self.share, f"{parent}{name}", timeout=self.timeout)
            parent = f"{parent}{actual}/"

    def upload(self, local: Path, remote: PurePosixPath) -> int:
        with (
            _reporting(f"uploading {local} to {remote} on share {self.share}"),
            local.open("rb") as file,  # closed before this returns (D7)
        ):
            written = self._conn.storeFile(
                self.share, (self.root / remote).as_posix(), file, timeout=self.timeout
            )
            return int(written)

    def _where(self) -> str:
        return self.share if self.root == SHARE_ROOT else f"{self.share}/{self.root}"

    def describe(self) -> str:
        return f"SMB share {self._where()} on {self.host}:{self.port}"

    def url(self) -> str:
        return f"smb://{self.host}:{self.port}/{self._where()}"
