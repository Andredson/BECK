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
The one exception is a tag whose `build` failed, so that nothing was published: see [If something goes wrong](#if-something-goes-wrong).

## The SBOM

Each GitHub Release has a software bill of materials: a [CycloneDX](https://cyclonedx.org/) list of what BECK depends on, so that users and distributors can check it against known problems (DEC-37). Trivy makes it, at the version pinned in `.github/workflows/ci.yml`:

```sh
mkdir -p sbom
trivy fs --format cyclonedx --skip-dirs .venv --output "sbom/beck-bios-$(uv version --short).cdx.json" .
```

- **What's in it:** the runtime packages in `uv.lock`, with their exact versions, and `beck-bios` itself.
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

4. **Tag it.** *(Owner)* Only once the PR is merged: a tag pushed before then is on the old `main`, with the old version. The workflow starts from this:

   ```sh
   git switch main && git pull && git tag -a vX.Y.Z -m "beck-bios X.Y.Z" && git push origin vX.Y.Z
   ```

   **Check:** in the *Release* workflow, the `build` job passes. It fails if the tag isn't the project's version, and then nothing has been published.

5. **Approve the publish.** *(Owner, final releases only)* The `pypi` environment waits for you. **Check:** it's the tag you meant, and `build` passed.

6. **Check the result.** *(Anyone)*
   - **The project's page** on [PyPI](https://pypi.org/project/beck-bios/) or [TestPyPI](https://test.pypi.org/project/beck-bios/): the version, the description, its links, and that the files show attestations.
   - **That it installs:** in a new environment, `pipx install beck-bios==X.Y.Z` or `uv tool install beck-bios==X.Y.Z`, then `beck --version`. Just after a publish,
     uv's cached copy of the index may not list the new version yet, and the install says there's no such version. Add `--refresh` to `uv tool install` or
     `uvx`, and run pipx, which installs with uv, as `UV_NO_CACHE=1 pipx install …`. A release candidate is on TestPyPI only. Install that file, checked against its hash, so that its dependencies still come from PyPI. Take the wheel's `url` and `sha256` from `https://test.pypi.org/pypi/beck-bios/X.Y.Z/json`, then:

     ```sh
     D=$(mktemp -d) && W=beck_bios-X.Y.Z-py3-none-any.whl && curl -sSfL -o "$D/$W" "<url>" && echo "<sha256>  $D/$W" | sha256sum -c && uv tool install --reinstall "$D/$W" && beck --version
     ```

     Installing by name doesn't work once `beck-bios` is on PyPI: uv takes a package from the first index that has it, so it looks only at PyPI, which has no release candidate. Don't add `--index-strategy unsafe-best-match` to get round that, because it would let a dependency come from TestPyPI, where anyone can upload under a name that's free there. And check the hash with `sha256sum`: uv doesn't check a `#sha256=` on the end of the URL.
   - **The [GitHub Release](https://github.com/Andredson/BECK/releases):** it has the notes, the wheel, the source archive and the SBOM, and a release candidate is marked as a pre-release. Commit messages are short, so if a `Breaking` line doesn't say enough, add to the notes with `gh release edit vX.Y.Z --notes-file <file>`.

### If something goes wrong

- **`build` failed:** nothing was published. Fix it in a new PR. If the fix changes files in the release, it needs a new version and a new tag.
- **`build` failed at "The tag is the project's version":** the tag isn't on the release commit, usually because it was pushed before the PR was merged.
  Nothing was published, so this is the one time a tag can be deleted and made again. Check that PyPI has no such version, and that there's no
  GitHub Release for it. Then merge the PR, and run:

  ```sh
  git push origin :refs/tags/vX.Y.Z && git tag -d vX.Y.Z && git switch main && git pull && git tag -a vX.Y.Z -m "beck-bios X.Y.Z" && git push origin vX.Y.Z
  ```

  This happened with `1.0.1`.
- **A publish job failed:** read why. If it's a setting, such as the trusted publisher or the environment, fix that and re-run the failed jobs.
- **The GitHub Release failed, after publishing:** the package is out. Re-run that job.
- **A published version is wrong:** you can't replace it. Publish a fix as a new version, and [yank the bad one](https://pypi.org/help/#yanked) on PyPI if it could harm someone.

## Reaching 1.0

`1.0.0` says BECK is stable: from then on, a breaking change needs a major version. It's released through [the checklist](#the-release-checklist), with a release candidate first, once every criterion below is met and the owner signs off ([step 10.11](../roadmap/10-packaging-and-release.md#1011--define-and-reach-10)). The status was checked on 2026-11-11.

- [x] **Stages 01–09 are done, and 10.1–10.10.** Step 10.12 closes stage 10 after 1.0. Defects D1–D16 are fixed, as [the assessment](../roadmap/00-assessment.md#defects) records. D16 was only suspected: the run below connected to Recalbox's own Samba on port 445.
- [x] **A real report from the current stable Recalbox is a fixture.** `recalbox-10.1.1/default-install`, from 10.1.1 in a VM. Recalbox 10.1 has been the stable release since 2026-09-04, and nothing newer was out on 2026-11-11, before the final tag.
- [x] **An end-to-end run with the installed package has passed, on the Recalbox 10.1.1 VM** (DEC-72; no real hardware was available, and the owner accepted the VM). On 2026-11-11, `beck 1.0.0rc1`, installed from TestPyPI's wheel as in [step 6 of the checklist](#the-release-checklist), with the owner's own BIOS files: the owner's `beck --json check --dry-run` planned one upload and exited with 0; `beck --json check --verify` uploaded it, checked its MD5 on the VM, and exited with 0, with no errors; a second dry run kept the file. The report was the one already on the VM, not a new one. Not run on it: `--move`, `--clean-unmatched`, `--overwrite`, or a login with a password, which the tests cover.
  **Found afterwards:** Recalbox couldn't use the file it uploaded. It was `neocd.bin`, sent up as `neocdz.zip`, which isn't a zip archive, so
  Recalbox went on listing the target as missing. BECK's checks compare what arrived with the local file, not whether Recalbox accepts it.
  `1.0.1` fixes this (DEC-74).
- [x] **The `--json` schema version 1 is frozen.** [The compatibility promise](json-output.md#the-compatibility-promise) only lets fields be added, and `V1_FIELDS` in `tests/unit/test_json_contract.py` records what version 1 holds.
- [x] **No open issue is labelled `data-loss`.** None on 2026-11-11, before the final tag: `gh issue list -R Andredson/BECK --label data-loss --state open`.
- [x] **Removed:** `check_bios.py`, `requirements.txt` and its CI check, and running `beck` with no command, which is now a usage error with exit code 2 (DEC-70).
- [x] **The message about the old `config/config.yml` stays,** in 1.0 and for one more minor version after it.
