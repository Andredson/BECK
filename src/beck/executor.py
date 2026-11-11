# SPDX-License-Identifier: GPL-3.0-only
"""Apply a Plan through a Transport. Only this module deletes local files, and only on request."""

import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from beck.errors import TransportError
from beck.hashing import ZIP_ERRORS, md5_bytes
from beck.models import ItemError, LocalFile, Plan, PlannedUpload, RunResult
from beck.transports.base import Transport


def _changes_extension(upload: PlannedUpload) -> bool:
    """Whether the file goes up under another extension. Case alone isn't a different format."""
    return PurePosixPath(upload.source.name).suffix.casefold() != upload.target.suffix.casefold()


def _upload(transport: Transport, upload: PlannedUpload) -> None:
    """Copy the file, or a member of a zip archive through a temporary copy (DEC-78).

    The temporary folder goes away with the ``with``. A member is copied up to the size the scan
    found, and one byte more, so that an archive changed since then can't fill the disk.
    """
    source = upload.source
    if source.member is None:
        transport.upload(source.path, upload.target)
        return
    shown = f"{source.member} in {source.relative}"
    with tempfile.TemporaryDirectory(prefix="beck-") as folder:
        extracted = Path(folder) / "member"
        try:
            with (
                zipfile.ZipFile(source.path) as archive,
                archive.open(source.member) as member,
                extracted.open("wb") as out,
            ):
                out.write(member.read(source.size + 1))
        except (*ZIP_ERRORS, KeyError) as e:  # KeyError: the member is gone since the scan
            raise TransportError(f"Couldn't read {shown}: {e}") from e
        transport.upload(extracted, upload.target)


def _damage(upload: PlannedUpload, transport: Transport, *, verify: bool) -> ItemError | None:
    """What's wrong with what arrived, if anything: its size, and with ``verify`` its MD5 too.

    It compares with what the scan found, because the local file could have changed since. A
    damaged file stays on the target, and a later run would keep it, so the message says what to do.
    """
    item = upload.target.as_posix()
    size = transport.size(upload.target)
    if size != upload.source.size:
        return ItemError(
            item=item,
            message=f"{item} has {size} bytes on the target, not {upload.source.size}. "
            "To try again, use --overwrite.",
            code="size_mismatch",
        )
    if verify and md5_bytes(transport.read_bytes(upload.target)) != upload.source.md5:
        return ItemError(
            item=item,
            message=f"{item} has a different MD5 on the target. To try again, use --overwrite.",
            code="md5_mismatch",
        )
    return None


def _files_to_move(plan: Plan, done: set[PlannedUpload]) -> list[LocalFile]:
    """Files uploaded to all their targets. What's done has already been checked on the target."""
    # A member is never deleted on its own, and its archive only once the archive itself was
    # uploaded, and every upload from it, member or not, is done.
    files = dict.fromkeys(upload.source for upload in plan.uploads if upload.source.member is None)
    return [
        file
        for file in files
        if all(upload in done for upload in plan.uploads if upload.source.path == file.path)
    ]


def _files_to_clean(plan: Plan) -> list[LocalFile]:
    """Files that matched nothing, except one that's valid for a target listed as incorrect."""
    valid_for_incorrect = {md5 for entry in plan.incorrect for md5 in entry.md5s}
    return [
        file for file in plan.unmatched if not {file.md5, file.contents_md5} & valid_for_incorrect
    ]


def _delete(file: LocalFile, errors: list[ItemError]) -> bool:
    try:
        file.path.unlink()
    except OSError as e:
        item = file.relative.as_posix()
        message = f"Couldn't delete {item}: {e.strerror}"
        errors.append(ItemError(item=item, message=message, code="delete_failed"))
        return False
    return True


def execute(
    plan: Plan,
    transport: Transport,
    *,
    dry_run: bool,
    overwrite: bool = False,
    move: bool = False,
    clean_unmatched: bool = False,
    verify: bool = False,
) -> RunResult:
    """Create the folders, upload, then delete what was asked. A failed item is recorded.

    A file already on the target is kept, unless ``overwrite`` asks to replace it (DEC-61).

    Each upload is checked on the target: its size always, and with ``verify`` its MD5 too, by
    reading it back. One that doesn't match counts as failed.

    ``move`` deletes a local file once it's uploaded to all its targets. ``clean_unmatched`` deletes
    local files that matched nothing, but not after any failure in this run. Without these flags,
    nothing local is ever deleted or renamed (DEC-02).

    An upload that changes the file's extension goes ahead, and is listed in ``extension_changes``:
    the MD5 is valid, but an emulator may not be able to read the file.

    A dry run only checks what's on the target: every upload it would make counts as skipped, and
    ``deleted`` has what it would delete. An upload whose folder couldn't be created is skipped too.
    Only a TransportError counts as an item failure: anything else is a bug, and stops the run.
    """
    errors = list(plan.rejected)  # so ``clean_unmatched`` stops: the report wasn't fully read
    failed_folders: set[PurePosixPath] = set()
    if not dry_run:
        for folder in plan.directories:
            try:
                transport.makedirs(folder)
            except TransportError as e:
                failed_folders.add(folder)
                errors.append(ItemError(item=folder.as_posix(), message=str(e)))

    completed: list[PlannedUpload] = []
    skipped: list[PlannedUpload] = []
    kept: list[PlannedUpload] = []
    replaced: list[PlannedUpload] = []
    for upload in plan.uploads:
        if upload.target.parent in failed_folders:
            skipped.append(upload)
            continue
        try:
            already_there = transport.exists(upload.target)
            if already_there and not overwrite:
                kept.append(upload)
                continue
            if dry_run:
                skipped.append(upload)
            else:
                _upload(transport, upload)
                damage = _damage(upload, transport, verify=verify)
                if damage is not None:
                    errors.append(damage)
                    continue
                completed.append(upload)
            if already_there:
                replaced.append(upload)
        except TransportError as e:
            errors.append(ItemError(item=upload.target.as_posix(), message=str(e)))

    done = skipped if dry_run else completed
    to_delete: list[LocalFile] = []
    if move:
        to_delete += _files_to_move(plan, set(done))
    if clean_unmatched and not errors:
        to_delete += _files_to_clean(plan)
    deleted = [file for file in to_delete if dry_run or _delete(file, errors)]

    return RunResult(
        plan=plan,
        completed=tuple(completed),
        skipped=tuple(skipped),
        errors=tuple(errors),
        dry_run=dry_run,
        kept=tuple(kept),
        replaced=tuple(replaced),
        deleted=tuple(deleted),
        extension_changes=tuple(upload for upload in done if _changes_extension(upload)),
    )
