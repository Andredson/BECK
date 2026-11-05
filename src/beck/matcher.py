"""Decide which local file fills which target. Pure: no I/O, and nothing is uploaded here."""

from collections.abc import Sequence
from pathlib import PurePosixPath

from beck.models import Duplicate, LocalFile, MissingBios, Plan, PlannedUpload


def _path(file: LocalFile) -> str:
    # As text, like stage 03: "first by path" decides which file wins, and PurePosixPath compares
    # folder by folder, which orders a/x and a-b/x the other way round.
    return file.relative.as_posix()


def _entry_order(entry: MissingBios) -> tuple[str, str, str, list[str]]:
    return entry.target.as_posix(), str(entry.system), str(entry.required), sorted(entry.md5s)


def plan(
    missing: Sequence[MissingBios], local: Sequence[LocalFile], *, replace_incorrect: bool = False
) -> Plan:
    """Build the plan for these report entries and local files. Input order doesn't matter.

    One file can fill many targets, and each target is filled once. A file already named like a
    target gets that target first: otherwise ``falcon.img``, which sorts earlier, would take the
    place of the user's real ``tos.img``. Remaining targets go to the first file by path. Identical
    copies upload once, and the copy named like a target is the one uploaded.

    A target that's incorrect on the device isn't uploaded to (DEC-54), even if another entry lists
    it as missing: it goes in ``Plan.incorrect``, and files that fit it stay unmatched. With
    ``replace_incorrect`` (DEC-61), those targets are filled like any other, and ``Plan.incorrect``
    has only the ones with no valid local file.
    """
    ordered = sorted(missing, key=_entry_order)
    incorrect = [entry for entry in ordered if entry.incorrect]
    kept_targets = {entry.target for entry in incorrect}
    entries = ordered if replace_incorrect else [e for e in ordered if e.target not in kept_targets]
    entries_by_md5: dict[str, list[MissingBios]] = {}
    for entry in entries:
        for md5 in entry.md5s:
            entries_by_md5.setdefault(md5, []).append(entry)

    def named_like_a_target(file: LocalFile) -> bool:
        return any(entry.name == file.relative.name for entry in entries_by_md5[file.md5])

    matching = [file for file in local if file.md5 in entries_by_md5]

    chosen: dict[str, LocalFile] = {}
    for file in sorted(matching, key=lambda file: (not named_like_a_target(file), _path(file))):
        chosen.setdefault(file.md5, file)

    uploads: dict[PurePosixPath, PlannedUpload] = {}
    for own_name_only in (True, False):
        for file in sorted(chosen.values(), key=_path):
            for entry in entries_by_md5[file.md5]:
                if entry.name == file.relative.name or not own_name_only:
                    uploads.setdefault(entry.target, PlannedUpload(file, entry.target, entry))

    sources = {upload.source for upload in uploads.values()}
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
        unmatched=tuple(file for file in local if file.md5 not in entries_by_md5),
        already_filled=tuple(file for file in chosen.values() if file not in sources),
        still_missing=tuple(
            entry
            for entry in entries
            if entry.target not in uploads and entry.target not in kept_targets
        ),
        incorrect=tuple(entry for entry in incorrect if entry.target not in uploads),
    )
