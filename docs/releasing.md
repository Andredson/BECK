# Releasing BECK

How versions and tags work, and the checklist for a release. Agents do the preparation. Only the owner pushes a tag or approves a publish (DEC-43), so an agent stops at step 3.

## Version numbers

BECK follows [Semantic Versioning](https://semver.org/):

| Change | Before 1.0 | From 1.0 |
|---|---|---|
| A fix | Patch: `0.5.0` → `0.5.1` | Patch |
| A new feature | Minor: `0.5.0` → `0.6.0` | Minor |
| A breaking change | Minor: `0.5.0` → `0.6.0` | Major |

A change is breaking if someone's use of BECK stops working: a command or flag that's removed or changes meaning, a different [exit code](cli.md#exit-codes), or a settings file that's no longer accepted. Its commit message has a `!`, which [the changelog](maintenance.md#regenerating-the-changelog) marks. If a pushed commit lacks one, add it to `cliff.toml`.

**The `--json` output has its own version.** `schema_version` changes only for [a breaking change to that output](json-output.md#the-compatibility-promise), which needs the owner's approval. That's a breaking change for BECK's version as well.

## Where the version lives

It's in `pyproject.toml`, and `uv.lock` holds a copy. Nothing else stores it: `beck --version` and `beck_version` in `--json` read it with `importlib.metadata`.

Never edit it by hand, because the lockfile would no longer match, and CI's `uv sync --locked` would fail. Use `uv version` (DEC-18), and commit both files:

```sh
uv version --bump patch      # 0.5.0 → 0.5.1
uv version --bump minor      # 0.5.0 → 0.6.0
uv version --bump major      # 0.5.0 → 1.0.0
uv version --short           # prints the version
```

Add `--dry-run` to see the result without changing anything.

## Release candidates

A release candidate is a rehearsal, and it's published to TestPyPI only (DEC-41). Its version follows PEP 440, as in `0.6.0rc1`:

```sh
uv version --bump minor --bump rc      # 0.5.0 → 0.6.0rc1
uv version --bump rc                   # 0.6.0rc1 → 0.6.0rc2
uv version --bump stable               # 0.6.0rc2 → 0.6.0
```

`--bump rc` alone only works on a version that's already a release candidate. For the first public version, whose number the owner chooses, give it exactly: `uv version 0.6.0rc1`.

## Tags

A tag is `v` and the exact version:

| Version | Tag |
|---|---|
| `0.6.0` | `v0.6.0` |
| `0.6.0rc1` | `v0.6.0rc1` |

The release workflow fails if the tag isn't the project's version, with this check (step 10.6):

```sh
test "$GITHUB_REF_NAME" = "v$(uv version --short)"
```

Never move a tag or reuse a version. PyPI won't accept the same version twice, even after a delete, so a mistake in a release gets a new version.

## The SBOM

Each GitHub Release has a software bill of materials: a [CycloneDX](https://cyclonedx.org/) list of what BECK depends on, so that users and distributors can check it against known problems (DEC-37). Trivy makes it, at the version pinned in `.github/workflows/ci.yml`:

```sh
mkdir -p sbom
trivy fs --format cyclonedx --skip-dirs .venv --skip-files requirements.txt --output "sbom/beck-bios-$(uv version --short).cdx.json" .
```

- **What's in it:** the runtime packages in `uv.lock`, with their exact versions, and `beck-bios` itself. That's the same list as `requirements.txt`, which it skips so as not to count it twice.
- **Dev dependencies are left out.** They never reach a user's computer, and Trivy has no way to label them as dev, so including them would make them look like part of BECK.
- **It goes in `sbom/`, not `dist/`.** `twine check dist/*` fails on anything that isn't a package, and the upload to PyPI takes the whole folder.
- **What it doesn't have:** licenses, because `uv.lock` doesn't hold them. Its top-level name is `.`, from the path Trivy was given, so the file's name and the `beck-bios` entry are what say what it describes.

## The release checklist

`X.Y.Z` is the version, which can be a release candidate like `0.6.0rc1`. A release candidate goes through the same steps, except that it publishes to TestPyPI with no approval.

1. **Check that it's ready.** *(Agent or owner)* The planned stages are closed, `main` is green, and for a final release, its release candidate went well. Look at any open `.trivyignore` expiry.

2. **Prepare the release.** *(Agent)* On a branch the owner has created, bump the version as [above](#where-the-version-lives), regenerate what depends on it, and commit:

   ```sh
   uv run python scripts/gen_cli_reference.py
   uvx --exclude-newer "14 days" git-cliff@2.14.2 --tag "v$(uv version --short)" -o CHANGELOG.md
   git add pyproject.toml uv.lock CHANGELOG.md docs/cli-reference.md
   git commit -m "chore(release): $(uv version --short)"
   ```

   `--tag` is what puts the changes under this version, not under `Unreleased`, which would then be in the released package. The commit needs [the quality gates](../.agents/skills/quality-gates/SKILL.md) to pass first. **Check:** `CHANGELOG.md` starts with this version, and its `Breaking` lines say what a user needs to know.

3. **Merge it.** *(Owner)* Push the branch, open the PR, and merge it with a merge commit. **Check:** CI is green, including `package`.

4. **Tag it.** *(Owner)* The workflow starts from this:

   ```sh
   git switch main && git pull && git tag -a vX.Y.Z -m "beck-bios X.Y.Z" && git push origin vX.Y.Z
   ```

   **Check:** in the *Release* workflow, the `build` job passes. It fails if the tag isn't the project's version, and then nothing has been published.

5. **Approve the publish.** *(Owner, final releases only)* The `pypi` environment waits for you. **Check:** it's the tag you meant, and `build` passed.

6. **Check the result.** *(Anyone)*
   - **The project's page** on [PyPI](https://pypi.org/project/beck-bios/) or [TestPyPI](https://test.pypi.org/project/beck-bios/): the version, the description, its links, and that the files show attestations.
   - **That it installs:** in a new environment, `pipx install beck-bios==X.Y.Z` or `uv tool install beck-bios==X.Y.Z`, then `beck --version`. A release candidate installs from TestPyPI, with its dependencies from PyPI: `uvx --index https://pypi.org/simple/ --default-index https://test.pypi.org/simple/ --from "beck-bios==X.Y.Z" beck --version`. uv takes each package from the first index that has it, PyPI here, so only `beck-bios` comes from TestPyPI, where anyone can upload under a name that's free there. Don't add `--index-strategy unsafe-best-match`, which would let a dependency come from TestPyPI.
   - **The [GitHub Release](https://github.com/Andredson/BECK/releases):** it has the notes, the wheel, the source archive and the SBOM, and a release candidate is marked as a pre-release. Commit messages are short, so if a `Breaking` line doesn't say enough, add to the notes with `gh release edit vX.Y.Z --notes-file <file>`.

### If something goes wrong

- **`build` failed:** nothing was published. Fix it in a new PR. If the fix changes files in the release, it needs a new version and a new tag.
- **A publish job failed:** read why. If it's a setting, such as the trusted publisher or the environment, fix that and re-run the failed jobs.
- **The GitHub Release failed, after publishing:** the package is out. Re-run that job.
- **A published version is wrong:** you can't replace it. Publish a fix as a new version, and [yank the bad one](https://pypi.org/help/#yanked) on PyPI if it could harm someone.
