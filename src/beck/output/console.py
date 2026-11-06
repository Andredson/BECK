"""Human output on stdout, with colors when the terminal wants them. Logs go to stderr."""

import ctypes
import logging
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import TextIO

from beck.errors import BeckError
from beck.models import SHARE_ROOT, LocalFile, MissingBios, RunResult, Unreadable
from beck.output import (
    LOGGER_NAME,
    distinct_targets,
    extension_warning,
    print_safely,
    upload_status,
)

RESET = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"

# How Python holds a byte of a file name that isn't valid UTF-8: 0xff becomes the character U+DCFF.
UNDECODABLE_BYTE = re.compile("[\udc80-\udcff]")

# What people read for each status of an upload. "planned" depends on more, so it isn't here.
OUTCOMES = {
    "uploaded": "copied",
    "replaced": "replaced",
    "kept": "already on the device, kept",
    "failed": "failed",
    "skipped": "skipped",
}

# DEC-56: the risk of --clean-unmatched, wherever it's about to delete something.
UNMATCHED_WARNING = (
    "These files aren't in the current report. That doesn't mean they're junk: after an upload and "
    "a rescan, your good BIOS files aren't in it either."
)


def configure_logging(level: int = logging.WARNING) -> logging.Logger:
    """Send BECK's diagnostics to stderr, so that stdout only has the human output.

    Only BECK's: pysmb's debug logs show what crosses the network, which isn't for a log. With debug
    logs, each line says how long the run has taken so far.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    if level <= logging.DEBUG:
        handler.setFormatter(logging.Formatter("%(relativeCreated)6d ms  %(message)s"))
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


def _printable(line: str, stream: TextIO | None) -> str:
    """A line with what the stream can't encode escaped, so that a name can't crash a run.

    A name can be anything, and this runs after the uploads and deletions: a crash here would report
    a failure for work that's done. ``--json`` has the exact name, if someone needs it.
    """
    readable = UNDECODABLE_BYTE.sub(lambda byte: f"\\x{ord(byte[0]) - 0xDC00:02x}", line)
    encoding = getattr(stream, "encoding", None) or "utf-8"  # a StringIO has none
    return readable.encode(encoding, "backslashreplace").decode(encoding)


def _deletes_unmatched(result: RunResult) -> bool:
    return any(file in result.plan.unmatched for file in result.deleted)


def _files_analysed(result: RunResult) -> list[LocalFile]:
    plan = result.plan
    files = {upload.source for upload in plan.uploads}
    files.update(duplicate.file for duplicate in plan.duplicates)
    files.update(plan.unmatched, plan.already_filled)
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
        self.stream = sys.stdout if stream is None else stream
        settings = os.environ if environ is None else environ
        self.color = self.stream is not None and wants_color(self.stream, settings)
        self.quiet = quiet
        self.progress = progress and not quiet and sys.stderr is not None and sys.stderr.isatty()
        self._counter = ""

    def _paint(self, text: object, color: str) -> str:
        return f"{color}{text}{RESET}" if self.color else str(text)

    def _print(self, line: str) -> None:
        print_safely(_printable(line, self.stream), self.stream)

    def _detail(self, line: str) -> None:
        if not self.quiet:
            self._print(line)

    def _show_counter(self, text: str) -> None:
        """On stderr, to leave stdout as the result. If it fails, the run carries on without it."""
        try:
            sys.stderr.write(text)
            sys.stderr.flush()
        except OSError:
            self.progress = False

    def hashing(self, count: int) -> None:
        if self.progress:
            self._counter = f"Hashing files: {count}"
            self._show_counter(f"\r{self._counter}")

    def hashing_done(self) -> None:
        """Clears the counter by writing over it, which any terminal can do."""
        if self.progress and self._counter:
            self._show_counter(f"\r{' ' * len(self._counter)}\r")

    def missing_count(self, count: int) -> None:
        self._detail(f"There are {self._paint(count, MAGENTA)} missing bios in your RECALBOX")

    def nothing_missing(self) -> None:
        self._print(self._paint("No missing bios were found in your RECALBOX!", CYAN))

    def files_found(self, count: int) -> None:
        self._detail(
            f"There are {self._paint(count, MAGENTA)} possible bios to be analysed in your system"
        )

    def no_files(self, folder: Path) -> None:
        self._print(self._paint(f"No BIOS files found in {folder}", CYAN))

    def error(self, message: BeckError | str) -> None:
        self._print(f"{self._paint('Error', RED)}: {message}")

    def unexpected_error(self) -> None:
        """Nothing on stdout: the traceback goes to stderr, for the bug report."""

    def opened(self, target: str) -> None:
        """Nothing: human output names the target only when something goes wrong with it."""

    def ended_early(self, result: RunResult, failing: Sequence[MissingBios] = ()) -> None:
        """The lines before this one already said why there's nothing to upload."""
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
            self._detail(f"{item.relative}: {label}, skipped: {item.reason}")

    def incorrect(self, entries: list[MissingBios]) -> None:
        """Files on the device with a wrong hash, which BECK keeps (DEC-54). One line per target."""
        for target in sorted({entry.target for entry in entries}):
            label = self._paint("INCORRECT:", RED)
            self._detail(f"{label} {target} is on the device with a wrong MD5, and was kept")

    def report(self, entries: list[MissingBios]) -> None:
        """What a report lists, grouped by folder. One line per target."""
        if not entries:
            self.nothing_missing()
            return
        self.incorrect([entry for entry in entries if entry.incorrect])
        missing = [entry for entry in entries if not entry.incorrect]
        by_target: dict[PurePosixPath, bool] = {}
        for entry in missing:
            by_target[entry.target] = (
                by_target.get(entry.target, False) or entry.required is not False
            )
        if by_target:
            self.missing_count(len(by_target))
        for folder in sorted({target.parent for target in by_target}, key=PurePosixPath.as_posix):
            self._print(f"{folder.as_posix()}/" if folder != SHARE_ROOT else "(BIOS folder)")
            for target in sorted(by_target, key=PurePosixPath.as_posix):
                if target.parent == folder:
                    kind = "required" if by_target[target] else "optional"
                    self._print(f"  {target.name} ({kind})")

    def result(self, result: RunResult, failing: Sequence[MissingBios] = ()) -> None:
        """What happened: uploads, then one or more lines per local file, then the summary."""
        for upload in result.completed:
            self._detail(f"{self._paint('FOUND:', GREEN)} {upload.entry.name} -> {upload.target}")
        for line in self._deleted_lines(result) if self.quiet else self._file_lines(result):
            self._print(line)
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
            self._print(f"{self._paint('MISSING:', RED)} {target}")
        if self.quiet:
            for target in sorted({entry.target for entry in failing if entry.incorrect}):
                self._print(f"{self._paint('INCORRECT:', RED)} {target}")
        state = "that would still be" if dry_run else "still"
        self._print(
            f"Required files {state} missing or incorrect: {len({e.target for e in failing})}. "
            "Exit code 5, because of --fail-if-missing."
        )

    def _deleted_lines(self, result: RunResult) -> list[str]:
        """Quiet never hides a deletion: the result lists every one (docs/cli.md)."""
        gone = "would be deleted" if result.dry_run else "deleted"
        paths = sorted(file.relative.as_posix() for file in result.deleted)
        return [f"{path}: {gone}" for path in paths]

    def _file_lines(self, result: RunResult) -> list[str]:
        plan = result.plan
        gone = "would be deleted" if result.dry_run else "deleted"
        duplicate_of = {duplicate.file: duplicate.of for duplicate in plan.duplicates}
        lines = []

        for file in _files_analysed(result):
            path = file.relative.as_posix()
            uploads = [upload for upload in plan.uploads if upload.source == file]
            if file in duplicate_of:
                lines.append(f"{path}: duplicate of {duplicate_of[file].relative.as_posix()}, kept")
            elif file in plan.already_filled:
                lines.append(f"{path}: target already filled, kept")
            elif not uploads:
                fits = sorted({e.target for e in plan.incorrect if file.md5 in e.md5s})
                if fits:
                    targets = ", ".join(str(target) for target in fits)
                    lines.append(
                        f"{path}: valid for {targets}, which is incorrect on the device, kept"
                    )
                elif file in result.deleted:
                    lines.append(f"{path}: no match, {gone}")
                else:
                    lines.append(f"{path}: no match, kept")
            for upload in uploads:
                status = upload_status(upload, result)
                if status == "planned":
                    outcome = "would replace" if upload in result.replaced else "would copy"
                else:
                    outcome = OUTCOMES[status]
                lines.append(f"{path}: {outcome} -> {upload.target}")
                if upload in result.extension_changes:
                    label = self._paint("Warning", YELLOW)
                    lines.append(f"{label}: {extension_warning(upload)}")
            if uploads and file in result.deleted:
                lines.append(f"{path}: {gone}")

        return lines

    def _summary(self, result: RunResult) -> None:
        if _deletes_unmatched(result) and result.dry_run:
            self._print(UNMATCHED_WARNING)
        files = len(_files_analysed(result))
        total = self._paint(distinct_targets(result.plan), BLUE)
        if result.dry_run:
            would = self._paint(len(result.skipped), GREEN)
            self._print(
                f"Dry run: {would}/{total} missing entries would be satisfied, "
                f"{files} files analysed"
            )
            if result.deleted:
                self._print(f"Dry run: would delete {len(result.deleted)} local files")
            return
        done = self._paint(len(result.completed), GREEN)
        self._print(
            f"Final result: {done}/{total} missing entries satisfied, {files} files analysed"
        )
        if result.deleted:
            self._print(f"Deleted {len(result.deleted)} local files.")
        if result.completed:
            self._print(self._paint("*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***", MAGENTA))
