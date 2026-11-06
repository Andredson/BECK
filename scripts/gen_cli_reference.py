# SPDX-License-Identifier: GPL-3.0-only
"""Write docs/cli-reference.md from the help of the `beck` command and its subcommands."""

import argparse
import os
import textwrap
from pathlib import Path
from unittest import mock

from beck.cli import _build_parser

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "docs" / "cli-reference.md"
WIDTH = 100
# The width is fixed so that the file doesn't depend on the terminal, and color is off because
# Python 3.14 can color its help.
ENVIRONMENT = {"COLUMNS": str(WIDTH), "NO_COLOR": "1", "PYTHON_COLORS": "0"}
HEADER = """\
# Command reference

What `beck --help` and each command's `--help` print.
[The guide to the `beck` command](cli.md) explains how to use them.

This file is generated, so don't edit it by hand. After changing a flag or its help, run
`uv run python scripts/gen_cli_reference.py`.
"""


def rewrap_usage(text: str) -> str:
    """Wrap the usage block the same way on every Python: 3.13 changed where argparse breaks it."""
    usage, separator, rest = text.partition("\n\n")
    wrapped = textwrap.fill(
        " ".join(usage.split()),
        width=WIDTH,
        subsequent_indent=" " * usage.index("[-h]"),
        break_long_words=False,
        break_on_hyphens=False,
    )
    return f"{wrapped}{separator}{rest}"


def _with_subcommands(parser: argparse.ArgumentParser) -> list[argparse.ArgumentParser]:
    parsers = [parser]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for subparser in action.choices.values():
                parsers += _with_subcommands(subparser)
    return parsers


def render() -> str:
    """Return the text of the reference, whatever the terminal is like."""
    with mock.patch.dict(os.environ, ENVIRONMENT):
        sections = [
            f"## `{parser.prog}`\n\n```text\n{rewrap_usage(parser.format_help()).rstrip()}\n```\n"
            for parser in _with_subcommands(_build_parser())
        ]
    return "\n".join([HEADER, *sections])


def write(path: Path = REFERENCE) -> None:
    path.write_text(render(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write()
