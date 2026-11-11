# SPDX-License-Identifier: GPL-3.0-only
"""Human output on stdout, with colors when the terminal wants them. Logs go to stderr."""

import ctypes
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, TextIO

from beck.config import ConfigLocation
from beck.errors import BeckError
from beck.models import (
    SHARE_ROOT,
    ItemError,
    LocalFile,
    MissingBios,
    RunResult,
    ScanResult,
    Unreadable,
)
from beck.output import (
    LOGGER_NAME,
    distinct_targets,
    escaped_for_terminal,
    extension_warning,
    not_a_zip_warning,
    print_safely,
    upload_status,
)
from beck.redact import redact

RESET = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"

# What people read for each status of an upload. "planned" depends on more, so it isn't here.
OUTCOMES = {
    "uploaded": "copied",
    "replaced": "replaced",
    "kept": "already on the device, kept",
    "failed": "failed",
    "skipped": "skipped",
}

# Why BECK reads the settings file it reads.
WHY_THIS_FILE = {
    "flag": "named by --config",
    "environment": "named by BECK_CONFIG",
    "default": "the default place on this system",
}

# DEC-56: the risk of --clean-unmatched, wherever it's about to delete something.
UNMATCHED_WARNING = (
    "These files aren't in the current report. That doesn't mean they're junk: after an upload and "
    "a rescan, your good BIOS files aren't in it either."
)


class _EscapingFormatter(logging.Formatter):
    """A log line can hold a name, which can be anything. A traceback keeps its line breaks."""

    def formatMessage(self, record: logging.LogRecord) -> str:
        return escaped_for_terminal(redact(super().formatMessage(record)))

    def formatException(self, ei: Any) -> str:
        lines = super().formatException(ei).split("\n")
        return "\n".join(escaped_for_terminal(redact(line)) for line in lines)


def configure_logging(level: int = logging.WARNING) -> logging.Logger:
    """Send BECK's diagnostics to stderr, so that stdout only has the human output.

    Only BECK's: pysmb's debug logs show what crosses the network, which isn't for a log. With debug
    logs, each line says how long the run has taken so far.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    timed = "%(relativeCreated)6d ms  %(message)s"
    handler.setFormatter(_EscapingFormatter(timed if level <= logging.DEBUG else None))
    logger.handlers[:] = [handler]  # replaced, so lines never repeat
    return logger


def enable_windows_ansi() -> bool:
    """Make a Windows console understand color codes. Other systems always do."""
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # standard output
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # virtual terminal
    except (AttributeError, OSError):
        return False


def wants_color(stream: TextIO, environ: Mapping[str, str]) -> bool:
    """NO_COLOR turns color off, then FORCE_COLOR turns it on, then it depends on the terminal.

    As their conventions say, an empty value counts as not set (no-color.org, force-color.org).
    """
    if environ.get("NO_COLOR"):
        return False
    if environ.get("FORCE_COLOR"):
        enable_windows_ansi()
        return True
    return stream.isatty() and enable_windows_ansi()


def _printable(text: str, stream: TextIO | None) -> str:
    """Text that can't act on a terminal, or crash on a stream that can't encode it.

    A name can be anything, and this runs after the uploads and deletions: a crash here would report
    a failure for work that's done. ``--json`` has the exact name, if someone needs it.
    """
    encoding = getattr(stream, "encoding", None) or "utf-8"  # a StringIO has none
    safe = escaped_for_terminal(redact(text))
    return safe.encode(encoding, "backslashreplace").decode(encoding)


@dataclass(frozen=True, slots=True)
class _Painted:
    """Part of a line to show in a color. Its text is escaped too: only the color goes out raw."""

    text: object
    color: str


_Part = str | _Painted


def _required_by_target(entries: list[MissingBios]) -> dict[PurePosixPath, bool]:
    """Whether each target counts as required: if any entry says so, or one doesn't say."""
    by_target: dict[PurePosixPath, bool] = {}
    for entry in entries:
        by_target[entry.target] = by_target.get(entry.target, False) or entry.required is not False
    return by_target


def _kind(required: bool) -> str:
    return "required" if required else "optional"


def _deletes_unmatched(result: RunResult) -> bool:
    return any(file in result.plan.unmatched for file in result.deleted)


