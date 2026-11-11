# SPDX-License-Identifier: GPL-3.0-only
"""Every Python file says its license on its first line (DEC-13)."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HEADER = "# SPDX-License-Identifier: GPL-3.0-only"


def _git(root: Path, *arguments: str) -> str:
    git = shutil.which("git")
    assert git is not None
    return subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [git, *arguments], cwd=root, capture_output=True, check=True, text=True
    ).stdout


def python_files(root: Path) -> list[Path]:
    """The tracked files, and the new ones, so that a file fails before it's committed."""
    listing = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "*.py")
    paths = (root / name for name in listing.split("\0") if name)
    return [path for path in paths if path.exists()]


def has_header(text: str) -> bool:
    """Whether the header comes first. Only a ``#!`` line, which must be first, can precede it."""
    lines = text.splitlines()
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    return bool(lines) and lines[0] == HEADER


def test_every_python_file_has_the_header() -> None:
    without = [
        path.relative_to(ROOT).as_posix()
        for path in python_files(ROOT)
        if not has_header(path.read_text(encoding="utf-8"))
    ]

    assert without == [], f"These need {HEADER!r} as their first line"


@pytest.mark.parametrize(
    "path",
    ["scripts/__init__.py", "src/beck/cli.py", "tests/test_license_headers.py"],
)
def test_the_check_looks_at_every_part_of_the_repository(path: str) -> None:
    assert ROOT / path in python_files(ROOT)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"{HEADER}\n", True),
        (f'{HEADER}\n"""A module."""\n', True),
        (f"#!/usr/bin/env python3\n{HEADER}\n", True),
        ("", False),
        ('"""A module."""\n', False),
        (f'"""A module."""\n{HEADER}\n', False),
        (f"\n{HEADER}\n", False),
        (f"#!/usr/bin/env python3\n\n{HEADER}\n", False),
        (f"import os\n{HEADER}\n", False),
        ("# SPDX-License-Identifier: GPL-3.0-or-later\n", False),
        (f"{HEADER} or later\n", False),
        (f'"""{HEADER}"""\n', False),
    ],
    ids=[
        "alone",
        "before-a-docstring",
        "after-a-shebang",
        "empty",
        "missing",
        "after-a-docstring",
        "after-a-blank-line",
        "too-far-after-a-shebang",
        "after-code",
        "another-license",
        "more-after-it",
        "in-a-docstring",
    ],
)
def test_has_header(text: str, expected: bool) -> None:
    assert has_header(text) is expected


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    return tmp_path


def test_a_new_file_without_the_header_is_noticed(repository: Path) -> None:
    new = repository / "new.py"
    new.write_text('"""Not added to git yet."""\n', encoding="utf-8")

    assert python_files(repository) == [new]
    assert not has_header(new.read_text(encoding="utf-8"))


def test_only_python_files_are_checked(repository: Path) -> None:
    (repository / "notes.md").write_text("Not code.\n", encoding="utf-8")

    assert python_files(repository) == []


def test_an_ignored_file_is_not_checked(repository: Path) -> None:
    (repository / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (repository / "ignored.py").write_text("", encoding="utf-8")

    assert python_files(repository) == []


def test_a_file_deleted_but_still_tracked_is_not_read(repository: Path) -> None:
    gone = repository / "gone.py"
    gone.write_text("", encoding="utf-8")
    _git(repository, "add", "gone.py")

    gone.unlink()

    assert python_files(repository) == []
