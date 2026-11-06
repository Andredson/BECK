"""``--json``: one document on stdout for each run. A public contract, see docs/json-output.md.

Within ``schema_version`` 1, fields are only added. Don't rename or remove one, or change what one
means, without asking the owner: that needs ``schema_version`` 2.
"""

import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, TextIO

from beck import __version__
from beck.errors import BeckError, UsageError
from beck.models import (
    ItemError,
    LocalFile,
    MissingBios,
    Plan,
    RunResult,
    ScanResult,
    Unreadable,
)
from beck.output import (
    distinct_targets,
    extension_warning,
    print_safely,
    upload_errors,
    upload_status,
)

SCHEMA_VERSION = 1
INTERNAL_ERROR = {
    "code": "internal",
    "message": "Unexpected error. The details are on stderr.",
    "item": None,
}


def _write(document: dict[str, Any], stream: TextIO) -> None:
    # ensure_ascii, the default: a file name that isn't valid UTF-8 can't break the output.
    print_safely(json.dumps(document, indent=2), stream)


def _header(command: str | None, *, ok: bool) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "beck_version": __version__,
        "command": command,
        "ok": ok,
    }


def write_rejected_command(message: str, stream: TextIO | None = None) -> None:
    """The command line itself was wrong, so no command ran. This has only the common fields."""
    document = _header(None, ok=False)
    document["errors"] = [{"code": UsageError.code, "message": message, "item": None}]
    _write(document, sys.stdout if stream is None else stream)


def _required(entries: list[MissingBios]) -> bool | None:
    """Required if any entry says so. None if none does and one doesn't say."""
    if any(entry.required for entry in entries):
        return True
    return None if any(entry.required is None for entry in entries) else False


def _by_target(entries: Iterable[MissingBios]) -> dict[str, list[MissingBios]]:
    grouped: dict[str, list[MissingBios]] = {}
    for entry in entries:
        grouped.setdefault(entry.target.as_posix(), []).append(entry)
    return dict(sorted(grouped.items()))


def _missing_items(entries: Iterable[MissingBios]) -> list[dict[str, Any]]:
    """One item per target: a file listed in several systems is still one file to find."""
    return [
        {
            "name": group[0].name,
            "target": target,
            "md5s": sorted({md5 for entry in group for md5 in entry.md5s}),
            "required": _required(group),
        }
        for target, group in _by_target(entries).items()
    ]


def _incorrect_items(entries: Sequence[MissingBios]) -> list[dict[str, Any]]:
    current = {e.target.as_posix(): e.current_md5 for e in entries if e.current_md5}
    return [
        {**item, "current_md5": current.get(item["target"])} for item in _missing_items(entries)
    ]


def _unreadable_items(items: Iterable[Unreadable]) -> list[dict[str, str]]:
    return [{"path": item.relative.as_posix(), "reason": item.reason} for item in items]


def _file_items(files: Iterable[LocalFile]) -> list[dict[str, Any]]:
    return [
        {"path": file.relative.as_posix(), "md5": file.md5, "size": file.size} for file in files
    ]


def _error_items(errors: Iterable[ItemError]) -> list[dict[str, str]]:
    return [{"code": error.code, "message": error.message, "item": error.item} for error in errors]


def _upload_items(result: RunResult) -> list[dict[str, Any]]:
    errors = upload_errors(result)
    return [
        {
            "source": upload.source.relative.as_posix(),
            "target": upload.target.as_posix(),
            "md5": upload.source.md5,
            "status": upload_status(upload, result),
            "replaces": upload in result.replaced,
            "error": errors.get(upload.target.as_posix()),
            "warning": (extension_warning(upload) if upload in result.extension_changes else None),
        }
        for upload in result.plan.uploads
    ]


