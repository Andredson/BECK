# SPDX-License-Identifier: GPL-3.0-only
"""What a frontend adapter provides. Each retro-gaming system gets one (DEC-03)."""

from pathlib import PurePosixPath
from typing import Protocol

from beck.models import ItemError, MissingBios


class FrontendAdapter(Protocol):
    """Where a system keeps its missing-BIOS report, and how to read it.

    A system whose web API lists the same, live, gives its port and path; otherwise the port is
    ``None`` (DEC-79).
    """

    name: str
    report_path: PurePosixPath  # relative to the BIOS root
    api_port: int | None
    api_path: str

    def parse_report(self, text: str) -> list[MissingBios]:
        """Turn a report's text into entries, in report order. Raises ReportParseError."""

    def rejected_entries(self, text: str) -> list[ItemError]:
        """The entries left out because they aren't safe to act on, one failed item each."""

    def parse_api(self, raw: bytes) -> tuple[list[MissingBios], list[ItemError]]:
        """What the web API lists, as ``parse_report`` and ``rejected_entries`` would give it.

        Raises ReportParseError for an answer in a form BECK doesn't know.
        """
