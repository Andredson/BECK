"""The troubleshooting guide has an entry for every exit code and every error code."""

import re
from pathlib import Path

import pytest

from beck.errors import BeckError

ROOT = Path(__file__).resolve().parent.parent
GUIDE = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
JSON_GUIDE = (ROOT / "docs" / "json-output.md").read_text(encoding="utf-8")
ERROR_CODES = re.findall(r"^\| `(\w+)` \| \d \|", JSON_GUIDE, flags=re.MULTILINE)


def test_the_list_of_error_codes_was_found() -> None:
    assert "transport" in ERROR_CODES
    assert len(ERROR_CODES) >= 9


@pytest.mark.parametrize("exit_code", range(6))
def test_every_exit_code_has_an_entry(exit_code: int) -> None:
    assert f"xit code {exit_code}" in GUIDE


@pytest.mark.parametrize("code", ERROR_CODES)
def test_every_error_code_has_an_entry(code: str) -> None:
    assert f"`{code}`" in GUIDE


@pytest.mark.parametrize(
    "error", [BeckError, *BeckError.__subclasses__()], ids=lambda e: e.__name__
)
def test_every_kind_of_error_has_an_entry_with_its_exit_code(error: type[BeckError]) -> None:
    assert f"**Exit code {error.exit_code},** `{error.code}`" in GUIDE


def test_an_entry_says_why_and_what_to_do() -> None:
    assert GUIDE.count("- **Cause:**") >= 10
    assert GUIDE.count("- **Fix:**") >= 10
