"""Apply a Plan through a Transport. It never deletes or renames a local file (DEC-02)."""

from pathlib import PurePosixPath

from beck.errors import TransportError
from beck.models import ItemError, Plan, PlannedUpload, RunResult
from beck.transports.base import Transport


def execute(
    plan: Plan, transport: Transport, *, dry_run: bool, overwrite: bool = False
) -> RunResult:
    """Create the folders, then upload. A failed item is recorded, and the run continues.

    A file already on the target is kept, unless ``overwrite`` asks to replace it (DEC-61).

    A dry run only checks what's on the target, and every upload it would make counts as skipped.
    An upload whose folder couldn't be created is skipped too. Only a TransportError counts as an
    item failure: anything else is a bug, and stops the run.
    """
    errors: list[ItemError] = []
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
                transport.upload(upload.source.path, upload.target)
                completed.append(upload)
            if already_there:
                replaced.append(upload)
        except TransportError as e:
            errors.append(ItemError(item=upload.target.as_posix(), message=str(e)))

    return RunResult(
        plan=plan,
        completed=tuple(completed),
        skipped=tuple(skipped),
        errors=tuple(errors),
        dry_run=dry_run,
        kept=tuple(kept),
        replaced=tuple(replaced),
    )
