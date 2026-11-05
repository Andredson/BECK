"""Recalbox: how its report is laid out. See tests/fixtures/reports/ for real examples."""

import re
from pathlib import PurePosixPath

from beck.errors import ReportParseError
from beck.models import MissingBios

BIOS_ROOT = "/recalbox/share/bios/"

SYSTEM_LINE = re.compile(r"^[ \t]*SYSTEM:[ \t]*(.+)$", re.MULTILINE)
BLOCK_HEADING = re.compile(r"^[ \t]*MISSING (REQUIRED|OPTIONAL) BIOS\b:?[ \t]*(.*)$", re.MULTILINE)
PATH_LINE = re.compile(r"^[ \t]*Path:[ \t]*(.+)$", re.MULTILINE)
MD5 = re.compile(r"\b[a-fA-F0-9]{32}\b")


def _system_at(systems: list[re.Match[str]], position: int) -> str | None:
    """The name in the last SYSTEM line before a position in the report."""
    name = None
    for system in systems:
        if system.start() > position:
            break
        name = system.group(1).strip()
    return name


class RecalboxAdapter:
    """Reads the report Recalbox writes from main menu > BIOS CHECKING > REPORT."""

    name = "recalbox"
    report_path = PurePosixPath("missing_bios_report.txt")

    def parse_report(self, text: str) -> list[MissingBios]:
        """Turn a report into one entry per ``MISSING ... BIOS`` block, in report order. Pure."""
        # A BOM would hide a heading on the first line: "^" wouldn't match, and the block would vanish.
        text = text.removeprefix("\ufeff").replace("\r\n", "\n")
        systems = list(SYSTEM_LINE.finditer(text))
        headings = list(BLOCK_HEADING.finditer(text))
        missing = []

        for heading, following in zip(headings, [*headings[1:], None], strict=False):
            block = text[heading.end() : following.start() if following else len(text)]
            first_line = heading.group(0).strip()
            name = heading.group(2).strip()
            location = PATH_LINE.search(block)
            md5s = frozenset(md5.lower() for md5 in MD5.findall(block))

            if not name:
                raise ReportParseError(f"No file name in report block: {first_line}")
            if location is None:
                raise ReportParseError(f"No Path line in report block: {first_line}")
            if not md5s:
                raise ReportParseError(f"No MD5 value in report block: {first_line}")

            # A Path line can list two locations ("<path> or <path>"): use the first (DEC-50).
            first_path = location.group(1).split(" or ")[0].strip()
            if not first_path.startswith(BIOS_ROOT):
                raise ReportParseError(f"Path is outside {BIOS_ROOT}: {first_line}")
            folder = first_path.removeprefix(BIOS_ROOT).rpartition("/")[0]

            try:
                entry = MissingBios(
                    name=name,
                    target=PurePosixPath(folder) / name,
                    md5s=md5s,
                    required=heading.group(1) == "REQUIRED",
                    system=_system_at(systems, heading.start()),
                )
            except ValueError as e:
                raise ReportParseError(f"Unsafe path in report block: {first_line}") from e
            missing.append(entry)

        return missing
