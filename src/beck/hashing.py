"""Hash files and scan the user's BIOS folder. It reads the local disk and prints nothing."""

import hashlib
import os
from pathlib import Path, PurePosixPath

from beck.models import LocalFile


def md5_file(path: Path) -> str:
    """A file's MD5 in lowercase, read in chunks. MD5 identifies files; it isn't for security."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()


def scan(folder: Path) -> list[LocalFile]:
    """Every non-hidden file under a folder, sorted by its path relative to that folder."""
    found = []

    for root, dirs, files in os.walk(folder):
        dirs[:] = [name for name in dirs if not name.startswith(".")]  # don't enter hidden folders
        for filename in files:
            if filename.startswith("."):
                continue
            path = Path(root, filename)
            found.append(
                LocalFile(
                    path=path,
                    relative=PurePosixPath(path.relative_to(folder).as_posix()),
                    md5=md5_file(path),
                    size=path.stat().st_size,
                )
            )

    return sorted(found, key=lambda item: item.relative.as_posix())
