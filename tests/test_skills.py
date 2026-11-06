# SPDX-License-Identifier: GPL-3.0-only
"""The Agent Skills follow the format, are indexed, and agree with what they copy (DEC-22).

Parsing is by line, on purpose: skills use single-line values, so no YAML library is needed.
"""

import re
from pathlib import Path

import pytest

from tests.test_docs_links import broken_links

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / ".agents" / "skills"
AGENTS = ROOT / "AGENTS.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"
CLI_GUIDE = ROOT / "docs" / "cli.md"
EXIT_CODES = SKILLS / "diagnose-missing-bios" / "references" / "exit-codes.md"
QUALITY_GATES = SKILLS / "quality-gates" / "SKILL.md"

SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
INDEX_ROW = re.compile(r"^\| `([^`]+)` \| \[`([^`]+)`\]\(([^)]+)\) \| .+ \|$")

# Steps that only make sense on a CI runner: installing tools, waiting and showing logs.
CI_ONLY = re.compile(
    r"""^(?:echo\ |test\ "\$RESULT"|curl\ |"https://|mkdir\ |tar\ |for\ attempt|if\ timeout|
    exit\ |sleep\ |done$|fi$|podman\ logs)""",
    re.VERBOSE,
)
# CI sets this in the step's ``env:``, and a local command has to set it on its own line.
CI_SETS_THIS = "VIRTUAL_ENV=.venv "
# What a local run needs that CI doesn't: the two tests of CI's are joined in one line there.
LOCAL_ONLY = (
    "podman rm -f beck-samba",
    "for attempt in $(seq 1 30); do timeout 1 bash -c",
    "BECK_TEST_SMB_HOST=127.0.0.1 BECK_TEST_SMB_PORT=4450 bash -eo pipefail -c",
    "rm -f pytest-output.txt",
    "COMMITIZEN_VERSION=$(sed",
    "TWINE_VERSION=$(sed",
    "rm -rf dist",
)


def frontmatter(text: str) -> dict[str, str]:
    """The fields between the ``---`` lines. Raises ValueError for what the format doesn't allow."""
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("no frontmatter between --- lines")
    fields: dict[str, str] = {}
    for line in lines[1 : lines.index("---", 1)]:
        key, separator, value = line.partition(": ")
        if not separator or line.startswith((" ", "\t")):
            raise ValueError(f"not a single-line key and value: {line!r}")
        if ": " in value:
            raise ValueError(f"{key}: a colon followed by a space isn't valid YAML")
        fields[key] = value
    return fields


def problems_with(folder: Path) -> list[str]:
    """Everything wrong with one skill's folder."""
    skill = folder / "SKILL.md"
    if not skill.is_file():
        return [f"{folder.name}: no SKILL.md"]
    try:
        fields = frontmatter(skill.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"{folder.name}: {e}"]
    problems = [f"{folder.name}: {key} isn't in the spec" for key in set(fields) - SPEC_FIELDS]
    name = fields.get("name", "")
    if not NAME.fullmatch(name) or len(name) > MAX_NAME:
        problems.append(f"{folder.name}: {name!r} isn't a valid name")
    if name != folder.name:
        problems.append(f"{folder.name}: its name is {name!r}, not the folder's")
    if not 1 <= len(fields.get("description", "")) <= MAX_DESCRIPTION:
        problems.append(f"{folder.name}: description must have 1-{MAX_DESCRIPTION} characters")
    if len(fields.get("compatibility", "")) > MAX_COMPATIBILITY:
        problems.append(f"{folder.name}: compatibility is over {MAX_COMPATIBILITY} characters")
    return problems


def skill_folders(root: Path = SKILLS) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir())


