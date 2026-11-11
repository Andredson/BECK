# SPDX-License-Identifier: GPL-3.0-only
"""Hash files and scan the user's BIOS folder. It reads the local disk and prints nothing."""

import hashlib
import os
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from beck.models import LocalFile, ScanResult, Unreadable

# Limits on each zip archive, against a zip bomb (DEC-78). Real BIOS archives are a few MB.
MAX_MEMBERS = 1000
MAX_UNPACKED = 512 * 1024 * 1024  # bytes, all members together
_CHUNK = 1024 * 1024
_UTF8_NAME = 0x800  # zip flag: the name is UTF-8
_ENCRYPTED = 0x1  # zip flag
ZIP_ERRORS = (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError, zlib.error)


class _ZipLimit(Exception):
    """An archive over the limits: its members aren't read."""


def md5_file(path: Path) -> str:
    """A file's MD5 in lowercase, read in chunks. MD5 identifies files; it isn't for security."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()


def md5_bytes(data: bytes) -> str:
    """The MD5 of some bytes, in the same form as ``md5_file``."""
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _name_key(info: zipfile.ZipInfo) -> bytes:
    """A member's name as Recalbox sorts it: libzip's guess, UTF-8 if it is UTF-8, else CP437."""
    if info.flag_bits & _UTF8_NAME:
        return info.orig_filename.encode("utf-8")
    raw = info.orig_filename.encode("cp437")  # Python read it as CP437, which keeps every byte
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return info.orig_filename.encode("utf-8")
    return raw


def _read_zip(path: Path) -> tuple[str, list[tuple[str, str, int]]]:
    """A zip's contents MD5, and each member's name, MD5 and size.

    The contents MD5 is what Recalbox checks a ``.zip`` target with: the MD5 of every member's
    bytes, in the order of their names, sorted byte by byte (``Zip::Md5Composite`` in Recalbox's
    EmulationStation). A folder adds nothing, and Recalbox can't open an encrypted member, so that
    adds nothing either. Raises ``_ZipLimit``, or one of ``ZIP_ERRORS``.
    """
    contents = hashlib.md5(usedforsecurity=False)
    members = []
    unpacked = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise _ZipLimit(f"it has more than {MAX_MEMBERS} members")
        for info in sorted(infos, key=_name_key):
            if info.is_dir() or info.flag_bits & _ENCRYPTED:
                continue
            member = hashlib.md5(usedforsecurity=False)
            size = 0
            with archive.open(info) as stream:
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    unpacked += len(chunk)
                    if unpacked > MAX_UNPACKED:  # counted as read: a header can lie
                        raise _ZipLimit(f"it unpacks to more than {MAX_UNPACKED // 2**20} MiB")
                    member.update(chunk)
                    contents.update(chunk)
            members.append((info.filename, member.hexdigest(), size))
    return contents.hexdigest(), members


def _describe_zip(archive: LocalFile) -> list[LocalFile | Unreadable]:
    """The archive with its contents MD5, and its members. If they can't be read, why not."""
    try:
        contents_md5, members = _read_zip(archive.path)
    except (_ZipLimit, *ZIP_ERRORS) as e:
        reason = f"its members weren't read, because {e}"
        return [archive, Unreadable(relative=archive.relative, reason=reason)]
    found: list[LocalFile | Unreadable] = [
        LocalFile(
            path=archive.path,
            relative=archive.relative,
            md5=archive.md5,
            size=archive.size,
            is_zip=True,
            contents_md5=contents_md5,
        )
    ]
    for name, md5, size in members:
        found.append(
            LocalFile(path=archive.path, relative=archive.relative, md5=md5, size=size, member=name)
        )
    return found


def _describe_file(path: Path, relative: PurePosixPath) -> list[LocalFile | Unreadable]:
    """A file, and if it's a zip archive, its members too (DEC-78)."""
    # Checked before opening it, because opening a named pipe would wait forever.
    try:
        if not path.is_file():
            kind = "broken symlink" if path.is_symlink() else "not a regular file"
            return [Unreadable(relative=relative, reason=kind)]
        file = LocalFile(
            path=path,
            relative=relative,
            md5=md5_file(path),
            size=path.stat().st_size,
            is_zip=zipfile.is_zipfile(path),
        )
    except OSError as e:
        return [Unreadable(relative=relative, reason=e.strerror or str(e))]
    return _describe_zip(file) if file.is_zip else [file]


def scan(folder: Path, on_file: Callable[[int], None] | None = None) -> ScanResult:
    """Every non-hidden file under a folder, sorted by its path relative to that folder.

    A file or sub-folder that can't be read is recorded, and the scan carries on. A folder that
    doesn't exist has nothing in it. ``on_file`` gets the count so far, after each file.
    """
    found: list[LocalFile | Unreadable] = []
    counted = 0

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
            found += _describe_file(path, PurePosixPath(path.relative_to(folder).as_posix()))
            counted += 1
            if on_file is not None:
                on_file(counted)

    def order(item: LocalFile | Unreadable) -> tuple[str, str]:
        return item.sort_key() if isinstance(item, LocalFile) else (item.relative.as_posix(), "")

    in_order = sorted(found, key=order)
    return ScanResult(
        files=tuple(item for item in in_order if isinstance(item, LocalFile)),
        unreadable=tuple(item for item in in_order if isinstance(item, Unreadable)),
    )
