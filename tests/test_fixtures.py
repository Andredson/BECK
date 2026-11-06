# SPDX-License-Identifier: GPL-3.0-only
"""The report fixtures stay complete and byte-exact (step 03.4, DEC-09)."""

import re

import pytest

from tests.conftest import REAL_REPORT, REPORT_NAMES, load_expected, load_report


def test_there_are_real_and_derived_fixtures() -> None:
    assert REAL_REPORT in REPORT_NAMES
    assert sum("derived-" in name for name in REPORT_NAMES) >= 4


@pytest.mark.parametrize("name", REPORT_NAMES)
def test_expected_file_matches_the_report(name: str) -> None:
    report = load_report(name)
    expected = load_expected(name)

    assert len(expected) == len(
        re.findall(r"(?:MISSING|INCORRECT) (?:REQUIRED|OPTIONAL) BIOS: ", report)
    )
    for entry in expected:
        assert set(entry) == {"name", "path", "relativePath", "hashes"}
        assert f"BIOS: {entry['name']}" in report
        assert entry["path"] == f"/recalbox/share/bios/{entry['relativePath']}"
        assert entry["hashes"], f"{entry['name']} has no hashes"
        assert all(h in report for h in entry["hashes"])


def test_real_report_keeps_its_crlf_line_endings() -> None:
    # Fails if .gitattributes stops protecting the fixtures from line-ending conversion.
    report = load_report(REAL_REPORT)
    assert report.count("\r\n") == 2056
    assert len(load_expected(REAL_REPORT)) == 238


def test_lf_fixture_has_no_crlf() -> None:
    assert "\r" not in load_report("recalbox-10.1.1/derived-lf-endings")
