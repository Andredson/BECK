# SPDX-License-Identifier: GPL-3.0-only
"""Decide which local file fills which target. Pure: no I/O, and nothing is uploaded here."""

from collections.abc import Sequence
from pathlib import PurePosixPath

from beck.models import Duplicate, ItemError, LocalFile, MissingBios, Plan, PlannedUpload


def _path(file: LocalFile) -> tuple[str, str]:
    # As text, like stage 03: "first by path" decides which file wins, and PurePosixPath compares
    # folder by folder, which orders a/x and a-b/x the other way round.
    return file.sort_key()


def _is_zip_target(entry: MissingBios) -> bool:
    return entry.target.suffix.casefold() == ".zip"


def _fits(file: LocalFile, entry: MissingBios) -> bool:
    """Whether the file fills this target, checked the way Recalbox checks it.

    Recalbox hashes a ``.zip`` target by the files inside it (DEC-74, DEC-78), so only a zip archive
    fills one: by that contents MD5, or by its own MD5 as before. Any other target is hashed whole,
    so a file, a zip as a whole, or a member of a zip fills it by its own MD5.
    """
    if _is_zip_target(entry):
        return file.is_zip and bool({file.md5, file.contents_md5} & entry.md5s)
    return file.md5 in entry.md5s


def _not_a_zip(file: LocalFile, entry: MissingBios) -> bool:
    """A file that isn't a zip archive, with an MD5 a ``.zip`` target lists: it can't fill it."""
    return _is_zip_target(entry) and not file.is_zip and file.md5 in entry.md5s


def _entry_order(entry: MissingBios) -> tuple[str, str, str, list[str]]:
    return entry.target.as_posix(), str(entry.system), str(entry.required), sorted(entry.md5s)


def plan(
    missing: Sequence[MissingBios],
    local: Sequence[LocalFile],
    *,
    replace_incorrect: bool = False,
    rejected: Sequence[ItemError] = (),
) -> Plan:
    """Build the plan for these report entries and local files. Input order doesn't matter.

    One file can fill many targets, and each target is filled once. A file already named like a
    target gets that target first: otherwise ``falcon.img``, which sorts earlier, would take the
    place of the user's real ``tos.img``. Remaining targets go to the first file by path. Identical
    copies upload once, and the copy named like a target is the one uploaded.

    A target that's incorrect on the device isn't uploaded to (DEC-54), even if another entry lists
    it as missing: it goes in ``Plan.incorrect``, and files that fit it stay unmatched. With
    ``replace_incorrect`` (DEC-61), those targets are filled like any other, and ``Plan.incorrect``
    has only the ones with no valid local file. ``rejected`` is what the report held that isn't safe
    to act on: it's only carried along, so that the run reports it, as failed items.

    A file that isn't a zip archive never fills a ``.zip`` target: the target stays missing, and
    ``Plan.not_a_zip`` says which file matched it. A member of a zip archive is matched like a file,
    but it's never unmatched: an archive is, if neither it nor any of its members matched.
    """
    ordered = sorted(missing, key=_entry_order)
    incorrect = [entry for entry in ordered if entry.incorrect]
    kept_targets = {entry.target for entry in incorrect}
    entries = ordered if replace_incorrect else [e for e in ordered if e.target not in kept_targets]
    candidates = {
        file: [e for e in entries if _fits(file, e) or _not_a_zip(file, e)] for file in local
    }

    def named_like_a_target(file: LocalFile) -> bool:
        return any(entry.name == file.name for entry in candidates[file])

    matching = [file for file in local if candidates[file]]

    chosen: dict[str, LocalFile] = {}
    in_order = sorted(
        matching,
        key=lambda file: (not named_like_a_target(file), file.member is not None, _path(file)),
    )
    for file in in_order:
        chosen.setdefault(file.md5, file)

    uploads: dict[PurePosixPath, PlannedUpload] = {}
    for own_name_only in (True, False):
        for file in sorted(chosen.values(), key=_path):
            for entry in candidates[file]:
                if (entry.name == file.name or not own_name_only) and _fits(file, entry):
                    uploads.setdefault(entry.target, PlannedUpload(file, entry.target, entry))

    not_a_zip: dict[PurePosixPath, PlannedUpload] = {}
    for file in sorted(chosen.values(), key=_path):
        for entry in candidates[file]:
            if _not_a_zip(file, entry) and entry.target not in uploads:
                not_a_zip.setdefault(entry.target, PlannedUpload(file, entry.target, entry))

    # An archive with a member that fits a target kept as incorrect isn't unmatched either, so that
    # --clean-unmatched can't delete it (DEC-59).
    valid_for_incorrect = {md5 for entry in incorrect for md5 in entry.md5s}
    used_archives = {file.path for file in matching} | {
        file.path for file in local if file.member is not None and file.md5 in valid_for_incorrect
    }

    sources = {upload.source for upload in uploads.values()}
    held_back = {upload.source for upload in not_a_zip.values()}
    return Plan(
        uploads=tuple(uploads.values()),
        directories=tuple(
            {target.parent for target in uploads if target.parent != PurePosixPath(".")}
        ),
        duplicates=tuple(
            Duplicate(file=file, of=chosen[file.md5])
            for file in matching
            if file != chosen[file.md5]
        ),
        unmatched=tuple(
            file for file in local if file.member is None and file.path not in used_archives
        ),
        already_filled=tuple(
            file for file in chosen.values() if file not in sources and file not in held_back
        ),
        still_missing=tuple(
            entry
            for entry in entries
            if entry.target not in uploads and entry.target not in kept_targets
        ),
        incorrect=tuple(entry for entry in incorrect if entry.target not in uploads),
        rejected=tuple(rejected),
        not_a_zip=tuple(not_a_zip.values()),
    )
