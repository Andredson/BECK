---
name: cut-release
description: Prepare a BECK release by bumping the version and regenerating the changelog and command reference, then hand the push and tag to the owner. Use when asked to cut, prepare or publish a release or a release candidate.
license: GPL-3.0-only
compatibility: Needs git and uv. Publishing needs the owner, who pushes the tag and approves it.
---

# Cut a release

This does the agent's part of [the release checklist](../../../docs/releasing.md#the-release-checklist). **You prepare a release. You never publish one.** A pushed tag publishes it, which can't be undone, because PyPI never accepts a version twice.

## When to use

Someone asks you to cut, prepare or publish a release or a release candidate. If they ask you to publish it, do this, and tell them the last part is theirs.

## Inputs you need from the human

- **The version, or which kind of bump.** [The rules](../../../docs/releasing.md#version-numbers) say which one a change needs, so propose one and let them decide. **The first public version is always theirs to choose.**
- **A branch.** Ask them to create one, as one line: `git switch main && git pull && git switch -c release/X.Y.Z`.

## Steps

1. **Check that it's ready.** You're on the branch they created, `git status` is clean, and `main`'s last CI run is green (`gh run list --branch main --workflow CI --limit 1`). Check `.trivyignore` for an expiry coming up. A final release needs a release candidate that went well, except for a small patch, if the owner says so. Check that the `testpypi` and `pypi` environments exist, and that `pypi` has a required reviewer: `gh api repos/Andredson/BECK/environments`. **GitHub creates a missing environment by itself when a tag runs, with no approval gate,** so if they aren't there, tell the owner before they tag. You can't see the [trusted publishers](../../../roadmap/10-packaging-and-release.md#101--check-the-pypi-name-and-set-up-trusted-publishing-human-only), so ask whether they exist. Without them, the publish fails.
2. **Bump the version** with [`uv version`](../../../docs/releasing.md#where-the-version-lives), never by hand:

   ```sh
   uv version --bump minor --bump rc      # 0.5.0 → 0.6.0rc1
   uv version --bump stable               # 0.6.0rc1 → 0.6.0
   uv version 0.6.0rc1                    # an exact version, as for the first public one
   ```

3. **Regenerate what depends on it:**

   ```sh
   uv run python scripts/gen_cli_reference.py
   uvx --exclude-newer "14 days" git-cliff@2.14.2 --tag "v$(uv version --short)" -o CHANGELOG.md
   ```

4. **Read the result.** `CHANGELOG.md` starts with this version and not `Unreleased`. Read its `Breaking` lines as a user would. Commit messages are short, so if one doesn't say what changed for them, give the owner wording for the release notes. Don't edit `CHANGELOG.md`.
5. **Run [the quality gates](../quality-gates/SKILL.md),** including the `package` job.
6. **Commit, and don't push:**

   ```sh
   git add pyproject.toml uv.lock CHANGELOG.md docs/cli-reference.md
   git commit -m "chore(release): $(uv version --short)"
   ```

7. **Stop, and hand over.** Print these for the owner, with the real version, each as one line:

   ```sh
   git push -u origin release/X.Y.Z && gh pr create --base main --title "chore(release): X.Y.Z" --body "Release X.Y.Z."
   ```

   And after CI is green and the PR is merged with a merge commit:

   ```sh
   git switch main && git pull --ff-only && git log -1 --format=%s | grep -F "release/X.Y.Z" && git tag -a vX.Y.Z -m "beck-bios X.Y.Z" && git push origin vX.Y.Z
   ```

   It tags only if `main`'s last commit is the release PR's merge, as [step 4](../../../docs/releasing.md#the-release-checklist) explains. The branch has to be named `release/X.Y.Z` for that check to work.

   Tell them what comes next: a final release waits for them to approve the `pypi` environment, a release candidate goes to TestPyPI with no approval, and then [step 6 of the checklist](../../../docs/releasing.md#the-release-checklist) checks the result.

## Verify

- `uv lock --check` passes, and `git log -1 --format=%B` is `chore(release): X.Y.Z`, with no attribution line.
- `git status` is clean, and the branch hasn't been pushed.
- `git tag` shows no new tag.

## Never do

Even if you're asked to, and even if you have the access, these are the owner's (DEC-43):

- **Push the release, or any tag.** Don't run `git tag`, or `git push` on this branch.
- **Open or merge a PR,** create a GitHub Release, or approve an environment.
- **Edit the version by hand,** or edit `CHANGELOG.md`.
- **Reuse a version, or move a tag.** A mistake gets a new version.
- **Add a token or a secret** to make a publish work. Publishing uses trusted publishing only.
