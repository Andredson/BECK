"""A folder on disk: a mounted SD card or USB drive, a run on the device itself, or a test."""

import logging
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Self

from beck.errors import TransportError

_log = logging.getLogger(__name__)


@contextmanager
def _reporting(action: str, path: object) -> Iterator[None]:
    """Turn a failure into a TransportError with a readable message.

    Python before 3.13 raises RuntimeError when a path resolves through a symlink loop.
    """
    try:
        yield
    except (OSError, RuntimeError) as e:
        raise TransportError(f"Error {action} {path}: {e}") from e


class LocalTransport:
    """Reads and copies files under one folder, and refuses any path that resolves outside it."""

    def __init__(self, root: Path) -> None:
        """Use this folder. It's resolved now, because every later path is compared with it."""
        with _reporting("finding folder", root):
            self.root = root.resolve()

    def __enter__(self) -> Self:
        """Check the folder: a missing one is a failed target, not an empty one."""
        if not self.root.is_dir():
            raise TransportError(f"Folder {self.root} doesn't exist")
        _log.debug("Using folder %s", self.root)
        return self

    def __exit__(self, *exc: object) -> None:
        """Nothing to do: no connection stays open."""
        pass

    def _resolve(self, path: PurePosixPath) -> Path:
        # resolve() follows "..", absolute paths and symlinks, so all of them are checked here.
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root):
            raise TransportError(f"Path {path} is outside {self.root}")
        return resolved

    def read_bytes(self, path: PurePosixPath) -> bytes:
        """A file's content. A path that resolves outside the folder is an error."""
        with _reporting("reading", path):
            return self._resolve(path).read_bytes()

    def exists(self, path: PurePosixPath) -> bool:
        """Whether a file or folder exists. A failure, such as a denied read, is an error."""
        # Not Path.exists(): from Python 3.14 it answers False for any failure, so a folder BECK
        # can't read would look like one with nothing in it.
        with _reporting("checking", path):
            try:
                self._resolve(path).stat()
            except (FileNotFoundError, NotADirectoryError):
                return False
            return True

    def size(self, path: PurePosixPath) -> int:
        """A file's size in bytes, which is how an upload is checked once it's copied."""
        with _reporting("getting the size of", path):
            return self._resolve(path).stat().st_size

    def makedirs(self, path: PurePosixPath) -> None:
        """Create a folder and any missing parents. An existing folder is fine."""
        with _reporting("creating folder", path):
            self._resolve(path).mkdir(parents=True, exist_ok=True)

    def upload(self, local: Path, remote: PurePosixPath) -> int:
        """Copy a file, replacing any file there. Returns the size of the copy."""
        with _reporting(f"copying {local} to", remote):
            target = self._resolve(remote)
            started = time.monotonic()
            shutil.copyfile(local, target)
            size = target.stat().st_size
            _log.debug("Copied %s: %d bytes in %.3f s", remote, size, time.monotonic() - started)
            return size

    def describe(self) -> str:
        """The folder, for messages."""
        return f"local folder {self.root}"

    def url(self) -> str:
        """The folder as a ``file://`` URL, for machines."""
        return self.root.as_uri()
