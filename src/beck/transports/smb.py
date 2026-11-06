"""A share on an SMB server, through pysmb (DEC-53). Only this module talks to pysmb."""

import io
import logging
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Self

from smb.base import SMBTimeout
from smb.smb_structs import OperationFailure
from smb.SMBConnection import SMBConnection

from beck.errors import TransportError
from beck.models import SHARE_ROOT

DEFAULT_TIMEOUT = 30  # seconds

_log = logging.getLogger(__name__)


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
        timeout: float = DEFAULT_TIMEOUT,
        root: PurePosixPath = SHARE_ROOT,
    ) -> None:
        """Keep the details. Nothing connects until the ``with`` block opens.

        ``root`` is the BIOS folder, relative to the share.
        """
        self.host = host
        self.port = port
        self.share = share
        self.user = user
        self.password = password
        self.timeout = timeout
        self.root = root  # the BIOS folder, relative to the share
        self._conn: Any = None

    def __enter__(self) -> Self:
        """Connect, log in and check that the share exists, or raise TransportError."""
        # Port 445 is SMB over plain TCP; other ports need a NetBIOS session first (D16).
        conn = SMBConnection(
            self.user,
            self.password,
            client_name(),
            self.host,
            use_ntlm_v2=True,
            is_direct_tcp=self.port == 445,
        )
        _log.debug(
            "Connecting to %s:%d, %s, %s",
            self.host,
            self.port,
            "over plain TCP" if self.port == 445 else "with a NetBIOS session",
            "with a user name" if self.user else "as a guest",
        )
        try:
            self._open(conn)
        except BaseException:
            conn.close()  # __exit__ doesn't run when __enter__ fails
            raise
        _log.debug("Connected, and the share %s exists", self.share)
        self._conn = conn
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the connection, even after an error."""
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

    def _inside(self, path: PurePosixPath) -> PurePosixPath:
        """The path under the root, or an error: what a report asks for could be anything.

        Each of these could reach another folder, and SMB takes a backslash as a separator too.
        """
        if path.is_absolute() or ".." in path.parts or "\\" in path.as_posix():
            raise TransportError(f"Path {path} is outside {self._where()}")
        return self.root / path

    def read_bytes(self, path: PurePosixPath) -> bytes:
        """A file's content, kept in memory so that no temporary file is left behind."""
        _log.debug("Reading %s", path)
        remote = self._inside(path).as_posix()
        buffer = io.BytesIO()  # in memory: no local or temporary file is written (D6)
        with _reporting(f"reading {path} from share {self.share}"):
            self._conn.retrieveFile(self.share, remote, buffer, timeout=self.timeout)
        return buffer.getvalue()

    def exists(self, path: PurePosixPath) -> bool:
        """Whether a file or folder exists, ignoring case. A failed listing is an error."""
        # Walks down the listings, because pysmb raises the same exception for "not found" and for
        # a real failure such as "access denied". A failed listing stays an error here.
        parent = ""
        for name in self._inside(path).parts:
            actual = _same_name(name, [e.filename for e in self._list(parent)])
            if actual is None:
                return False
            parent = f"{parent}{actual}/"
        return True

    def size(self, path: PurePosixPath) -> int:
        """A file's size in bytes, as the server reports it."""
        remote = self._inside(path).as_posix()
        with _reporting(f"getting the size of {path} on share {self.share}"):
            attributes = self._conn.getAttributes(self.share, remote, timeout=self.timeout)
            return int(attributes.file_size)

    def makedirs(self, path: PurePosixPath) -> None:
        """Create a folder and any missing parents, one level at a time.

        A folder whose name differs only in case counts as the same one, as it does on Samba.
        """
        # createDirectory isn't recursive, so each missing level is created in order (D4).
        parent = ""
        for name in self._inside(path).parts:
            actual = _same_name(name, self._list_dirs(parent))
            if actual is None:
                actual = name
                _log.debug("Creating folder %s%s", parent, name)
                with _reporting(f"creating folder {parent}{name} on share {self.share}"):
                    self._conn.createDirectory(self.share, f"{parent}{name}", timeout=self.timeout)
            parent = f"{parent}{actual}/"

    def upload(self, local: Path, remote: PurePosixPath) -> int:
        """Copy a file, replacing any file there. Returns the bytes the server says it stored."""
        inside = self._inside(remote).as_posix()
        with (
            _reporting(f"uploading {local} to {remote} on share {self.share}"),
            local.open("rb") as file,  # closed before this returns (D7)
        ):
            started = time.monotonic()
            written = int(self._conn.storeFile(self.share, inside, file, timeout=self.timeout))
            _log.debug(
                "Uploaded %s: %d bytes in %.3f s", remote, written, time.monotonic() - started
            )
            return written

    def _where(self) -> str:
        return self.share if self.root == SHARE_ROOT else f"{self.share}/{self.root}"

    def describe(self) -> str:
        """The share, host and port, for messages. The user isn't part of it."""
        return f"SMB share {self._where()} on {self.host}:{self.port}"

    def url(self) -> str:
        """The target as an ``smb://`` URL, for machines. It has no user or password."""
        return f"smb://{self.host}:{self.port}/{self._where()}"
