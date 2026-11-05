"""Shared test helpers: load the report fixtures in tests/fixtures/reports/."""

import json
from pathlib import Path
from typing import Any

import pytest

import check_bios

REPORTS = Path(__file__).resolve().parent / "fixtures" / "reports"
REAL_REPORT = "recalbox-10.1.1/default-install"
REPORT_NAMES = sorted(str(p.relative_to(REPORTS).with_suffix("")) for p in REPORTS.glob("*/*.txt"))


def load_report(name: str) -> str:
    """A report's text; ``name`` is like ``recalbox-10.1.1/default-install``. CRLF is preserved."""
    # read_bytes + decode: read_text would turn CRLF into LF and hide line-ending bugs.
    return (REPORTS / f"{name}.txt").read_bytes().decode("utf-8")


def load_expected(name: str) -> list[dict[str, Any]]:
    """The entries the parser must produce for a report, in report order."""
    expected: list[dict[str, Any]] = json.loads(
        (REPORTS / f"{name}.expected.json").read_text(encoding="utf-8")
    )
    return expected


def use_folder(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    """Make check_bios use ``folder/config/config.yml`` and ``folder/bios``, not the repo's."""
    monkeypatch.setattr(check_bios, "CONFIG_PATH", folder / "config" / "config.yml")
    monkeypatch.setattr(check_bios, "BIOS_DIR", folder / "bios")
