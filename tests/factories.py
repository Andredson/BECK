"""Build test data. A "BIOS" here is always random bytes, never real BIOS content."""

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from beck.frontends.recalbox import BIOS_ROOT
from beck.hashing import md5_file
from beck.models import LocalFile, MissingBios

Snapshot = dict[str, tuple[int, int, bytes]]

SECTION_LINE = "=" * 62
SYSTEM_LINE = "-" * 45


def md5_of(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def make_bios_file(directory: Path, relative: str, content: bytes | None = None) -> LocalFile:
    """Write a file under ``directory``, random bytes by default, and describe it with its MD5."""
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    data = os.urandom(64) if content is None else content
    path.write_bytes(data)
    return LocalFile(
        path=path, relative=PurePosixPath(relative), md5=md5_file(path), size=len(data)
    )


def make_local_file(relative: str, md5: str, size: int = 1) -> LocalFile:
    """Describe a local file that doesn't exist on disk, for tests that do no I/O."""
    return LocalFile(
        path=Path("/bios", relative), relative=PurePosixPath(relative), md5=md5, size=size
    )


def make_missing(
    target: str,
    *md5s: str,
    required: bool | None = True,
    system: str | None = None,
    incorrect: bool = False,
    current_md5: str | None = None,
) -> MissingBios:
    """A report entry. Its name is the target's last part, which is what the model requires."""
    path = PurePosixPath(target)
    return MissingBios(
        name=path.name,
        target=path,
        md5s=frozenset(md5s),
        required=required,
        system=system,
        incorrect=incorrect,
        current_md5=current_md5,
    )


def settings_text(url: str, user: str = "", *, timeout: int | None = None) -> str:
    """A settings file naming this target. A password can't go in one: see BECK_SMB_PASSWORD."""
    timeout_line = "" if timeout is None else f"timeout = {timeout}\n"
    return f'schema_version = 1\n[target]\nurl = "{url}"\n[smb]\nuser = "{user}"\n{timeout_line}'


def make_report_text(entries: Iterable[MissingBios]) -> str:
    """Render entries in the real Recalbox format, CRLF included (see tests/fixtures/reports/)."""
    lines = [
        SECTION_LINE,
        "MISSING BIOS REPORT",
        "Platform: x86_64",
        "Generated on 2026/Nov./04 16:48:14+0100",
        SECTION_LINE,
        "",
    ]
    current_system = None
    for entry in entries:
        if entry.system is not None and entry.system != current_system:
            lines += [f"SYSTEM: {entry.system}", SYSTEM_LINE, ""]
            current_system = entry.system
        kind = "OPTIONAL" if entry.required is False else "REQUIRED"
        lines += [
            f"  {'INCORRECT' if entry.incorrect else 'MISSING'} {kind} BIOS: {entry.name}",
            f"    Path: {BIOS_ROOT}{entry.target}",
            "    For: libretro/beck-test",
            *([f"    Current MD5: {entry.current_md5}"] if entry.current_md5 else []),
            "    Possible MD5 List:",
            *(f"      {md5.upper()}" for md5 in sorted(entry.md5s)),
            "",
        ]
    return "\r\n".join(lines) + "\r\n"


def snapshot(folder: Path) -> Snapshot:
    """Every file under a folder: size, modification time and content, to compare later."""
    return {
        path.relative_to(folder).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }
