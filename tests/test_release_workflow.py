# SPDX-License-Identifier: GPL-3.0-only
"""Who can do what in the release workflow. Its publishing jobs only run for a real tag.

Parsing uses regular expressions on purpose, as in test_workflow_pins.py: no YAML library is needed.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
MAINTENANCE = (ROOT / "docs" / "maintenance.md").read_text(encoding="utf-8")
RELEASING = (ROOT / "docs" / "releasing.md").read_text(encoding="utf-8")
PUBLISHERS = ("publish-testpypi", "publish-pypi")


def jobs(workflow: str = WORKFLOW) -> dict[str, str]:
    """Each job's text, by its name."""
    body = workflow.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z-]+):\n", body, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_these_are_the_jobs() -> None:
    assert list(jobs()) == ["build", *PUBLISHERS, "github-release"]


def test_it_runs_on_tags_and_no_other_push() -> None:
    assert 'push:\n    tags: ["v*"]\n' in WORKFLOW
    assert "branches" not in WORKFLOW.split("\npermissions:", 1)[0]


def test_nothing_is_allowed_unless_a_job_says_so() -> None:
    assert "\npermissions: {}\n" in WORKFLOW


def test_only_the_publishers_get_an_identity_pypi_trusts() -> None:
    assert [name for name, job in jobs().items() if "id-token: write" in job] == list(PUBLISHERS)


def test_only_the_github_release_can_write_to_the_repository() -> None:
    assert [name for name, job in jobs().items() if "contents: write" in job] == ["github-release"]


@pytest.mark.parametrize("name", PUBLISHERS)
def test_a_publisher_runs_nothing_of_the_projects(name: str) -> None:
    job = jobs()[name]

    assert "run:" not in job
    assert "actions/checkout" not in job
    assert "setup-uv" not in job


def test_there_are_no_stored_secrets() -> None:
    assert "secrets." not in WORKFLOW
    assert "password" not in WORKFLOW


@pytest.mark.parametrize("name", PUBLISHERS)
def test_a_publisher_only_gets_the_packages(name: str) -> None:
    job = jobs()[name]

    assert "name: dist\n" in job
    assert "name: sbom\n" not in job


def test_only_rc_tags_go_to_testpypi() -> None:
    job = jobs()["publish-testpypi"]

    assert "startsWith(github.ref, 'refs/tags/v') && contains(github.ref_name, 'rc')" in job
    assert "name: testpypi\n" in job
    assert "repository-url: https://test.pypi.org/legacy/" in job


def test_only_final_tags_go_to_pypi_through_the_approved_environment() -> None:
    job = jobs()["publish-pypi"]

    assert "startsWith(github.ref, 'refs/tags/v') && !contains(github.ref_name, 'rc')" in job
    assert "name: pypi " in job
    assert "repository-url" not in job


def test_the_build_checks_the_tag_before_building() -> None:
    job = jobs()["build"]

    check = 'test "$GITHUB_REF_NAME" = "v$(uv version --short)"'
    assert check in job
    assert job.index(check) < job.index("run: uv build")
    assert "twine check --strict dist/*" in job


def test_the_sbom_stays_out_of_what_is_published() -> None:
    job = jobs()["build"]

    assert '--output "sbom/' in job
    assert "--output dist" not in job
    assert '--output "dist' not in job


def test_the_release_comes_after_publishing_and_never_after_a_failure() -> None:
    job = jobs()["github-release"]

    assert "needs: [publish-testpypi, publish-pypi]" in job
    assert "needs.publish-testpypi.result == 'success'" in job
    assert "needs.publish-pypi.result == 'success'" in job


def test_release_notes_run_from_the_last_final_release() -> None:
    # `git-cliff --latest` gives a final only what changed since its rc (step 10.6).
    job = jobs()["github-release"]

    assert "--exclude '*rc*'" in job
    assert "--latest" not in job


def test_git_cliff_has_one_version_here_and_in_the_routine() -> None:
    pinned = re.search(r'GIT_CLIFF_VERSION: "([^"]+)"', WORKFLOW)
    documented = re.findall(r"git-cliff@([0-9.]+)", MAINTENANCE + RELEASING)

    assert pinned is not None
    assert len(documented) >= 2
    assert set(documented) == {pinned.group(1)}


def test_the_checklist_names_who_does_each_step() -> None:
    steps = re.findall(r"^\d\. \*\*.+$", RELEASING.split("## The release checklist", 1)[1], re.M)

    assert len(steps) == 6
    assert all(re.search(r"\*\((Agent|Owner|Anyone)", step) for step in steps)


def test_the_checklist_puts_the_changes_under_the_version() -> None:
    # Without --tag, a released CHANGELOG.md calls them Unreleased (step 10.7).
    assert '--tag "v$(uv version --short)" -o CHANGELOG.md' in RELEASING


def test_only_the_owner_pushes_a_tag_or_approves() -> None:
    steps = RELEASING.split("## The release checklist", 1)[1].split("### If something", 1)[0]
    tagging = steps[steps.index("4. **Tag it.**") : steps.index("5. **Approve")]
    approving = steps[steps.index("5. **Approve") : steps.index("6. **Check the result")]

    assert "*(Owner)*" in tagging
    assert "git push origin vX.Y.Z" in tagging
    assert "*(Owner, final releases only)*" in approving


def test_a_job_list_comes_apart_correctly() -> None:
    assert jobs("name: x\n\njobs:\n  one:\n    a: 1\n  two-three:\n    b: 2\n") == {
        "one": "    a: 1\n",
        "two-three": "    b: 2\n",
    }
