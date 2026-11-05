"""Apply a Plan through a Transport. It never deletes or renames a local file (DEC-02)."""

from pathlib import PurePosixPath

from beck.errors import TransportError
from beck.models import ItemError, Plan, PlannedUpload, RunResult
from beck.transports.base import Transport


def execute(plan: Plan, transport: Transport, *, dry_run: bool) -> RunResult:
    """Create the folders, then upload. A failed item is recorded, and the run continues.

    In a dry run, nothing is written and every upload counts as skipped. An upload whose folder
    couldn't be created is skipped too. Only a TransportError counts as an item failure: anything
    else is a bug, and stops the run.
    """
    if dry_run:
        return RunResult(plan=plan, skipped=plan.uploads, dry_run=True)

    errors: list[ItemError] = []
    failed_folders: set[PurePosixPath] = set()
    for folder in plan.directories:
        try:
            transport.makedirs(folder)
        except TransportError as e:
            failed_folders.add(folder)
            errors.append(ItemError(item=folder.as_posix(), message=str(e)))

    completed: list[PlannedUpload] = []
    skipped: list[PlannedUpload] = []
    for upload in plan.uploads:
        if upload.target.parent in failed_folders:
            skipped.append(upload)
            continue
        try:
            transport.upload(upload.source.path, upload.target)
        except TransportError as e:
            errors.append(ItemError(item=upload.target.as_posix(), message=str(e)))
        else:
            completed.append(upload)

    return RunResult(
        plan=plan, completed=tuple(completed), skipped=tuple(skipped), errors=tuple(errors)
    )