class JsonRenderer:
    """Collects what a run finds, and writes one document when it ends. Nothing here decides."""

    def __init__(
        self, command: str, *, frontend: str, dry_run: bool, stream: TextIO | None = None
    ) -> None:
        self.command = command
        self.frontend = frontend
        self.dry_run = dry_run
        self.stream = sys.stdout if stream is None else stream
        self.target: str | None = None
        self.files_scanned = 0
        self.unreadable_items: tuple[Unreadable, ...] = ()

    def can_ask(self) -> bool:
        """Never: a consumer can't hang on a question, or confirm one by accident."""
        return False

    def confirm_deletion(self, preview: RunResult) -> bool:
        """Never reached, because this renderer can't ask. If it were, the answer is no."""
        return False

    def opened(self, target: str) -> None:
        self.target = target

    def uses_frontend(self, name: str) -> None:
        self.frontend = name

    def missing_count(self, count: int) -> None:
        """Nothing yet: the document has it at the end."""

    def nothing_missing(self) -> None:
        """Nothing yet: the document has it at the end."""

    def files_found(self, count: int) -> None:
        self.files_scanned = count

    def no_files(self, folder: Path) -> None:
        """Nothing yet: the document has it at the end."""

    def hashing(self, count: int) -> None:
        """Nothing: a counter is for people."""

    def hashing_done(self) -> None:
        """Nothing: a counter is for people."""

    def unreadable(self, items: tuple[Unreadable, ...]) -> None:
        self.unreadable_items = items

    def incorrect(self, entries: list[MissingBios]) -> None:
        """Nothing yet: the document has it at the end."""

    def ended_early(self, result: RunResult, failing: Sequence[MissingBios] = ()) -> None:
        """The run had nothing to upload, and is complete."""
        self.result(result, failing)

    def result(self, result: RunResult, failing: Sequence[MissingBios] = ()) -> None:
        """``failing`` is what ``--fail-if-missing`` fails on. It's no error, but it isn't ok."""
        errors = _error_items(result.errors)
        _write(self._check(result, errors, ok=not errors and not failing), self.stream)

    def report(self, entries: list[MissingBios]) -> None:
        _write(self._report(entries, []), self.stream)

    def scan(self, scanned: ScanResult, folder: Path) -> None:
        _write(self._scan(scanned, []), self.stream)

    def error(self, error: BeckError) -> None:
        """An error that stopped the run: the lists stay empty, and the document is still valid."""
        self._stopped({"code": error.code, "message": str(error), "item": None})

    def unexpected_error(self) -> None:
        """A bug in BECK. Its message could hold anything, so it stays on stderr."""
        self._stopped(INTERNAL_ERROR)

    def _stopped(self, error: dict[str, Any]) -> None:
        if self.command == "report":
            document = self._report([], [error])
        elif self.command == "scan":
            document = self._scan(ScanResult(), [error])
        else:
            self.files_scanned = 0
            self.unreadable_items = ()
            stopped = RunResult(plan=Plan(), dry_run=self.dry_run)
            document = self._check(stopped, [error], ok=False)
        _write(document, self.stream)

    def _check(
        self, result: RunResult, errors: list[dict[str, Any]], *, ok: bool
    ) -> dict[str, Any]:
        plan = result.plan
        still_missing = _missing_items(plan.still_missing)
        return {
            **_header(self.command, ok=ok),
            "dry_run": result.dry_run,
            "frontend": self.frontend,
            "target": self.target,
            "summary": {
                "missing_entries": distinct_targets(plan),
                "satisfied": len(result.skipped if result.dry_run else result.completed),
                "still_missing": len(still_missing),
                "files_scanned": self.files_scanned,
                "uploaded": len(result.completed),
                "duplicates": len(plan.duplicates),
                "unmatched": len(plan.unmatched),
                "deleted": len(result.deleted),
                "errors": len(errors),
            },
            "uploads": _upload_items(result),
            "incorrect": _incorrect_items(plan.incorrect),
            "still_missing": still_missing,
            "duplicates": [
                {
                    "path": duplicate.file.relative.as_posix(),
                    "of": duplicate.of.relative.as_posix(),
                    "md5": duplicate.file.md5,
                }
                for duplicate in plan.duplicates
            ],
            "already_filled": _file_items(plan.already_filled),
            "unmatched": _file_items(plan.unmatched),
            "unreadable": _unreadable_items(self.unreadable_items),
            "deleted": _file_items(result.deleted),
            "errors": errors,
        }

    def _report(self, entries: list[MissingBios], errors: list[dict[str, Any]]) -> dict[str, Any]:
        missing = _missing_items(entry for entry in entries if not entry.incorrect)
        incorrect = _incorrect_items([entry for entry in entries if entry.incorrect])
        return {
            **_header(self.command, ok=not errors),
            "frontend": self.frontend,
            "target": self.target,
            "summary": {"missing": len(missing), "incorrect": len(incorrect)},
            "missing": missing,
            "incorrect": incorrect,
            "errors": errors,
        }

    def _scan(self, scanned: ScanResult, errors: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            **_header(self.command, ok=not errors),
            "summary": {"files": len(scanned.files), "unreadable": len(scanned.unreadable)},
            "files": _file_items(scanned.files),
            "unreadable": _unreadable_items(scanned.unreadable),
            "errors": errors,
        }
