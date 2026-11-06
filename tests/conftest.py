"""Shared test helpers: load the report fixtures in tests/fixtures/reports/."""

import json
from pathlib import Path
from typing import Any

import pytest

REPORTS = Path(__file__).resolve().parent / "fixtures" / "reports"
REAL_REPORT = "recalbox-10.1.1/default-install"
NO_SETTINGS_FOLDER = "/nonexistent/beck-tests-have-no-settings"
SETTINGS_VARIABLES = (
    "BECK_CONFIG",
    "BECK_TARGET",
    "BECK_TARGET_DIR",
    "BECK_SOURCE",
    "BECK_SMB_USER",
    "BECK_SMB_PASSWORD",
)
REPORT_NAMES = sorted(
    p.relative_to(REPORTS).with_suffix("").as_posix() for p in REPORTS.rglob("*.txt")
)


def isolate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Results can't depend on who runs them: no settings from the shell or the home folder."""
    monkeypatch.setenv("XDG_CONFIG_HOME", NO_SETTINGS_FOLDER)
    for name in SETTINGS_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_settings_from_the_user(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_settings(monkeypatch)


@pytest.fixture(autouse=True)
def no_color_settings_from_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """Results can't depend on the shell: FORCE_COLOR there would break output checks."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)


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