def index_rows(agents_text: str) -> dict[str, tuple[str, str]]:
    """Each row of the skills index: its name, and the two forms of its path."""
    section = agents_text.split("### Skills\n", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        if line.startswith("|") and not line.startswith(("| Skill ", "|---")):
            match = INDEX_ROW.match(line)
            if match is None:
                raise ValueError(f"Not a row of the index: {line}")
            rows[match.group(1)] = (match.group(2), match.group(3))
    return rows


def table_after(text: str) -> list[str]:
    """The first Markdown table in a text."""
    rows: list[str] = []
    for line in text.splitlines():
        if line.startswith("|"):
            rows.append(line)
        elif rows:
            break
    return rows


def _squeezed(text: str) -> str:
    return " ".join(text.split())


def ci_commands(workflow: str) -> list[str]:
    """What a workflow runs: each ``run:``, with folded lines joined, and block lines one by one."""
    lines = workflow.splitlines()
    commands: list[str] = []
    for number, line in enumerate(lines):
        match = re.match(r"(\s*)(?:- )?run: (.*)$", line)
        if match is None:
            continue
        indent, value = match.groups()
        block = []
        for following in lines[number + 1 :]:
            if not following.startswith(indent + "  ") or following.lstrip().startswith("- "):
                break
            block.append(following.strip())
        if value == ">-":
            commands.append(_squeezed(" ".join(block)))
        elif value == "|":
            commands += block
        else:
            commands.append(_squeezed(value))
    return commands


def commands_to_compare(workflow: str) -> list[str]:
    """CI's commands, with the range of commits a PR has written the way a local run does."""
    return [
        command.replace("${BASE_SHA}..${HEAD_SHA}", "origin/main..HEAD")
        for command in ci_commands(workflow)
        if not CI_ONLY.match(command)
    ]


def skill_commands(skill_text: str) -> list[str]:
    """The lines of a skill's ``sh`` blocks."""
    return [
        line.strip()
        for block in re.findall(r"^ *```sh\n(.*?)^ *```", skill_text, re.DOTALL | re.MULTILINE)
        for line in block.splitlines()
        if line.strip()
    ]


def test_there_are_skills_to_check() -> None:
    assert {folder.name for folder in skill_folders()} >= {
        "execute-roadmap-step",
        "quality-gates",
        "add-report-fixture",
        "add-frontend-adapter",
        "diagnose-missing-bios",
    }


def test_the_folder_holds_only_skills_and_its_readme() -> None:
    files = {path.name for path in SKILLS.iterdir() if not path.is_dir()}

    assert files == {"README.md"}


@pytest.mark.parametrize("folder", skill_folders(), ids=lambda folder: folder.name)
def test_a_skill_follows_the_format(folder: Path) -> None:
    assert problems_with(folder) == []


def _skill(tmp_path: Path, text: str, name: str = "a-skill") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    (folder / "SKILL.md").write_text(text, encoding="utf-8")
    return folder


def _fields(*lines: str) -> str:
    return "\n".join(["---", *lines, "---", "", "# A skill"]) + "\n"


GOOD = ("name: a-skill", "description: Does a thing. Use when asked.")


def test_a_good_skill_has_no_problems(tmp_path: Path) -> None:
    fields = _fields(*GOOD, "license: GPL-3.0-only", "compatibility: Needs git.")

    assert problems_with(_skill(tmp_path, fields)) == []


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("# No frontmatter\n", "no frontmatter"),
        ("---\nname: a-skill\n", "no frontmatter"),
        ("", "no frontmatter"),
        (_fields("description: Does a thing."), "isn't a valid name"),
        (_fields("name: another-skill", GOOD[1]), "not the folder's"),
        (_fields(GOOD[0]), "description must have"),
        (_fields(GOOD[0], "description: " + "x" * (MAX_DESCRIPTION + 1)), "description must have"),
        (_fields(*GOOD, "author: Someone"), "author isn't in the spec"),
        (
            _fields(*GOOD, "compatibility: " + "x" * (MAX_COMPATIBILITY + 1)),
            "compatibility is over",
        ),
        (_fields(GOOD[0], "description: Use this when: asked."), "isn't valid YAML"),
        (_fields(*GOOD, "metadata:", "  author: Someone"), "single-line"),
        (_fields(*GOOD, "just some words"), "single-line"),
    ],
    ids=[
        "no-frontmatter",
        "never-closed",
        "empty-file",
        "no-name",
        "name-is-not-the-folder",
        "no-description",
        "long-description",
        "unknown-field",
        "long-compatibility",
        "colon-and-space",
        "several-lines",
        "not-a-field",
    ],
)
def test_a_bad_skill_is_refused(tmp_path: Path, text: str, complaint: str) -> None:
    assert complaint in " ".join(problems_with(_skill(tmp_path, text)))


@pytest.mark.parametrize(
    "name",
    ["Upper", "-start", "end-", "two--hyphens", "under_score", "x" * (MAX_NAME + 1)],
)
def test_a_bad_name_is_refused(tmp_path: Path, name: str) -> None:
    fields = _fields(f"name: {name}", GOOD[1])

    assert "isn't a valid name" in " ".join(problems_with(_skill(tmp_path, fields, name)))


def test_the_longest_name_is_allowed(tmp_path: Path) -> None:
    name = "x" * MAX_NAME

    assert problems_with(_skill(tmp_path, _fields(f"name: {name}", GOOD[1]), name)) == []


