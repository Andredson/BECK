"""Apply a Plan through a Transport. Only this module deletes local files, and only on request."""

from pathlib import PurePosixPath

from beck.errors import TransportError
from beck.models import ItemError, LocalFile, Plan, PlannedUpload, RunResult
from beck.transports.base import Transport


def _changes_extension(upload: PlannedUpload) -> bool:
    """Whether the file goes up under another extension. Case alone isn't a different format."""
    return upload.source.relative.suffix.casefold() != upload.target.suffix.casefold()


def _size_matches(upload: PlannedUpload, transport: Transport, errors: list[ItemError]) -> bool:
    """Whether the file on the target has the local file's size. A failure counts as no."""
    item = upload.target.as_posix()
    try:
        size = transport.size(upload.target)
    except TransportError as e:
        errors.append(ItemError(item=item, message=str(e)))
        return False
    if size != upload.source.size:
        errors.append(
            ItemError(
                item=item,
                message=f"{item} has {size} bytes on the target, not {upload.source.size}, "
                f"so {upload.source.relative} wasn't deleted",
                code="size_mismatch",
            )
        )
        return False
    return True


def _files_to_move(
    plan: Plan,
    transport: Transport,
    *,
    dry_run: bool,
    done: set[PlannedUpload],
    errors: list[ItemError],
) -> list[LocalFile]:
    """Files uploaded to all their targets. In a real run, each remote size must match too."""
    files = []
    for file in dict.fromkeys(upload.source for upload in plan.uploads):
        uploads = [upload for upload in plan.uploads if upload.source == file]
        if not all(upload in done for upload in uploads):
            continue
        if dry_run or all(_size_matches(upload, transport, errors) for upload in uploads):
            files.append(file)
    return files


def _files_to_clean(plan: Plan) -> list[LocalFile]:
    """Files that matched nothing, except one that's valid for a target listed as incorrect."""
    valid_for_incorrect = {md5 for entry in plan.incorrect for md5 in entry.md5s}
    return [file for file in plan.unmatched if file.md5 not in valid_for_incorrect]


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
) -> RunResult:
    """Create the folders, upload, then delete what was asked. A failed item is recorded.

    A file already on the target is kept, unless ``overwrite`` asks to replace it (DEC-61).

    ``move`` deletes a local file once it's uploaded to all its targets and each remote size
    matches. ``clean_unmatched`` deletes local files that matched nothing, but not after any failure
    in this run. Without these flags, nothing local is ever deleted or renamed (DEC-02).

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
                transport.upload(upload.source.path, upload.target)
                completed.append(upload)
            if already_there:
                replaced.append(upload)
        except TransportError as e:
            errors.append(ItemError(item=upload.target.as_posix(), message=str(e)))

    done = skipped if dry_run else completed
    to_delete: list[LocalFile] = []
    if move:
        to_delete += _files_to_move(plan, transport, dry_run=dry_run, done=set(done), errors=errors)
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
