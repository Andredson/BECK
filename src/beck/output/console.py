"""Human output on stdout, with colors when the terminal wants them. Logs go to stderr."""

import ctypes
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from beck.models import LocalFile, MissingBios, RunResult, Unreadable

RESET = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
BLUE = "\033[94m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"

LOGGER_NAME = "beck"


def configure_logging(level: int = logging.WARNING) -> logging.Logger:
    """Send BECK's diagnostics to stderr, so that stdout only has the human output."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers[:] = [logging.StreamHandler(sys.stderr)]  # replaced, so lines never repeat
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


def _distinct_targets(result: RunResult) -> int:
    plan = result.plan
    return len({u.target for u in plan.uploads} | {e.target for e in plan.still_missing})


def _files_analysed(result: RunResult) -> list[LocalFile]:
    plan = result.plan
    files = {upload.source for upload in plan.uploads}
    files.update(duplicate.file for duplicate in plan.duplicates)
    files.update(plan.unmatched, plan.already_filled)
    return sorted(files, key=lambda file: file.relative.as_posix())


class ConsoleRenderer:
    """Prints each stage of a run. Nothing here decides anything."""

    def __init__(
        self, stream: TextIO | None = None, environ: Mapping[str, str] | None = None
    ) -> None:
        self.stream = sys.stdout if stream is None else stream
        self.color = wants_color(self.stream, os.environ if environ is None else environ)

    def _paint(self, text: object, color: str) -> str:
        return f"{color}{text}{RESET}" if self.color else str(text)

    def _print(self, line: str) -> None:
        print(line, file=self.stream)

    def missing_count(self, count: int) -> None:
        self._print(f"There are {self._paint(count, MAGENTA)} missing bios in your RECALBOX")

    def nothing_missing(self) -> None:
        self._print(self._paint("No missing bios were found in your RECALBOX!", CYAN))

    def files_found(self, count: int) -> None:
        self._print(
            f"There are {self._paint(count, MAGENTA)} possible bios to be analysed in your system"
        )

    def no_files(self, folder: Path) -> None:
        self._print(self._paint(f"No BIOS files found in {folder}", CYAN))

    def error(self, message: object) -> None:
        self._print(f"{self._paint('Error', RED)}: {message}")

    def unreadable(self, items: tuple[Unreadable, ...]) -> None:
        """Local files and folders that couldn't be read. The run carries on without them."""
        for item in items:
            label = self._paint("can't be read", RED)
            self._print(f"{item.relative}: {label}, skipped: {item.reason}")

    def incorrect(self, entries: list[MissingBios]) -> None:
        """Files on the device with a wrong hash, which BECK keeps (DEC-54). One line per target."""
        for target in sorted({entry.target for entry in entries}):
            label = self._paint("INCORRECT:", RED)
            self._print(f"{label} {target} is on the device with a wrong MD5, and was kept")

    def result(self, result: RunResult) -> None:
        """What happened: uploads, then one or more lines per local file, then the summary."""
        for upload in result.completed:
            self._print(f"{self._paint('FOUND:', GREEN)} {upload.entry.name} -> {upload.target}")
        for line in self._file_lines(result):
            self._print(line)
        for error in result.errors:
            self.error(error.message)
        self._summary(result)

    def _file_lines(self, result: RunResult) -> list[str]:
        plan = result.plan
        completed = {upload.target for upload in result.completed}
        failed = {error.item for error in result.errors}
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
                else:
                    lines.append(f"{path}: no match, kept")
            for upload in uploads:
                if result.dry_run:
                    outcome = "would copy"
                elif upload.target in completed:
                    outcome = "copied"
                elif upload.target.as_posix() in failed:
                    outcome = "failed"
                else:
                    outcome = "skipped"
                lines.append(f"{path}: {outcome} -> {upload.target}")

        return lines

    def _summary(self, result: RunResult) -> None:
        files = len(_files_analysed(result))
        total = self._paint(_distinct_targets(result), BLUE)
        if result.dry_run:
            would = self._paint(len(result.skipped), GREEN)
            self._print(
                f"Dry run: {would}/{total} missing entries would be satisfied, "
                f"{files} files analysed"
            )
            return
        done = self._paint(len(result.completed), GREEN)
        self._print(
            f"Final result: {done}/{total} missing entries satisfied, {files} files analysed"
        )
        if result.completed:
            self._print(self._paint("*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***", MAGENTA))