def test_a_folder_without_a_skill_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()

    assert problems_with(folder) == ["empty: no SKILL.md"]


@pytest.mark.parametrize(
    "path",
    sorted(SKILLS.rglob("*.md")),
    ids=lambda path: path.relative_to(SKILLS).as_posix(),
)
def test_links_in_a_skill_resolve(path: Path) -> None:
    assert broken_links(path) == []


def test_every_skill_is_in_the_index_and_every_row_is_a_skill() -> None:
    rows = index_rows(AGENTS.read_text(encoding="utf-8"))

    assert set(rows) == {folder.name for folder in skill_folders()}


def test_every_row_of_the_index_points_to_its_own_skill() -> None:
    for name, paths in index_rows(AGENTS.read_text(encoding="utf-8")).items():
        expected = f".agents/skills/{name}/SKILL.md"
        assert paths == (expected, expected)
        assert (ROOT / expected).is_file()


def test_a_row_that_is_not_in_the_index_format_is_refused() -> None:
    with pytest.raises(ValueError, match="Not a row"):
        index_rows("### Skills\n\n| *(none yet)* | | |\n\n## Code style\n")


def test_the_index_stops_at_the_next_section() -> None:
    text = "### Skills\n\n| `a` | [`p`](p) | When. |\n\n## Code style\n\n| b | c |\n"

    assert index_rows(text) == {"a": ("p", "p")}


def test_the_exit_codes_in_the_skill_are_the_ones_in_the_guide() -> None:
    guide = table_after(CLI_GUIDE.read_text(encoding="utf-8").split("## Exit codes\n", 1)[1])

    assert table_after(EXIT_CODES.read_text(encoding="utf-8")) == guide
    assert len(guide) == len(["heading", "separator", 0, 1, 2, 3, 4, 5])


def test_every_ci_command_is_in_the_quality_gates_skill() -> None:
    skill = _squeezed(QUALITY_GATES.read_text(encoding="utf-8"))
    commands = commands_to_compare(CI.read_text(encoding="utf-8"))

    assert "uv run pytest --cov --cov-report=xml" in commands
    assert [command for command in commands if command not in skill] == []


def test_every_command_in_the_quality_gates_skill_is_from_ci() -> None:
    ci = commands_to_compare(CI.read_text(encoding="utf-8"))
    commands = skill_commands(QUALITY_GATES.read_text(encoding="utf-8"))

    assert "uv run mypy" in commands
    assert [
        command
        for command in commands
        if command.removeprefix(CI_SETS_THIS) not in ci and not command.startswith(LOCAL_ONLY)
    ] == []


def test_the_integration_line_in_the_skill_runs_what_ci_runs() -> None:
    line = next(c for c in skill_commands(QUALITY_GATES.read_text(encoding="utf-8")) if "tee" in c)

    assert "uv run pytest -m integration -q -rs | tee pytest-output.txt" in line
    assert '! grep -q "skipped" pytest-output.txt' in line


def test_the_commands_before_a_commit_in_agents_md_are_what_ci_runs() -> None:
    # This line once said it was what CI runs, without the coverage gate (step 09.3).
    workflow = CI.read_text(encoding="utf-8")
    jobs = workflow.split("\n  quality:\n", 1)[1].split("\n  tests-passed:\n", 1)[0]
    agents = AGENTS.read_text(encoding="utf-8")
    line = next(text for text in agents.splitlines() if text.startswith("uv sync --locked && "))

    commands = commands_to_compare(jobs)
    assert "uv run pytest --cov --cov-report=xml" in commands
    assert [command for command in commands if command not in line] == []


def test_ci_commands_come_apart_correctly() -> None:
    workflow = """
      - run: uv sync --locked
      - name: Folded
        run: >-
          trivy fs --scanners vuln
          --no-progress .
      - name: Block
        run: |
          first one
          second one
      - uses: something
        with:
          key: value
"""

    assert ci_commands(workflow) == [
        "uv sync --locked",
        "trivy fs --scanners vuln --no-progress .",
        "first one",
        "second one",
    ]


def test_a_new_ci_command_is_not_taken_for_a_runner_step() -> None:
    assert commands_to_compare("      - run: uv run something-new\n") == ["uv run something-new"]
    assert commands_to_compare("      - run: curl -sSf example\n") == []
    assert commands_to_compare('      - run: test "$RESULT" = "success"\n') == []
    assert commands_to_compare('      - run: test "$(beck --version)" = "x"\n') != []
