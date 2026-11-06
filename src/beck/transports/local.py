"""A folder on disk: a mounted SD card or USB drive, a run on the device itself, or a test."""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Self

from beck.errors import TransportError


@contextmanager
def _reporting(action: str, path: object) -> Iterator[None]:
    """Turn an OSError into a TransportError with a readable message."""
    try:
        yield
    except OSError as e:
        raise TransportError(f"Error {action} {path}: {e}") from e


class LocalTransport:
    """Reads and copies files under one folder, and refuses any path that resolves outside it."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def __enter__(self) -> Self:
        if not self.root.is_dir():
            raise TransportError(f"Folder {self.root} doesn't exist")
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def _resolve(self, path: PurePosixPath) -> Path:
        # resolve() follows "..", absolute paths and symlinks, so all of them are checked here.
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root):
            raise TransportError(f"Path {path} is outside {self.root}")
        return resolved

    def read_bytes(self, path: PurePosixPath) -> bytes:
        with _reporting("reading", path):
            return self._resolve(path).read_bytes()

    def exists(self, path: PurePosixPath) -> bool:
        return self._resolve(path).exists()

    def size(self, path: PurePosixPath) -> int:
        with _reporting("getting the size of", path):
            return self._resolve(path).stat().st_size

    def makedirs(self, path: PurePosixPath) -> None:
        with _reporting("creating folder", path):
            self._resolve(path).mkdir(parents=True, exist_ok=True)

    def upload(self, local: Path, remote: PurePosixPath) -> int:
        with _reporting(f"copying {local} to", remote):
            target = self._resolve(remote)
            shutil.copyfile(local, target)
            return target.stat().st_size

    def describe(self) -> str:
        return f"local folder {self.root}"

    def url(self) -> str:
        return self.root.as_uri()
