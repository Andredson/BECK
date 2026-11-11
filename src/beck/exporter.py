# SPDX-License-Identifier: GPL-3.0-only
"""Copy the BIOS files on a target to a local folder: ``beck export`` (DEC-57, DEC-60).

It only reads the target, and only creates local files: a file that's already there is kept as it
is. Nothing here deletes or renames anything.
"""

import logging
import os
import time
from pathlib import Path

from beck.errors import TransportError, UsageError
from beck.models import ExportResult, ItemError, RemoteFile
from beck.transports.base import Transport

EXTENSIONS = (".rom", ".bin")  # DEC-60, in any case

_log = logging.getLogger(__name__)


class _Refused(Exception):
    """A file that can't be written where it belongs, with the ItemError that says why."""

    def __init__(self, error: ItemError) -> None:
        super().__init__(error.message)
        self.error = error


def is_exported(file: RemoteFile) -> bool:
    """Whether export copies this file: a ``.rom`` or ``.bin`` file, in any case (DEC-60)."""
    return file.path.suffix.casefold() in EXTENSIONS


def _local(destination: Path, file: RemoteFile) -> Path:
    return destination.joinpath(*file.path.parts)


def _folder_for(destination: Path, file: RemoteFile) -> Path:
    """Create the file's folders, one level at a time, without following a link.

    A link could lead out of the destination, and the target's names could be anything.
    """
    item = file.path.as_posix()
    folder = destination
    for part in file.path.parent.parts:
        folder = folder / part
        if folder.is_symlink():
            message = f"Refused {item}: {folder} is a link, and export doesn't follow links"
            raise _Refused(ItemError(item=item, message=message, code="unsafe_path"))
        try:
            folder.mkdir(exist_ok=True)
        except OSError as e:
            message = f"Couldn't create the folder {folder}: {e.strerror}"
            raise _Refused(ItemError(item=item, message=message, code="write_failed")) from e
    return folder


def _copy(transport: Transport, destination: Path, file: RemoteFile) -> bool:
    """Copy one file. False if a local file appeared there meanwhile, which is then kept.

    The whole file is read before anything is written, so a failed read leaves nothing behind.
    """
    item = file.path.as_posix()
    data = transport.read_bytes(file.path)
    if len(data) != file.size:
        message = (
            f"{item} has {len(data)} bytes when read, but the target listed {file.size}. "
            "Nothing was written."
        )
        raise _Refused(ItemError(item=item, message=message, code="size_mismatch"))
    local = _folder_for(destination, file) / file.path.name
    try:
        out = local.open("xb")  # "x" fails if anything is there, even a link: nothing is replaced
    except FileExistsError:
        return False
    except OSError as e:
        message = f"Couldn't write {local}: {e.strerror}"
        raise _Refused(ItemError(item=item, message=message, code="write_failed")) from e
    try:
        with out:
            out.write(data)
    except OSError as e:
        message = (
            f"Couldn't write {local}: {e.strerror}. Part of it may be there: delete it before "
            "you export again, or export keeps it."
        )
        raise _Refused(ItemError(item=item, message=message, code="write_failed")) from e
    return True


def export(transport: Transport, destination: Path, *, dry_run: bool) -> ExportResult:
    """Copy each ``.rom`` and ``.bin`` file on the target to ``destination``, in its folders.

    A local file that's already there is kept, and listed in ``existing``. One failed file is
    recorded, and the run carries on. A dry run lists the target and checks what's here, and writes
    nothing, not even ``destination``. A target that can't be listed raises TransportError.
    """
    started = time.monotonic()
    listed = transport.list_files()
    chosen = [file for file in listed if is_exported(file)]
    _log.debug("Listed %d files on the target, %d to export", len(listed), len(chosen))
    if not dry_run:
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise UsageError(f"Can't create the folder {destination}: {e.strerror}") from e

    copied: list[RemoteFile] = []
    planned: list[RemoteFile] = []
    existing: list[RemoteFile] = []
    failed: list[RemoteFile] = []
    errors: list[ItemError] = []
    for file in chosen:
        if os.path.lexists(_local(destination, file)):  # lexists: a link is something there too
            existing.append(file)
        elif dry_run:
            planned.append(file)
        else:
            try:
                (copied if _copy(transport, destination, file) else existing).append(file)
            except TransportError as e:
                failed.append(file)
                errors.append(ItemError(item=file.path.as_posix(), message=str(e)))
            except _Refused as e:
                failed.append(file)
                errors.append(e.error)

    _log.debug(
        "Exported in %.3f s: %d copied, %d already here, %d failed",
        time.monotonic() - started,
        len(copied),
        len(existing),
        len(failed),
    )
    return ExportResult(
        destination=destination,
        copied=tuple(copied),
        planned=tuple(planned),
        existing=tuple(existing),
        failed=tuple(failed),
        errors=tuple(errors),
        on_target=len(listed),
        dry_run=dry_run,
    )
