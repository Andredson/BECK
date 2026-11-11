# SPDX-License-Identifier: GPL-3.0-only
"""Recalbox: how its report is laid out. See tests/fixtures/reports/ for real examples."""

import json
import re
from pathlib import PurePosixPath
from typing import Any

from beck.errors import ReportParseError
from beck.models import ItemError, MissingBios

BIOS_ROOT = "/recalbox/share/bios/"
API_PORT = 81  # Recalbox's web manager API, since web manager v3 (DEC-79)
API_PATH = "/api/bios"
API_STATUSES = {"HashMatching", "FileNotFound", "HashNotMatching"}

TITLE = "MISSING BIOS REPORT"
SYSTEM_LINE = re.compile(r"^[ \t]*SYSTEM:[ \t]*(.+)$", re.MULTILINE)
BLOCK_HEADING = re.compile(
    r"^[ \t]*(MISSING|INCORRECT) (REQUIRED|OPTIONAL) BIOS\b:?[ \t]*(.*)$", re.MULTILINE
)
# Anything that looks like a heading: used to notice a format BECK doesn't know.
LOOKS_LIKE_HEADING = re.compile(
    r"^[ \t]*(?:MISSING\b|INCORRECT\b|[A-Z]+(?: [A-Z]+)* BIOS\b).*$", re.MULTILINE
)
PATH_LINE = re.compile(r"^[ \t]*Path:[ \t]*(.+)$", re.MULTILINE)
CURRENT_MD5_LINE = re.compile(r"^[ \t]*Current MD5:[ \t]*([a-fA-F0-9]{32})\b", re.MULTILINE)
MD5_LIST = "Possible MD5 List:"
MD5 = re.compile(r"\b[a-fA-F0-9]{32}\b")
# Control characters, the controls for the direction of text, and what replaces a byte that wasn't
# valid UTF-8.
UNSAFE_CHARACTERS = re.compile("[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\ufffd]")


def _check_format(text: str, systems: list[re.Match[str]], headings: list[re.Match[str]]) -> None:
    """Refuse a report BECK can't read, so that a new format never reads as "nothing missing"."""
    for line in LOOKS_LIKE_HEADING.finditer(text):
        stripped = line.group(0).strip()
        if stripped != TITLE and not BLOCK_HEADING.fullmatch(line.group(0)):
            raise ReportParseError(f"Unrecognized heading in the report: {stripped}")

    # Recalbox leaves out a system with nothing to report, so a lone heading means a changed format.
    for index, system in enumerate(systems):
        end = systems[index + 1].start() if index + 1 < len(systems) else len(text)
        if not any(system.end() <= heading.start() < end for heading in headings):
            raise ReportParseError(f"No BIOS block under: {system.group(0).strip()}")

    # A report with nothing missing is just its header, so the title has to be there.
    if not headings and not any(line.strip() == TITLE for line in text.splitlines()):
        raise ReportParseError(f"This doesn't look like a report: it has no {TITLE} title")


def _system_at(systems: list[re.Match[str]], position: int) -> str | None:
    """The name in the last SYSTEM line before a position in the report."""
    name = None
    for system in systems:
        if system.start() > position:
            break
        name = system.group(1).strip()
    return name


def _why_unsafe(name: str, path: str) -> str | None:
    """Why an entry can't be trusted, if so. Its target comes from a report: it could be anything.

    On SMB a backslash separates folders too, so it could write anywhere in the share. A character
    in the other set can't be meant, and it would leave a file nobody could use or read the name of.
    """
    if not name:
        return "it has no file name"
    if name in (".", "..") or "/" in name or "\\" in name:
        return "its file name isn't only a file name"
    if not path.startswith(BIOS_ROOT):
        return f"its Path is outside {BIOS_ROOT}"
    relative = path.removeprefix(BIOS_ROOT)
    if relative.startswith("/") or ".." in relative.split("/") or "\\" in relative:
        return f"its Path could leave {BIOS_ROOT}"
    if UNSAFE_CHARACTERS.search(name + relative):
        return "it holds a control character, or a byte that wasn't valid text"
    return None


