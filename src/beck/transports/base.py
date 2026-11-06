"""What a transport provides. Paths are relative to the target's BIOS root."""

from pathlib import Path, PurePosixPath
from typing import Protocol, Self


class Transport(Protocol):
    """A target BECK can read from and copy to. Use it in a ``with`` block.

    Failures raise TransportError. Nothing here deletes or renames a file.
    """

    def __enter__(self) -> Self:
        """Open the target."""

    def __exit__(self, *exc: object) -> None:
        """Close the target, even after an error."""

    def read_bytes(self, path: PurePosixPath) -> bytes:
        """A remote file's content."""

    def exists(self, path: PurePosixPath) -> bool:
        """Whether a remote file or folder exists."""

    def size(self, path: PurePosixPath) -> int:
        """A remote file's size in bytes."""

    def makedirs(self, path: PurePosixPath) -> None:
        """Create a remote folder and any missing parents. An existing folder is fine."""

    def upload(self, local: Path, remote: PurePosixPath) -> int:
        """Copy a local file to a remote path, replacing any file there. Returns bytes written."""

    def describe(self) -> str:
        """The target, for messages. Never includes a secret."""

    def url(self) -> str:
        """The target as a URL, for machines. Never includes a user name or a password."""
