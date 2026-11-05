"""Hash files and scan the user's BIOS folder. It reads the local disk and prints nothing."""

import hashlib
import os
from pathlib import Path, PurePosixPath

from beck.models import LocalFile, ScanResult, Unreadable


def md5_file(path: Path) -> str:
    """A file's MD5 in lowercase, read in chunks. MD5 identifies files; it isn't for security."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()


def _describe_file(path: Path, relative: PurePosixPath) -> LocalFile | Unreadable:
    # Checked before opening it, because opening a named pipe would wait forever.
    try:
        if not path.is_file():
            kind = "broken symlink" if path.is_symlink() else "not a regular file"
            return Unreadable(relative=relative, reason=kind)
        return LocalFile(path=path, relative=relative, md5=md5_file(path), size=path.stat().st_size)
    except OSError as e:
        return Unreadable(relative=relative, reason=e.strerror or str(e))


def scan(folder: Path) -> ScanResult:
    """Every non-hidden file under a folder, sorted by its path relative to that folder.

    A file or sub-folder that can't be read is recorded, and the scan carries on. A folder that
    doesn't exist has nothing in it.
    """
    found: list[LocalFile | Unreadable] = []

    def unreadable_folder(error: OSError) -> None:
        if not (isinstance(error, FileNotFoundError) and Path(str(error.filename)) == folder):
            relative = Path(str(error.filename)).relative_to(folder).as_posix()
            found.append(
                Unreadable(relative=PurePosixPath(relative), reason=error.strerror or str(error))
            )

    for root, dirs, files in os.walk(folder, onerror=unreadable_folder):
        dirs[:] = [name for name in dirs if not name.startswith(".")]  # don't enter hidden folders
        for filename in files:
            if filename.startswith("."):
                continue
            path = Path(root, filename)
            found.append(_describe_file(path, PurePosixPath(path.relative_to(folder).as_posix())))

    in_order = sorted(found, key=lambda item: item.relative.as_posix())
    return ScanResult(
        files=tuple(item for item in in_order if isinstance(item, LocalFile)),
        unreadable=tuple(item for item in in_order if isinstance(item, Unreadable)),
    )
