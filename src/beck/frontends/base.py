"""What a frontend adapter provides. Each retro-gaming system gets one (DEC-03)."""

from pathlib import PurePosixPath
from typing import Protocol

from beck.models import ItemError, MissingBios


class FrontendAdapter(Protocol):
    """Where a system keeps its missing-BIOS report, and how to read it."""

    name: str
    report_path: PurePosixPath  # relative to the BIOS root

    def parse_report(self, text: str) -> list[MissingBios]:
        """Turn a report's text into entries, in report order. Raises ReportParseError."""

    def rejected_entries(self, text: str) -> list[ItemError]:
        """The entries left out because they aren't safe to act on, one failed item each."""