def _read(text: str) -> tuple[list[MissingBios], list[ItemError]]:
    """The safe entries, and the unsafe ones as failed items. Raises ReportParseError.

    A block with no Path or no MD5 means BECK can't read the format, so that stops the whole run.
    """
    # A BOM would hide a heading on the first line, because "^" wouldn't match there.
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    systems = list(SYSTEM_LINE.finditer(text))
    headings = list(BLOCK_HEADING.finditer(text))
    _check_format(text, systems, headings)
    missing = []
    rejected = []

    for heading, following in zip(headings, [*headings[1:], None], strict=False):
        block = text[heading.end() : following.start() if following else len(text)]
        first_line = heading.group(0).strip()
        name = heading.group(3).strip()
        location = PATH_LINE.search(block)
        md5_list = block.partition(MD5_LIST)[2]
        md5s = frozenset(md5.lower() for md5 in MD5.findall(md5_list))
        current = CURRENT_MD5_LINE.search(block)

        if location is None:
            raise ReportParseError(f"No Path line in report block: {first_line}")
        if not md5s:
            raise ReportParseError(f"No MD5 value in report block: {first_line}")

        # A Path line can list two locations ("<path> or <path>"): use the first (DEC-50).
        first_path = location.group(1).split(" or ")[0].strip()
        reason = _why_unsafe(name, first_path)
        if reason is not None:
            item = name or first_line
            rejected.append(
                ItemError(item=item, message=f"Refused {item}: {reason}", code="unsafe_path")
            )
            continue
        folder = first_path.removeprefix(BIOS_ROOT).rpartition("/")[0]

        try:
            entry = MissingBios(
                name=name,
                target=PurePosixPath(folder) / name,
                md5s=md5s,
                required=heading.group(2) == "REQUIRED",
                system=_system_at(systems, heading.start()),
                incorrect=heading.group(1) == "INCORRECT",
                current_md5=current.group(1).lower() if current else None,
            )
        except ValueError as e:
            raise ReportParseError(f"Can't read report block: {first_line}") from e
        missing.append(entry)

    return missing, rejected


def _api_entry(system: str, key: str, bios: Any) -> MissingBios | ItemError | None:
    """One BIOS from the API as the report would list it: missing, incorrect, or nothing.

    The report lists a file that isn't there, and one with a wrong MD5 only where the MD5 must match
    (``hashMatchingMandatory``). That's what keeps it equal to the report, which 10.1.1 shows.
    """
    status = bios["realStatus"]
    if status not in API_STATUSES:
        raise ReportParseError(f"Unknown status {status!r} for {key} in the web API's answer")
    incorrect = status == "HashNotMatching"
    if status == "HashMatching" or (incorrect and not bios["hashMatchingMandatory"]):
        return None
    # Like a Path line with two locations, the first one is where BECK writes (DEC-50). Recalbox
    # 10.1.1 gives paths from the BIOS folder, and newer code may give them whole.
    first_path = key.split("|")[0].strip()
    if not first_path.startswith("/"):
        first_path = BIOS_ROOT + first_path
    name = first_path.rpartition("/")[2]
    reason = _why_unsafe(name, first_path)
    if reason is not None:
        return ItemError(
            item=name or key, message=f"Refused {name or key}: {reason}", code="unsafe_path"
        )
    md5s = frozenset(md5.lower() for md5 in bios["md5List"] if MD5.fullmatch(md5))
    current = bios["currentMd5"].lower()
    if not md5s:
        raise ReportParseError(f"No MD5 value for {key} in the web API's answer")
    return MissingBios(
        name=name,
        target=PurePosixPath(first_path.removeprefix(BIOS_ROOT)),
        md5s=md5s,
        required=bool(bios["mandatory"]),
        system=system,
        incorrect=incorrect,
        current_md5=current
        if incorrect and MD5.fullmatch(current) and current.strip("0")
        else None,
    )


class RecalboxAdapter:
    """Reads the report Recalbox writes from main menu > BIOS CHECKING > REPORT."""

    name = "recalbox"
    report_path = PurePosixPath("missing_bios_report.txt")
    api_port: int | None = API_PORT
    api_path = API_PATH

    def parse_report(self, text: str) -> list[MissingBios]:
        """Turn a report into one entry per ``MISSING`` or ``INCORRECT`` block, in order. Pure.

        Candidate MD5s come only from below ``Possible MD5 List:``. An INCORRECT block's
        ``Current MD5:`` is the hash of the wrong file, so it must never become a candidate.
        An entry that isn't safe isn't here: see ``rejected_entries``.
        """
        return _read(text)[0]

    def rejected_entries(self, text: str) -> list[ItemError]:
        """The entries that aren't safe to act on, one failed item each. Pure."""
        return _read(text)[1]

    def parse_api(self, raw: bytes) -> tuple[list[MissingBios], list[ItemError]]:
        """What ``GET /api/bios`` lists, as the report would: entries, and those refused. Pure.

        The answer is ``{system: {"fullName", "biosList": {path: bios}}}``. An answer in another
        form raises ReportParseError, so that BECK can read the report instead.
        """
        try:
            systems = json.loads(raw)
            missing: list[MissingBios] = []
            rejected: list[ItemError] = []
            for system in systems.values():
                for key, bios in system["biosList"].items():
                    item = _api_entry(str(system["fullName"]), str(key), bios)
                    if isinstance(item, MissingBios):
                        missing.append(item)
                    elif item is not None:
                        rejected.append(item)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ReportParseError(f"BECK can't read the web API's answer: {e}") from e
        return missing, rejected
