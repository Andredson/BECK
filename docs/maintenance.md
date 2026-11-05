# Maintenance routine

BECK has no dependency-update bot ([DEC-29](adr/0003-tooling.md#dec-29--no-dependency-update-bot)). This monthly
routine replaces it. An agent can run it end to end; steps marked *(owner)* are human-only. The lookup and check
commands below were tested on 2026-11-02.

## When to run it

- **Monthly**, in the first week.
- **Right away** when:
  - the weekly *Security* workflow (`.github/workflows/security.yml`) fails;
  - CI starts failing because a `.trivyignore` entry expired;
  - an advisory affects a dependency or a pinned tool.

  In those cases, do only the sections that apply, and still add a [log](#log) row.

## Rules for the whole routine

- **14-day cooldown** ([DEC-45](adr/0003-tooling.md#dec-45--14-day-dependency-cooldown)). Python packages get it
  from `exclude-newer` in `pyproject.toml`. For Actions, uv, gitleaks, Trivy and commitizen, choose releases that
  are at least 14 days old. Never shorten the cooldown; an exception for one package is an owner decision
  ([urgent fixes](#urgent-fixes-inside-the-cooldown)).
- **Same pin everywhere.** `ci.yml` and `security.yml` repeat the same pins; `tests/test_workflow_pins.py` fails if
  they differ, or if an action isn't pinned to a full commit SHA.
- **Release binaries only, never floating tags or Trivy's own actions**
  ([DEC-48](adr/0004-ci-security-release.md#dec-48--trivy-kept-after-its-2026-supply-chain-compromise)).
- **No new tools.** Replacing a tool, or adding one, needs a new DEC first (see [AGENTS.md](../AGENTS.md)).

## 0. Prepare *(owner)*

```sh
git switch main && git pull && git switch -c deps/YYYY-MM
```

The agent commits on this branch (DEC-46). DEC-47 lets agents push **stage** branches only, so the owner pushes
this one (step 7).

## 1. Python dependencies

```sh
uv lock --upgrade --dry-run   # preview: one "Update <package> vOLD -> vNEW" line per change
uv lock --upgrade
uv sync --locked
```

- For every upgraded package, read its release notes between the two versions. Look for breaking changes,
  dropped support for Python 3.11, license changes, and new owners or maintainers (a supply-chain warning sign).
  Note what matters in the commit body.
- **Cooldown exceptions:** run `grep -n 'exclude-newer-package' pyproject.toml`. Remove every exception whose
  release is now at least 14 days old, then run `uv lock` again.
- New ruff or mypy releases can report new findings. Fix them in a separate commit on the same branch
  (`style: …` or `fix: …`). Never silence a rule to get past them without the owner's OK.

## 2. requirements.txt

```sh
uv export --no-dev --no-hashes --no-emit-project -o requirements.txt
```

CI fails if this file doesn't match `uv.lock` ([step 02.9](../roadmap/02-foundation-tooling-and-ci.md#029--keep-requirementstxt-generated)).

## 3. Run every check

The same commands CI runs:

```sh
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run python scripts/check_repo_hygiene.py
```

## 4. Pinned Actions and tools

| Pin | Where | Newest release ≥ 14 days old | Check before pinning |
|---|---|---|---|
| `actions/checkout`, `astral-sh/setup-uv`, `actions/upload-artifact` | `uses:` lines | [4a](#4a-list-releases-with-their-age) | Resolve the tag to a commit SHA ([4b](#4b-resolve-an-action-tag-to-its-commit-sha)) |
| uv | `UV_VERSION` | [4a](#4a-list-releases-with-their-age) on `astral-sh/uv` | Release notes |
| gitleaks | `GITLEAKS_VERSION`, `GITLEAKS_SHA256` | [4a](#4a-list-releases-with-their-age) on `gitleaks/gitleaks` | Three matching hashes ([4c](#4c-hash-a-release-binary)) |
| Trivy | `TRIVY_VERSION`, `TRIVY_SHA256` | [4a](#4a-list-releases-with-their-age) on `aquasecurity/trivy`; must show `immutable=true` | Three matching hashes ([4c](#4c-hash-a-release-binary)), and Trivy's advisories |
| commitizen | `COMMITIZEN_VERSION` | [4d](#4d-list-pypi-releases-with-their-age) | Release notes |

All of them are in the `env:` block or the `uses:` lines of **both** `.github/workflows/ci.yml` and
`.github/workflows/security.yml` (commitizen and `upload-artifact` only in `ci.yml`). Update the version, the hash
or SHA, and the "pinned" date in the trailing comment.

### 4a. List releases with their age

```sh
gh api 'repos/OWNER/REPO/releases?per_page=10' --jq '.[] | select(.prerelease | not) | "\(.tag_name)  \(.published_at[0:10])  \((now - (.published_at | fromdateiso8601)) / 86400 | floor) days  immutable=\(.immutable)"'
```

Pick the newest release that is at least 14 days old. Some projects publish several major versions on the same
day (`actions/checkout` does): stay on the current major version unless you've read the migration notes, and put
a major upgrade in its own commit (`ci: …`).

### 4b. Resolve an action tag to its commit SHA

```sh
gh api repos/OWNER/REPO/commits/TAG --jq .sha
```

Write it as `uses: OWNER/REPO@<40-character SHA> # TAG`.

### 4c. Hash a release binary

Three sources must agree: GitHub's asset digest, the release's checksums file, and the file you download.

```sh
V=8.30.1; R=gitleaks/gitleaks; A=gitleaks_${V}_linux_x64.tar.gz; C=gitleaks_${V}_checksums.txt
# Trivy instead: V=0.76.0; R=aquasecurity/trivy; A=trivy_${V}_Linux-64bit.tar.gz; C=trivy_${V}_checksums.txt
gh api "repos/$R/releases/tags/v$V" --jq ".assets[] | select(.name == \"$A\") | .digest"
curl -sSfL "https://github.com/$R/releases/download/v$V/$C" | grep " $A\$"
D=$(mktemp -d) && curl -sSfL -o "$D/$A" "https://github.com/$R/releases/download/v$V/$A" && sha256sum "$D/$A"
```

For Trivy, also read the advisories that appeared since the last run:

```sh
gh api repos/aquasecurity/trivy/security-advisories --jq '.[] | "\(.published_at[0:10])  \(.severity)  \(.summary)"'
```

### 4d. List PyPI releases with their age

```sh
PKG=commitizen; curl -sSf "https://pypi.org/pypi/$PKG/json" | uv run python -c '
import datetime as dt, json, sys
now = dt.datetime.now(dt.timezone.utc)
releases = json.load(sys.stdin)["releases"]
uploads = sorted((min(f["upload_time_iso_8601"] for f in files), v) for v, files in releases.items() if files)
for uploaded, version in uploads[-5:]:
    age = (now - dt.datetime.fromisoformat(uploaded.replace("Z", "+00:00"))).days
    verdict = "ok" if age >= 14 else "too new"
    print(f"{version:12} {uploaded[:10]}  {age:3} days  {verdict}")'
```

### 4e. Check the new pins

```sh
uv run pytest tests/test_workflow_pins.py -q
uvx --exclude-newer "14 days" --from "commitizen==NEW_VERSION" cz check --rev-range origin/main..HEAD
```

The gitleaks and Trivy pins are proven by CI: the install step fails if the hash doesn't match.

### The Samba test server's base image

`tests/integration/samba/Containerfile` pins a Debian image by digest. Find the newest `trixie-<date>-slim` tag at least 14
days old (DEC-45), with its digest:

```sh
curl -sS 'https://hub.docker.com/v2/repositories/library/debian/tags?page_size=100&name=trixie-2' | python3 -c "import json,sys; [print(t['name'], t.get('tag_last_pushed','?')[:10], t.get('digest')) for t in json.load(sys.stdin)['results'] if t['name'].endswith('-slim')]" | sort -k2 -r | head
```

Update the tag and digest, then check that the integration tests still pass, with the commands in [AGENTS.md](../AGENTS.md#commands).

## 5. Security review

1. **Weekly runs.** `gh run list --workflow security.yml --limit 5`, then `gh run view RUN_ID --log-failed` for any
   failure. Fix the cause, or treat it as an [urgent fix](#urgent-fixes-inside-the-cooldown).
2. **`.trivyignore`.** For each entry, check whether its fix is now at least 14 days old. If it is, run
   `uv lock --upgrade-package NAME`, regenerate `requirements.txt` and delete the entry. If the entry expires before
   the fix passes the cooldown, ask the owner: extend the expiry (with the reason in the comment) or make a
   cooldown exception.

### Urgent fixes inside the cooldown

When a vulnerability is fixed only by a release less than 14 days old, the **owner** chooses one of these and
the choice goes in the [log](#log):

- **Ignore it until the fix passes the cooldown.** Add the IDs to `.trivyignore`, each with a comment, a link and
  `exp:YYYY-MM-DD`, set to the day **after** the fix becomes 14 days old (an entry expires at 00:00 UTC). This was
  used for pyasn1 in November 2026.
- **Make a cooldown exception for that one package.** In `[tool.uv]`, add a cutoff just after the fix's upload
  time, then run `uv lock --upgrade-package NAME` and regenerate `requirements.txt`:

  ```toml
  exclude-newer-package = { pyasn1 = "2026-10-28T00:00:00Z" }   # example: admits pyasn1 0.6.5
  ```

  Step 1 removes the exception once the release is 14 days old.

## 6. Python versions

```sh
curl -sSf https://peps.python.org/api/release-cycle.json | uv run python -c '
import json, sys
for version, info in json.load(sys.stdin).items():
    if version.startswith("3.") and int(version.split(".")[1]) >= 10:
        status, first, eol = info["status"], info["first_release"], info["end_of_life"]
        print(f"{version:5} {status:9} released {first}  end of life {eol}")'
```

Compare with the `tests` matrix in `ci.yml` and with `requires-python` in `pyproject.toml`
([DEC-08](adr/0003-tooling.md#dec-08--python--311)). Propose to the owner:

- adding a version that has been released (status `bugfix`) to the matrix;
- raising the floor when the oldest version is less than 3 months from end of life. That changes DEC-08, so it
  needs a new DEC.

## 7. Commit and hand over

The agent commits (DEC-46), with no attribution trailer:

```sh
git add uv.lock requirements.txt pyproject.toml .github/workflows .trivyignore docs/maintenance.md
git commit -m "build(deps): monthly dependency refresh (YYYY-MM)" -m "<upgraded packages, new pins, exceptions, ignores>"
```

Then it prints this line for the owner, who pushes, opens the PR, and merges with a merge commit once CI is
green (DEC-39):

```sh
git push -u origin deps/YYYY-MM && gh pr create --base main --title "build(deps): monthly dependency refresh (YYYY-MM)" --body "See the log in docs/maintenance.md."
```

## Log

Add one row per run, newest first. It records the reasons for every cooldown exception and ignore (DEC-45).

| Date | By | Changes | Cooldown exceptions and ignores | Follow-ups |
|---|---|---|---|---|
| 2026-11-02 | Stage 02 (initial pins) | uv 0.13.2; checkout v7.0.1; setup-uv v10.3.0; upload-artifact v7.0.2; commitizen 4.19.2; gitleaks 8.30.1; Trivy 0.76.0 | `.trivyignore`: four pyasn1 0.6.4 CVEs until 2026-11-11 (owner decision; fix 0.6.5 is inside the cooldown) | After 2026-11-10 06:33 UTC: `uv lock --upgrade-package pyasn1`, regenerate `requirements.txt`, delete the four entries. Python 3.15 was released on 2026-10-09: propose adding it to the CI matrix. |
