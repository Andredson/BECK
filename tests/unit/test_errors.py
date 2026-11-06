# SPDX-License-Identifier: GPL-3.0-only
"""Exit codes are a public promise (DEC-23), so each class's code is pinned here."""

import inspect

import pytest

from beck import errors

JSON_CODES: dict[type[errors.BeckError], str] = {
    errors.BeckError: "internal",
    errors.UsageError: "usage",
    errors.ConfigError: "config",
    errors.TransportError: "transport",
    errors.ReportNotFoundError: "report_not_found",
    errors.ReportParseError: "report_parse",
}

EXIT_CODES: dict[type[errors.BeckError], int] = {
    errors.BeckError: 1,
    errors.UsageError: 2,
    errors.ConfigError: 2,
    errors.TransportError: 3,
    errors.ReportNotFoundError: 4,
    errors.ReportParseError: 4,
}


@pytest.mark.parametrize(("error", "code"), EXIT_CODES.items())
def test_each_error_has_its_exit_code(error: type[errors.BeckError], code: int) -> None:
    assert error.exit_code == code
    assert error("message").exit_code == code


@pytest.mark.parametrize("error", EXIT_CODES)
def test_each_error_is_a_beck_error_and_keeps_its_message(error: type[errors.BeckError]) -> None:
    with pytest.raises(errors.BeckError, match="something went wrong"):
        raise error("something went wrong")


def test_every_error_in_the_module_has_a_pinned_code() -> None:
    defined = {
        cls
        for _, cls in inspect.getmembers(errors, inspect.isclass)
        if issubclass(cls, errors.BeckError)
    }

    assert defined == set(EXIT_CODES)


@pytest.mark.parametrize(("error", "code"), JSON_CODES.items())
def test_each_error_has_its_json_code(error: type[errors.BeckError], code: str) -> None:
    assert error.code == code


def test_every_error_class_has_a_pinned_json_code() -> None:
    classes = {
        cls
        for _, cls in inspect.getmembers(errors, inspect.isclass)
        if issubclass(cls, errors.BeckError)
    }

    assert classes == set(JSON_CODES)
