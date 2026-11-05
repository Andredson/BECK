"""Fail if the repository tracks files it must never contain (step 02.8, DEC-28).

There are no git hooks in this project, so CI runs this guard on every PR. It checks every file
in the git index (committed or staged) for:

- BIOS/ROM-type files: copyrighted, never allowed (see AGENTS.md "Legal");
- anything inside ``bios/`` except ``bios/.keep``;
- files larger than 1 MiB;
- a real (non-example) BECK config file, which may contain credentials.

Usage: ``uv run python scripts/check_repo_hygiene.py``.
Exits 0 when clean, or 1 after printing one line per problem.
"""

import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 1024 * 1024
BIOS_EXTENSIONS = frozenset({".bin", ".rom", ".img", ".zip", ".7z", ".pup", ".chd", ".iso"})
CONFIG_NAMES = frozenset({"config.yml", "config.yaml", "config.toml"})

# Temporary exceptions. Each entry says which roadmap step removes it. Empty since step 03.2.
ALLOWED: dict[str, str] = {}


def find_problems(entries: Iterable[tuple[str, int]]) -> list[str]:
    """Return one message per problem for (posix path, size in bytes) entries."""
    problems: list[str] = []
    for path, size in entries:
        if path in ALLOWED:
            continue
        posix = PurePosixPath(path)
        if posix.suffix.lower() in BIOS_EXTENSIONS:
            problems.append(f"{path}: BIOS/ROM-type file ({posix.suffix}); never commit BIOS files")
        if posix.parts[0] == "bios" and path != "bios/.keep":
            problems.append(f"{path}: only bios/.keep may be tracked inside bios/")
        if size > MAX_BYTES:
            problems.append(f"{path}: {size:,} bytes is over the {MAX_BYTES:,}-byte limit")
        if posix.name in CONFIG_NAMES and posix.parts[0] != ".github":
            problems.append(
                f"{path}: real config file may hold credentials; track an *.example.* copy"
            )
    return problems


def tracked_entries(root: Path = ROOT) -> list[tuple[str, int]]:
    """(path, size) for every file in the git index; size 0 if it's missing from the work tree."""
    git = shutil.which("git")
    if git is None:
        raise SystemExit("git is required to run this check")
    listing = subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [git, "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout.decode()
    entries: list[tuple[str, int]] = []
    for path in filter(None, listing.split("\0")):
        file = root / path
        entries.append((path, file.stat().st_size if file.is_file() else 0))
    return entries


def main() -> int:
    entries = tracked_entries()
    problems = find_problems(entries)
    for problem in problems:
        print(f"hygiene: {problem}", file=sys.stderr)
    if problems:
        print(f"Repository hygiene FAILED: {len(problems)} problem(s).", file=sys.stderr)
        return 1
    print(f"Repository hygiene OK ({len(entries)} tracked files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