def _files_analysed(result: RunResult) -> list[LocalFile]:
    plan = result.plan
    files = {upload.source for upload in plan.uploads}
    files.update(duplicate.file for duplicate in plan.duplicates)
    files.update(plan.unmatched, plan.already_filled)
    files.update(upload.source for upload in plan.not_a_zip)
    return sorted(files, key=lambda file: file.relative.as_posix())


class ConsoleRenderer:
    """Prints each stage of a run. Nothing here decides anything.

    ``quiet`` leaves only errors, deletions and how the run ended. ``progress`` allows the counter
    while hashing, which also needs a terminal, and which ``quiet`` turns off.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        environ: Mapping[str, str] | None = None,
        *,
        quiet: bool = False,
        progress: bool = True,
    ) -> None:
        """Choose where to print. By default, stdout, and the real environment decides on color."""
        self.stream = sys.stdout if stream is None else stream
        settings = os.environ if environ is None else environ
        self.color = self.stream is not None and wants_color(self.stream, settings)
        self.quiet = quiet
        self.progress = progress and not quiet and sys.stderr is not None and sys.stderr.isatty()
        self._counter = ""

    def _paint(self, text: object, color: str) -> _Painted:
        return _Painted(text, color)

    def _rendered(self, part: _Part) -> str:
        if isinstance(part, str):
            return _printable(part, self.stream)
        text = _printable(str(part.text), self.stream)
        return f"{part.color}{text}{RESET}" if self.color else text

    def _print(self, *parts: _Part) -> None:
        """Print a line. This is the one way to stdout, so nothing can skip the escaping.

        A line takes parts because of it: colors can't be inside a text that's about to be escaped.
        """
        print_safely("".join(self._rendered(part) for part in parts), self.stream)

    def _detail(self, *parts: _Part) -> None:
        if not self.quiet:
            self._print(*parts)

    def _show_counter(self, text: str) -> None:
        """On stderr, to leave stdout as the result. If it fails, the run carries on without it."""
        try:
            sys.stderr.write(text)
            sys.stderr.flush()
        except OSError:
            self.progress = False

    def hashing(self, count: int) -> None:
        """Update the counter, if there's a terminal to show it on."""
        if self.progress:
            self._counter = f"Hashing files: {count}"
            self._show_counter(f"\r{self._counter}")

    def hashing_done(self) -> None:
        """Clears the counter by writing over it, which any terminal can do."""
        if self.progress and self._counter:
            self._show_counter(f"\r{' ' * len(self._counter)}\r")

    def missing_count(self, count: int) -> None:
        """How many files are missing. ``quiet`` hides this."""
        self._detail("There are ", self._paint(count, MAGENTA), " missing bios in your RECALBOX")

    def nothing_missing(self) -> None:
        """Say that nothing is missing. ``quiet`` keeps this: it's how the run ended."""
        self._print(self._paint("No missing bios were found in your RECALBOX!", CYAN))

    def files_found(self, count: int) -> None:
        """How many local files were found. ``quiet`` hides this."""
        self._detail(
            "There are ",
            self._paint(count, MAGENTA),
            " possible bios to be analysed in your system",
        )

    def no_files(self, folder: Path) -> None:
        """Say that the folder has no BIOS files. ``quiet`` keeps this: it's how the run ended."""
        self._print(self._paint(f"No BIOS files found in {folder}", CYAN))

    def error(self, message: BeckError | str) -> None:
        """Print an error. ``quiet`` keeps this."""
        self._print(self._paint("Error", RED), f": {message}")

    def unexpected_error(self) -> None:
        """Nothing on stdout: the traceback goes to stderr, for the bug report."""

    def opened(self, target: str) -> None:
        """Nothing: human output names the target only when something goes wrong with it."""

    def uses_frontend(self, name: str) -> None:
        """Nothing: human output doesn't name the frontend."""

    def ended_early(self, result: RunResult, failing: Sequence[MissingBios] = ()) -> None:
        """The lines before this one already said why there's nothing to upload."""
        for error in result.errors:
            self.error(error.message)
        self._failing_if_missing(failing, dry_run=result.dry_run)

    def can_ask(self) -> bool:
        """Only with a terminal to read the answer from, and a stderr to ask on."""
        return sys.stdin is not None and sys.stderr is not None and sys.stdin.isatty()

    def confirm_deletion(self, preview: RunResult) -> bool:
        """List what would be deleted, and ask. On stderr, so that stdout stays the result.

        This isn't ``print_safely``: nobody can answer a question that wasn't shown, so an OSError
        here means BECK can't ask. Anything that isn't text isn't a yes.
        """
        for file in preview.deleted:
            print(_printable(f"  {file.relative.as_posix()}", sys.stderr), file=sys.stderr)
        if _deletes_unmatched(preview):
            print(UNMATCHED_WARNING, file=sys.stderr)
        print(f"Delete {len(preview.deleted)} files? [y/N] ", end="", file=sys.stderr, flush=True)
        try:
            answer = sys.stdin.readline()
        except UnicodeDecodeError:
            return False
        return answer.strip().lower() in ("y", "yes")

    def unreadable(self, items: tuple[Unreadable, ...]) -> None:
        """Local files and folders that couldn't be read. The run carries on without them."""
        for item in items:
            label = self._paint("can't be read", RED)
            self._detail(f"{item.relative}: ", label, f", skipped: {item.reason}")

    def incorrect(self, entries: list[MissingBios]) -> None:
        """Files on the device with a wrong hash, which BECK keeps (DEC-54). One line per target."""
        for target in sorted({entry.target for entry in entries}):
            label = self._paint("INCORRECT:", RED)
            self._detail(label, f" {target} is on the device with a wrong MD5, and was kept")

    def report(self, entries: list[MissingBios], rejected: Sequence[ItemError] = ()) -> None:
        """What a report lists, grouped by folder. One line per target, then what it refused."""
        if not entries and not rejected:
            self.nothing_missing()
            return
        incorrect = _required_by_target([entry for entry in entries if entry.incorrect])
        for target in sorted(incorrect):
            self._print(
                self._paint("INCORRECT:", RED),
                f" {target} ({_kind(incorrect[target])}) is on the device with a wrong MD5",
            )
        by_target = _required_by_target([entry for entry in entries if not entry.incorrect])
        if by_target:
            self.missing_count(len(by_target))
        for folder in sorted({target.parent for target in by_target}, key=PurePosixPath.as_posix):
            self._print(f"{folder.as_posix()}/" if folder != SHARE_ROOT else "(BIOS folder)")
            for target in sorted(by_target, key=PurePosixPath.as_posix):
                if target.parent == folder:
                    self._print(f"  {target.name} ({_kind(by_target[target])})")
        for error in rejected:
            self.error(error.message)

    def scan(self, scanned: ScanResult, folder: Path) -> None:
        """Each local file, in the order of ``md5sum``: the name last, as it can be anything."""
        if not scanned.files:
            self.no_files(folder)
        width = max((len(str(file.size)) for file in scanned.files), default=0)
        for file in scanned.files:
            self._print(f"{file.md5}  {file.size:>{width}}  {file.relative.as_posix()}")
        self.unreadable(scanned.unreadable)
        if scanned.files:
            total = f"Files: {len(scanned.files)}"
            unreadable = f", can't be read: {len(scanned.unreadable)}" if scanned.unreadable else ""
            self._print(f"{total}{unreadable}")

    def config_path(self, location: ConfigLocation, exists: bool) -> None:
        """The path alone on the first line, so that ``$(beck config path | head -1)`` works."""
        self._print(str(location.path))
        self._print(f"This is {WHY_THIS_FILE[location.source]}.")
        if not exists:
            self._print("It doesn't exist yet. To create it, run beck config init.")

    def config_created(self, location: ConfigLocation, exists: bool) -> None:
        """Say where the new settings file is."""
        self._print(f"Wrote {location.path}, which only you can read. Edit it to suit you.")

    def config_file(self, location: ConfigLocation, exists: bool) -> None:
        """Nothing yet: ``config_settings`` says it, if the file can be read."""

    def config_settings(
        self, location: ConfigLocation, exists: bool, settings: dict[str, dict[str, Any]]
    ) -> None:
        """The settings file, then each setting, with its value and where that came from."""
        state = "" if exists else ", which doesn't exist"
        self._print(f"Settings file: {location.path} ({WHY_THIS_FILE[location.source]}{state})")
        for name, setting in settings.items():
            value = "not set" if setting["value"] is None else setting["value"]
            shown = "(a guest)" if name == "smb_user" and value == "" else value
            self._print(f"{name}: {shown} ({setting['source']})")

    def result(self, result: RunResult, failing: Sequence[MissingBios] = ()) -> None:
        """What happened: uploads, then one or more lines per local file, then the summary."""
        for upload in result.completed:
            self._detail(self._paint("FOUND:", GREEN), f" {upload.entry.name} -> {upload.target}")
        for line in self._deleted_lines(result) if self.quiet else self._file_lines(result):
            self._print(*line)
        for error in result.errors:
            self.error(error.message)
        if result.kept:
            self._detail(
                f"{len(result.kept)} files were already on the device, and were kept. If the "
                "report is out of date, generate a new one. To replace them, use --overwrite."
            )
        self._summary(result)
        self._failing_if_missing(failing, dry_run=result.dry_run)

    def _failing_if_missing(self, failing: Sequence[MissingBios], *, dry_run: bool) -> None:
        """Why the run exits with 5. INCORRECT files have their own lines, unless quiet."""
        if not failing:
            return
        for target in sorted({entry.target for entry in failing if not entry.incorrect}):
            self._print(self._paint("MISSING:", RED), f" {target}")
        if self.quiet:
            for target in sorted({entry.target for entry in failing if entry.incorrect}):
                self._print(self._paint("INCORRECT:", RED), f" {target}")
        state = "that would still be" if dry_run else "still"
        self._print(
            f"Required files {state} missing or incorrect: {len({e.target for e in failing})}. "
            "Exit code 5, because of --fail-if-missing."
        )

    def _deleted_lines(self, result: RunResult) -> list[list[_Part]]:
        """Quiet never hides a deletion: the result lists every one (docs/cli.md)."""
        gone = "would be deleted" if result.dry_run else "deleted"
        paths = sorted(file.relative.as_posix() for file in result.deleted)
        return [[f"{path}: {gone}"] for path in paths]

    def _file_lines(self, result: RunResult) -> list[list[_Part]]:
        plan = result.plan
        gone = "would be deleted" if result.dry_run else "deleted"
        duplicate_of = {duplicate.file: duplicate.of for duplicate in plan.duplicates}
        lines: list[list[_Part]] = []

        for file in _files_analysed(result):
            path = file.relative.as_posix()
            uploads = [upload for upload in plan.uploads if upload.source == file]
            held_back = [upload for upload in plan.not_a_zip if upload.source == file]
            if file in duplicate_of:
                of = duplicate_of[file].relative.as_posix()
                lines.append([f"{path}: duplicate of {of}, kept"])
            elif file in plan.already_filled:
                lines.append([f"{path}: target already filled, kept"])
            elif not uploads and not held_back:
                fits = sorted({e.target for e in plan.incorrect if file.md5 in e.md5s})
                if fits:
                    targets = ", ".join(str(target) for target in fits)
                    lines.append(
                        [f"{path}: valid for {targets}, which is incorrect on the device, kept"]
                    )
                elif file in result.deleted:
                    lines.append([f"{path}: no match, {gone}"])
                else:
                    lines.append([f"{path}: no match, kept"])
            for upload in uploads:
                status = upload_status(upload, result)
                if status == "planned":
                    outcome = "would replace" if upload in result.replaced else "would copy"
                else:
                    outcome = OUTCOMES[status]
                lines.append([f"{path}: {outcome} -> {upload.target}"])
                if upload in result.extension_changes:
                    label = self._paint("Warning", YELLOW)
                    lines.append([label, f": {extension_warning(upload)}"])
            for upload in held_back:
                lines.append([f"{path}: not a zip archive, not copied -> {upload.target}"])
                lines.append([self._paint("Warning", YELLOW), f": {not_a_zip_warning(upload)}"])
            if uploads and file in result.deleted:
                lines.append([f"{path}: {gone}"])

        return lines

    def _summary(self, result: RunResult) -> None:
        if _deletes_unmatched(result) and result.dry_run:
            self._print(UNMATCHED_WARNING)
        files = len(_files_analysed(result))
        total = self._paint(distinct_targets(result.plan), BLUE)
        if result.dry_run:
            would = self._paint(len(result.skipped), GREEN)
            self._print(
                "Dry run: ",
                would,
                "/",
                total,
                f" missing entries would be satisfied, {files} files analysed",
            )
            if result.deleted:
                self._print(f"Dry run: would delete {len(result.deleted)} local files")
            return
        done = self._paint(len(result.completed), GREEN)
        self._print(
            "Final result: ",
            done,
            "/",
            total,
            f" missing entries satisfied, {files} files analysed",
        )
        if result.deleted:
            self._print(f"Deleted {len(result.deleted)} local files.")
        if result.completed:
            self._print(self._paint("*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***", MAGENTA))
