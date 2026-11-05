"""The data passed between BECK's modules. No I/O here.

Remote paths are always relative to the target's BIOS root. Breaking an invariant raises ValueError,
because it's a bug in BECK: adapters must reject bad input with a BeckError before building a model.
"""

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MD5 = re.compile(r"[0-9a-f]{32}")
SHARE_ROOT = PurePosixPath(".")  # a target's BIOS folder, when it's the whole share


def _check_md5(md5: str) -> None:
    if not MD5.fullmatch(md5):
        raise ValueError(f"Not a lowercase MD5: {md5!r}")


def _check_relative_file(path: PurePosixPath) -> None:
    if path.is_absolute() or ".." in path.parts or not path.name:
        raise ValueError(f"Not a relative file path: {path}")


@dataclass(frozen=True, slots=True)
class MissingBios:
    """One entry of a missing-BIOS report: a file that's missing, or on the device but incorrect."""

    name: str
    target: PurePosixPath
    md5s: frozenset[str]
    required: bool | None = None  # None: the report doesn't say
    system: str | None = None
    incorrect: bool = False  # the file is on the device, but with a hash that isn't on the list
    current_md5: str | None = None  # the hash of the file on the device, if the report gives it

    def __post_init__(self) -> None:
        _check_relative_file(self.target)
        if self.current_md5 is not None:
            if not self.incorrect:
                raise ValueError(f"{self.name} has a current MD5 but isn't incorrect")
            _check_md5(self.current_md5)
        if self.target.name != self.name:
            raise ValueError(f"Target {self.target} doesn't end in {self.name}")
        if not self.md5s:
            raise ValueError(f"No MD5 for {self.name}")
        for md5 in self.md5s:
            _check_md5(md5)


@dataclass(frozen=True, slots=True)
class LocalFile:
    """A file found in the user's BIOS folder."""

    path: Path
    relative: PurePosixPath  # to the scanned folder
    md5: str
    size: int

    def __post_init__(self) -> None:
        _check_relative_file(self.relative)
        _check_md5(self.md5)
        if self.size < 0:
            raise ValueError(f"Negative size for {self.relative}")


@dataclass(frozen=True, slots=True)
class Unreadable:
    """A file or folder in the user's BIOS folder that couldn't be read, and why."""

    relative: PurePosixPath  # to the scanned folder
    reason: str


@dataclass(frozen=True, slots=True)
class ScanResult:
    """What a scan of the user's BIOS folder found. Both are sorted by path, as text."""

    files: tuple[LocalFile, ...] = ()
    unreadable: tuple[Unreadable, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannedUpload:
    """One local file going to one target."""

    source: LocalFile
    target: PurePosixPath
    entry: MissingBios

    def __post_init__(self) -> None:
        _check_relative_file(self.target)
        if self.entry.incorrect:
            raise ValueError(
                f"{self.target} is incorrect on the device, and isn't replaced (DEC-54)"
            )
        if self.target != self.entry.target:
            raise ValueError(f"Target {self.target} isn't the entry's {self.entry.target}")
        if self.source.md5 not in self.entry.md5s:
            raise ValueError(f"{self.source.relative} has no MD5 listed for {self.target}")


@dataclass(frozen=True, slots=True)
class Duplicate:
    """A local file with the same content as the file that was chosen instead."""

    file: LocalFile
    of: LocalFile


@dataclass(frozen=True, slots=True)
class Plan:
    """What a run will do. Every field is sorted, so the same input always gives the same plan.

    Local paths sort as text, like the stage 03 script, not folder by folder.
    """

    uploads: tuple[PlannedUpload, ...] = ()
    directories: tuple[PurePosixPath, ...] = ()
    duplicates: tuple[Duplicate, ...] = ()
    unmatched: tuple[LocalFile, ...] = ()
    already_filled: tuple[LocalFile, ...] = ()  # matched, but other files fill all its targets
    still_missing: tuple[MissingBios, ...] = ()
    incorrect: tuple[MissingBios, ...] = ()  # on the device with a wrong hash, and kept (DEC-54)

    def __post_init__(self) -> None:
        fields: dict[str, list[Any]] = {
            "uploads": sorted(self.uploads, key=lambda u: (u.target, u.source.relative.as_posix())),
            "directories": sorted(self.directories),
            "duplicates": sorted(self.duplicates, key=lambda d: d.file.relative.as_posix()),
            "unmatched": sorted(self.unmatched, key=lambda f: f.relative.as_posix()),
            "already_filled": sorted(self.already_filled, key=lambda f: f.relative.as_posix()),
            "still_missing": sorted(self.still_missing, key=lambda e: e.target),
            "incorrect": sorted(self.incorrect, key=lambda e: e.target),
        }
        for name, value in fields.items():
            object.__setattr__(self, name, tuple(value))  # the only write: this class is frozen


@dataclass(frozen=True, slots=True)
class ItemError:
    """One item that failed while the rest of the run continued."""

    item: str
    message: str


@dataclass(frozen=True, slots=True)
class RunResult:
    """What a run did."""

    plan: Plan
    completed: tuple[PlannedUpload, ...] = ()
    skipped: tuple[PlannedUpload, ...] = ()
    errors: tuple[ItemError, ...] = ()
    dry_run: bool = False
