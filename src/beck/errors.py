# SPDX-License-Identifier: GPL-3.0-only
"""Errors BECK expects, each with a fixed exit code and JSON code.

Library code raises them; only cli.py exits.

An exception that isn't a BeckError is unexpected, and exits with code 1.
"""

from typing import ClassVar


class BeckError(Exception):
    """An error with a message for the user."""

    exit_code: ClassVar[int] = 1
    code: ClassVar[str] = "internal"


class UsageError(BeckError):
    """The command line is wrong."""

    exit_code: ClassVar[int] = 2
    code: ClassVar[str] = "usage"


class ConfigError(BeckError):
    """The settings are missing or invalid."""

    exit_code: ClassVar[int] = 2
    code: ClassVar[str] = "config"


class TransportError(BeckError):
    """The target can't be reached, or a file operation on it failed."""

    exit_code: ClassVar[int] = 3
    code: ClassVar[str] = "transport"


class ReportNotFoundError(BeckError):
    """The target has no missing-BIOS report."""

    exit_code: ClassVar[int] = 4
    code: ClassVar[str] = "report_not_found"


class ReportParseError(BeckError):
    """The missing-BIOS report has a block BECK can't read."""

    exit_code: ClassVar[int] = 4
    code: ClassVar[str] = "report_parse"
