"""Relative links and anchors between the repository's Markdown files must resolve (DEC-42).

Standard library only; external URLs are not checked. Anchors follow GitHub's heading-slug rule.
"""

import re
import shutil
import subprocess
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", ".mypy_cache", ".ruff_cache", ".pytest_cache", "node_modules"}

FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK_TARGET = re.compile(r"\]\(\s*<?([^)\s>]*)")  # inline links and images: ...](target)
REFERENCE_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?([^\s>]+)")  # [ref]: target
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)  # http:, mailto:, tel:, ...


def markdown_files(root: Path = ROOT) -> list[Path]:
    """Tracked and untracked-but-not-ignored Markdown files (falls back to a glob without git)."""
    git = shutil.which("git")
    if git and (root / ".git").exists():
        listing = subprocess.run(  # noqa: S603 - fixed arguments, no external input
            [git, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.md"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout.decode()
        files = {root / name for name in listing.split("\0") if name}
    else:
        files = set(root.rglob("*.md"))
    return sorted(
        p for p in files if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(root).parts)
    )


def prose_lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (line number, line) for lines outside fenced code blocks."""
    fence: str | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = FENCE.match(line)
        if match:
            marker = match.group(1)[0]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None:
            yield number, line


def slugify(heading: str) -> str:
    """GitHub's anchor for a heading: lowercase, drop punctuation, spaces become hyphens."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # a link contributes its text only
    text = re.sub(r"[^\w\- ]", "", text.lower())
    return text.replace(" ", "-")


@cache
def anchors(path: Path) -> frozenset[str]:
    """All heading anchors of a Markdown file; repeated headings get -1, -2, ... suffixes."""
    seen: dict[str, int] = {}
    found: set[str] = set()
    for _, line in prose_lines(path):
        match = HEADING.match(line)
        if not match:
            continue
        base = slugify(match.group(1))
        count = seen.get(base, 0)
        found.add(base if count == 0 else f"{base}-{count}")
        seen[base] = count + 1
    return frozenset(found)


def link_targets(line: str) -> list[str]:
    code_free = INLINE_CODE.sub("", line)
    targets = LINK_TARGET.findall(code_free)
    definition = REFERENCE_DEF.match(code_free)
    if definition:
        targets.append(definition.group(1))
    return [t for t in targets if t]


def broken_links(md: Path, root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    where = md.relative_to(root)
    for number, line in prose_lines(md):
        for target in link_targets(line):
            if EXTERNAL.match(target):
                continue
            path_part, _, anchor = target.partition("#")
            dest = (md.parent / unquote(path_part)).resolve() if path_part else md
            if not dest.is_relative_to(root.resolve()):
                problems.append(f"{where}:{number}: '{target}' points outside the repository")
            elif not dest.exists():
                problems.append(f"{where}:{number}: '{target}' -> file not found")
            elif anchor and dest.suffix.lower() == ".md" and unquote(anchor) not in anchors(dest):
                problems.append(f"{where}:{number}: '{target}' -> no heading with that anchor")
    return problems


@pytest.mark.parametrize("md", markdown_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_relative_links_resolve(md: Path) -> None:
    problems = broken_links(md)
    assert not problems, "Broken links:\n" + "\n".join(problems)


# --- the checker itself ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("heading", "slug"),
    [
        (
            "02.1 — Add `pyproject.toml` and `uv.lock` (D15)",
            "021--add-pyprojecttoml-and-uvlock-d15",
        ),
        ("Re-scoring history", "re-scoring-history"),
        ("How to execute a step (humans and agents)", "how-to-execute-a-step-humans-and-agents"),
        ("See [the log](README.md) now", "see-the-log-now"),
    ],
)
def test_slugify_matches_github(heading: str, slug: str) -> None:
    assert slugify(heading) == slug


def test_checker_reports_missing_files_and_anchors(tmp_path: Path) -> None:
    (tmp_path / "target.md").write_text(
        "# Real heading\n\n## Twice\n\n## Twice\n", encoding="utf-8"
    )
    source = tmp_path / "source.md"
    source.write_text(
        "[ok](target.md#real-heading) [dup](target.md#twice-1) [web](https://example.com)\n"
        "`[in code](nope.md)`\n"
        "```\n[in fence](nope.md)\n```\n"
        "[missing file](nope.md)\n"
        "[missing anchor](target.md#not-there)\n"
        "[escape](../outside.md)\n",
        encoding="utf-8",
    )

    problems = broken_links(source, root=tmp_path)

    assert len(problems) == 3
    assert "source.md:6: 'nope.md' -> file not found" in problems[0]
    assert "no heading with that anchor" in problems[1]
    assert "points outside the repository" in problems[2]
