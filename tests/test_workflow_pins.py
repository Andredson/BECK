"""Pins repeated across GitHub workflows must agree, so a refresh can't miss one file.

Also checks that every third-party action is pinned to a full commit SHA (DEC-34, DEC-35,
DEC-48). Parsing uses regular expressions on purpose: no YAML library is needed (PyYAML goes
away in stage 07, DEC-24).
"""

import re
from collections import defaultdict
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# `NAME_VERSION: "x"` or `NAME_SHA256: "x"` in an `env:` block.
ENV_PIN = re.compile(r'^\s+([A-Z][A-Z0-9_]*_(?:VERSION|SHA256)):\s*"([^"]+)"', re.MULTILINE)
# `uses: owner/repo[/path]@ref  # comment`; local (`./…`) and docker:// actions don't match.
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*([\w.-]+/[\w./-]+)@(\S+)(?:\s+#\s*(\S+))?", re.MULTILINE)
FULL_SHA = re.compile(r"[0-9a-f]{40}")


def workflow_files(directory: Path) -> list[Path]:
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])


def mismatched_env_pins(files: list[Path]) -> dict[str, set[str]]:
    """Env pins whose value differs between (or within) workflow files."""
    values: dict[str, set[str]] = defaultdict(set)
    for f in files:
        for name, value in ENV_PIN.findall(f.read_text(encoding="utf-8")):
            values[name].add(value)
    return {name: vals for name, vals in values.items() if len(vals) > 1}


def mismatched_actions(files: list[Path]) -> dict[str, set[str]]:
    """Actions used with more than one ref (or version comment) across workflow files."""
    refs: dict[str, set[str]] = defaultdict(set)
    for f in files:
        for action, ref, comment in USES.findall(f.read_text(encoding="utf-8")):
            refs[action].add(f"{ref} # {comment}")
    return {action: r for action, r in refs.items() if len(r) > 1}


def unpinned_actions(files: list[Path]) -> list[str]:
    """`uses:` lines whose ref isn't a full 40-character commit SHA."""
    return [
        f"{f.name}: {action}@{ref}"
        for f in files
        for action, ref, _ in USES.findall(f.read_text(encoding="utf-8"))
        if not FULL_SHA.fullmatch(ref)
    ]


def test_repository_has_workflows() -> None:
    assert len(workflow_files(WORKFLOWS)) >= 2


def test_env_pins_match_across_workflows() -> None:
    assert mismatched_env_pins(workflow_files(WORKFLOWS)) == {}


def test_actions_use_the_same_pin_everywhere() -> None:
    assert mismatched_actions(workflow_files(WORKFLOWS)) == {}


def test_actions_are_pinned_to_full_commit_shas() -> None:
    assert unpinned_actions(workflow_files(WORKFLOWS)) == []


def test_checks_detect_drift(tmp_path: Path) -> None:
    sha_a, sha_b = "a" * 40, "b" * 40
    (tmp_path / "one.yml").write_text(
        f'env:\n  TOOL_VERSION: "1.0.0"\njobs:\n  x:\n    steps:\n'
        f"      - uses: owner/action@{sha_a} # v1\n",
        encoding="utf-8",
    )
    (tmp_path / "two.yml").write_text(
        f'env:\n  TOOL_VERSION: "1.0.1"\njobs:\n  x:\n    steps:\n'
        f"      - uses: owner/action@{sha_b} # v2\n"
        "      - uses: owner/other@v3\n"
        "      - uses: ./.github/actions/local\n",
        encoding="utf-8",
    )
    files = workflow_files(tmp_path)
    assert mismatched_env_pins(files) == {"TOOL_VERSION": {"1.0.0", "1.0.1"}}
    assert mismatched_actions(files) == {"owner/action": {f"{sha_a} # v1", f"{sha_b} # v2"}}
    assert unpinned_actions(files) == ["two.yml: owner/other@v3"]
