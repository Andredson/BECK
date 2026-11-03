# Stage 02 — Foundation tooling & CI

**Status:** In progress · **Depends on:** 01 · **Branch:** `stage/02-foundation` · **Effort:** M

## Goal
Put the project on a modern, reproducible toolchain (uv, ruff, mypy, pytest) and a CI pipeline that gates every
later change with lint, format, type, test, commit-message, secret and dependency checks. Every check is a
**local `uv run …` command**; CI only calls them (DEC-25).

## Why
- Testing and CI/CD score **0/10**, and dependency management 5/10 ([assessment](00-assessment.md#scorecard)).
- Stage 03 changes code that has data-loss bugs, so a test runner and CI must exist **before** it starts.
- With no git hooks (DEC-28) and no update bot (DEC-29), CI and a written maintenance routine are the only
  safety nets.

## Decisions applied
DEC-07, DEC-08, DEC-14, DEC-25, DEC-27, DEC-28, DEC-29, DEC-32, DEC-34, DEC-35, DEC-38, DEC-39, DEC-42, DEC-43, DEC-48.

## Steps

### 02.1 — Add `pyproject.toml` and `uv.lock` (D15)
- [x] Done (2026-11-02: uv 0.13.6, CPython 3.11.18; locked pysmb 1.2.15, PyYAML 6.0.3)
- **What:** Create a **non-package** uv project for now. The package layout comes in stage 04.
  ```toml
  [project]
  name = "beck-bios"
  version = "0.1.0"
  description = "Match your BIOS files by MD5 and send them to the right folder on your Recalbox"
  readme = "README.md"
  requires-python = ">=3.11"
  license = "GPL-3.0-only"
  dependencies = ["pysmb>=1.2.9.1,<2", "PyYAML>=6.0.2,<7"]

  [tool.uv]
  package = false
  ```
  Use `uv add` so uv picks current compatible versions, then `uv lock`. Confirm the chosen PyYAML version has
  wheels for every Python version in the CI matrix (3.11–3.14).
- **Files:** `pyproject.toml`, `uv.lock`, `.python-version` (`3.11`, the floor, so local runs catch syntax that
  is too new)
- **Done when:** `uv sync` creates `.venv` and the script imports cleanly under uv. Don't *run* the script: it
  would connect to a real Recalbox, which needs the owner's explicit OK (AGENTS.md hard rule).
- **Verify:** `uv lock --check && uv run python -c "import check_bios"`
- **Commit message:** `build: manage project with uv and require Python 3.11+`

### 02.2 — Dev dependency group
- [x] Done (2026-11-02: pytest 9.1.1, pytest-cov 7.1.0, ruff 0.17.1, mypy 2.4.0, types-PyYAML 6.0.12.20260906; resolved under the 14-day cooldown added here, DEC-45)
- **What:** `uv add --dev pytest pytest-cov ruff mypy types-PyYAML` (written to `[dependency-groups] dev`).
  `types-PyYAML` is temporary; it goes away when PyYAML is dropped in stage 07 (DEC-24).
- **Files:** `pyproject.toml`, `uv.lock`
- **Done when:** `uv run ruff --version`, `uv run mypy --version` and `uv run pytest --version` all work.
- **Verify:** `uv run ruff --version && uv run mypy --version && uv run pytest --version`
- **Commit message:** `build: add pytest, ruff and mypy as dev dependencies`

### 02.3 — Ruff configuration and first pass (SAST via `S` rules)
- [x] Done (2026-11-02: 34 findings → formatting + 4 safe fixes, verified AST-equivalent apart from import order, `json` removal, the redundant `"r"` mode and `return None`; 23 remaining findings across 11 rules ignored per file, each pointing to its 03.x step)
- **What:**
  ```toml
  [tool.ruff]
  line-length = 100
  target-version = "py311"

  [tool.ruff.lint]
  select = ["E", "W", "F", "I", "B", "UP", "SIM", "RET", "PTH", "RUF", "S"]

  [tool.ruff.lint.per-file-ignores]
  "tests/**" = ["S101"]   # assert is how pytest works
  ```
  Run `uv run ruff format .` and `uv run ruff check --fix .`. Leave behavior unchanged; this step is
  formatting and safe autofixes only. Any remaining violation in `check_bios.py` gets a **per-file ignore
  with a comment naming the stage-03 step that removes it** (for example `E722` bare except → 03.12). Note on
  `S324` (MD5 flagged as insecure): MD5 is used here to *identify* files, not for security. The fix (in 03.6) is
  `hashlib.md5(data, usedforsecurity=False)`, not an ignore.
- **Files:** `pyproject.toml`, `check_bios.py` (format only)
- **Done when:** Lint and format pass; every ignore has a step reference.
- **Verify:** `uv run ruff check . && uv run ruff format --check .`
- **Commit message:** `style: adopt ruff formatting and lint rules including security checks`

### 02.4 — Mypy configuration
- [x] Done (2026-11-02: strict, `files = ["check_bios.py"]` for now, because `tests`/`scripts` don't exist yet and are added by 02.5/02.8. The 11 legacy errors (wrong `-> str` on `smb_connect`, reused variables, D10's `.group()` on `None`) are all in code that stage 03 rewrites, so they're disabled per error code with the step that removes each (03.3, 03.5; leftovers 03.12). No code changes.)
- **What:**
  ```toml
  [tool.mypy]
  python_version = "3.11"
  strict = true
  files = ["check_bios.py", "tests", "scripts"]

  [[tool.mypy.overrides]]
  module = ["check_bios"]          # legacy: relaxed until stage 04
  disallow_untyped_defs = false
  disallow_untyped_calls = false

  [[tool.mypy.overrides]]
  module = ["smb.*", "nmb.*"]      # pysmb ships no type hints
  ignore_missing_imports = true
  ```
  Fix any genuine type errors with minimal changes. Don't refactor.
- **Files:** `pyproject.toml`
- **Done when:** mypy passes with this configuration.
- **Verify:** `uv run mypy`
- **Commit message:** `build: configure mypy with strict defaults and a relaxed legacy module`

### 02.5 — Pytest configuration and smoke test
- [x] Done (2026-11-02: 1 test passes; checked that it fails when an import-time side effect is injected; `tests` added to mypy `files`)
- **What:**
  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  pythonpath = ["."]
  addopts = "-ra --strict-markers --strict-config"
  markers = ["integration: needs the Samba test container (stage 05)"]

  [tool.coverage.run]
  branch = true
  source = ["check_bios"]
  ```
  `tests/test_smoke.py`: import `check_bios`, assert `main` is callable, and assert that importing performs
  no network or file I/O (monkeypatch `smb_connect` to raise if it gets called).
- **Files:** `pyproject.toml` (also add `"tests"` to mypy `files`), `tests/__init__.py` (empty), `tests/test_smoke.py`
- **Done when:** `uv run pytest` passes with coverage output.
- **Verify:** `uv run pytest --cov`
- **Commit message:** `test: add pytest configuration and import smoke test`

### 02.6 — Markdown link test (DEC-42)
- [x] Done (2026-11-02: 25 Markdown files checked; also covers reference-style links and links escaping the repo; unit tests for the slug rule and the checker; checked that it fails on a broken file name and a broken anchor in real files)
- **What:** `tests/test_docs_links.py` (about 30–60 lines, standard library only):
  - Collect tracked `*.md` files (`git ls-files '*.md'`, falling back to a glob if git isn't available).
  - Skip fenced code blocks; find `[text](target)` links whose target is not `http(s):`, `mailto:` or `tel:`.
  - Assert that the target file exists (relative to the linking file). If there is a `#anchor`, assert it
    matches a heading slug in the target file, using GitHub's rule: lowercase, drop characters other than
    letters, digits, spaces, `-` and `_`, spaces become `-`, and duplicates get `-1`, `-2`, ….
  - Parametrize by file so failures name the broken file and link.
- **Files:** `tests/test_docs_links.py`
- **Done when:** The test passes on the current repository (roadmap anchors included).
- **Verify:** `uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `test(docs): check relative links and anchors in Markdown files`

### 02.7 — Editor and line-ending settings
- [x] Done (2026-11-02: all 37 tracked files already LF; TOML indent is 4 spaces, not 2, to match how uv writes `pyproject.toml`; image extensions added as binary for the optional 08.2 screenshots. The Windows checkout is exercised by the CI matrix in 02.10.)
- **What:** `.editorconfig` (UTF-8, LF, final newline, 4-space Python, 2-space YAML/TOML/JSON, no trailing
  whitespace except in Markdown). `.gitattributes` with `* text=auto eol=lf`, and `*.bin *.rom *.zip *.img
  *.7z binary` as a safety net. Also extend `.gitignore` for `.venv/`, `__pycache__/`, `.pytest_cache/`,
  `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `coverage.xml`, `dist/`.
- **Files:** `.editorconfig`, `.gitattributes`, `.gitignore`
- **Done when:** A fresh clone on Windows produces LF files and `git status` stays clean after running all tools.
- **Verify:** Run all tools, then `git status --porcelain` lists only the intended files, and
  `git ls-files --eol` shows `i/lf` and `attr/text=auto eol=lf` for every text file. (Read-only commands; they
  replaced an earlier `git add --renormalize .` that would have staged unrelated files.)
- **Commit message:** `chore: add editorconfig, gitattributes and tool caches to gitignore`

### 02.8 — Repository hygiene guard
- [x] Done (2026-11-02: 39 tracked files pass; 15 unit tests; checked that it fails on a staged `bios/scph5501.bin` using a temporary index. `.github/` is exempt from the config-name rule, so the 12.4 issue-form `config.yml` is allowed. Added `scripts/__init__.py` so mypy and the tests see `scripts` as a package.)
- **What:** `scripts/check_repo_hygiene.py` (standard library only). It runs `git ls-files -z` and fails, with a
  clear message per file, if:
  - any tracked file is under `bios/` other than `bios/.keep`;
  - any tracked file has a typical BIOS/ROM extension (`.bin`, `.rom`, `.img`, `.zip`, `.7z`, `.pup`, `.chd`,
    `.iso`, case-insensitive);
  - any tracked file is larger than 1 MiB;
  - a real config is tracked (`config/config.yml`, or later any `config.toml` that isn't `*.example.*`).

  This replaces what a pre-commit hook would do (DEC-28). It's the main guard against committing copyrighted
  BIOS files or credentials.
- **Files:** `scripts/check_repo_hygiene.py`, `tests/test_repo_hygiene.py` (unit tests on fake file lists),
  `pyproject.toml` (add `"scripts"` to mypy `files`)
- **Done when:** The script passes on the repository today **except** for the tracked `config/config.yml`,
  which is allow-listed with a comment pointing to 03.2.
- **Verify:** `uv run python scripts/check_repo_hygiene.py && uv run pytest tests/test_repo_hygiene.py -q`
- **Commit message:** `ci: add repository hygiene guard against BIOS files and tracked secrets`

### 02.9 — Keep `requirements.txt` generated
- [x] Done (2026-11-02: pins now match `uv.lock` (pysmb 1.2.15, PyYAML 6.0.3, plus transitive dependencies); uv's own header marks the file as generated and names the command; re-export is byte-identical; installs and imports in a fresh 3.11 venv)
- **What:** Users who don't have uv still use `pip install -r requirements.txt` until 1.0 (stage 10). Generate
  it from the lockfile instead of editing it by hand:
  `uv export --no-dev --no-hashes -o requirements.txt`. Add a header comment saying it's generated.
- **Files:** `requirements.txt`
- **Done when:** Running the export again produces no diff.
- **Verify:** `uv export --no-dev --no-hashes -o requirements.txt && git diff --exit-code -- requirements.txt`
- **Commit message:** `build: generate requirements.txt from uv.lock`

### 02.10 — CI workflow: quality and test jobs
- [x] Done (2026-11-02: PR #2, all 13 checks green on the first run. Pins: checkout v7.0.1, setup-uv v10.3.0, upload-artifact v7.0.2, uv 0.13.2, each ≥ 14 days old (DEC-45). A per-Python `cache-suffix` was added after the first run showed cache-save races between matrix cells.)
- **What:** `.github/workflows/ci.yml`, on `pull_request` and `push` to `main`:
  - Top level: `permissions: contents: read`; `concurrency` group per ref with `cancel-in-progress: true`.
  - Every third-party action pinned to a **full commit SHA**, with the version in a trailing comment
    (`actions/checkout`, `astral-sh/setup-uv`).
  - Job `quality` (ubuntu): `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`,
    `uv run mypy`, `uv run python scripts/check_repo_hygiene.py`, plus the `requirements.txt` drift check from 02.9.
  - Job `tests`: matrix `os: [ubuntu-latest, windows-latest, macos-latest]` × `python: ["3.11", "3.12",
    "3.13", "3.14"]`, `fail-fast: false`; `uv sync --locked --python ${{ matrix.python }}`, then
    `uv run --python ${{ matrix.python }} pytest --cov --cov-report=xml`. Upload `coverage.xml` as a workflow
    artifact from one cell (ubuntu, 3.11). No third-party coverage service.
  - Each job's `run:` lines must be exactly the commands documented in AGENTS.md (DEC-25).
- **Files:** `.github/workflows/ci.yml`
- **Done when:** The workflow is green on the stage branch's PR.
- **Verify:** Locally: run every command listed in the workflow. On GitHub: the PR's checks are green.
- **Commit message:** `ci: add lint, type-check and cross-platform test workflow`

### 02.11 — CI: Conventional Commits check (DEC-38)
- [x] Done (2026-11-02: commitizen pinned to 4.19.2, the newest release ≥ 14 days old (DEC-45). `uvx` ignores the
  project's `[tool.uv]` settings, so the job passes `--exclude-newer "14 days"` to apply the cooldown to
  commitizen's dependencies too. Passing case: this PR's commits. Failing case: the same command in a throwaway
  local repo failed (exit 14) on a `fixed stuff` commit. Correction to the reasoning below: commitizen's default
  `allowed_prefixes` already skips `Merge …` messages, so checking out the head SHA isn't needed to avoid a
  failure. It is kept so the job checks exactly the commits the author pushed.)
- **What:** Add a `commits` job that runs only on `pull_request`:
  - Checkout with `fetch-depth: 0` and `ref: ${{ github.event.pull_request.head.sha }}` (not GitHub's
    synthetic merge ref, whose "Merge …" commit would fail the check).
  - `uvx --from 'commitizen==<pinned version>' cz check --rev-range ${{ github.event.pull_request.base.sha }}..${{ github.event.pull_request.head.sha }}`
  - Add `[tool.commitizen] name = "cz_conventional_commits"` to `pyproject.toml` so the rule is explicit and
    can be run locally.
  - Older, pre-roadmap commits on `main` are never checked; only commits in the PR are.
- **Files:** `.github/workflows/ci.yml`, `pyproject.toml`
- **Done when:** A PR with a commit like `fixed stuff` fails this job, and one with `fix(parser): …` passes.
- **Verify:** Locally: `uvx --from commitizen cz check --message "fix(parser): handle hyphens"` exits 0, and
  `--message "fixed stuff"` exits non-zero.
- **Commit message:** `ci: enforce Conventional Commits on pull requests with commitizen`

### 02.12 — CI: secret scanning with gitleaks (DEC-35)
- [x] Done (2026-11-02: gitleaks 8.30.1, the newest release (226 days old). The archive's SHA-256 is pinned in the
  workflow, and matched the release's checksums file and GitHub's asset digest; a wrong hash stops the install.
  The allow-list skips a finding only when the file is under `tests/` **and** the value starts with `beck-test-`.
  Proven in a throwaway local repo: the default rules flag such a fake value; with the allow-list it passes in
  `tests/` but still fails in `app.py`, and a real-looking value or a random AWS-style key in `tests/` fails
  (exit 1). The test branch from *Done when* wasn't created, because branches are human-only. BECK's full history
  is clean too, ahead of 02.14.)
- **What:** Add a `secrets` job:
  - Download a **pinned gitleaks release** and verify its SHA-256 checksum before running it. Don't use a
    floating action tag: security tools' own actions have been hijacked through re-pointed tags before (for
    example `tj-actions/changed-files`, March 2025).
  - On PRs: scan only the PR's commit range. On `main` pushes: scan the pushed range. Full-history scans run
    weekly (02.14). Check the current CLI syntax when implementing (`gitleaks git …` in recent v8 releases;
    older ones used `gitleaks detect`). Use `--redact` so logs never print a found secret.
  - `.gitleaks.toml`: extend the default rules and allow-list only clearly fake test values (e.g. the literal
    `beck-test-password` used by stage 05 fixtures).
- **Files:** `.github/workflows/ci.yml`, `.gitleaks.toml`
- **Done when:** A test branch with a fake AWS-style key in a file fails the job (then drop that branch).
- **Verify:** Locally, with gitleaks installed: run the same command against `HEAD~5..HEAD`; it exits 0.
- **Commit message:** `ci: scan commits for secrets with gitleaks`

### 02.13 — CI: dependency scanning with Trivy (DEC-34)
- [x] Done (2026-11-02: Trivy 0.76.0, the newest release ≥ 14 days old, from an immutable release; its SHA-256 is
  pinned and matched the checksums file and GitHub's asset digest. The owner reviewed Trivy's March 2026 compromise
  and kept it with stricter install rules (DEC-48). Trivy reads `uv.lock` directly, so `requirements.txt` is
  skipped in the vulnerability scan to avoid duplicates; dev dependencies are included. The single command
  below was split in two: with `--severity HIGH,CRITICAL --exit-code 1`, a "restricted" license such as LGPL
  would have **failed** the job. The license scan is a separate, report-only command. Lockfiles carry no
  license data, so it reads `requirements.txt` plus the installed `.venv`. First run found four HIGH CVEs in
  pyasn1 0.6.4, fixed in 0.6.5, which is still inside the cooldown; the owner chose to ignore them until
  2026-11-11 in `.trivyignore`. An expired entry was tested and does fail the scan.)
- **What:** Add an `sca` job:
  - Pinned Trivy release binary with checksum verification (same reasoning as 02.12).
  - `trivy fs --scanners vuln,license --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 .`
  - Confirm Trivy detects `uv.lock`. If the installed version doesn't support it, point it at the generated
    `requirements.txt` (kept in sync by 02.9) and note why in a comment.
  - License findings are **reported, not failing** for now. Turning them into a failing policy (e.g. reject
    licenses incompatible with GPL-3.0-only) needs an owner decision: record a new DEC first.
  - Add `.trivyignore` only with a comment, a link and an expiry date per entry.
- **Files:** `.github/workflows/ci.yml`, `.trivyignore` (only if needed)
- **Done when:** The job runs on the PR and is green, or fails only on real, documented findings.
- **Verify:** Locally, with Trivy installed: the same `trivy fs` command exits 0.
- **Commit message:** `ci: scan dependencies for vulnerabilities and licenses with Trivy`

### 02.14 — Weekly security workflow
- [x] Done (2026-11-02: Mondays 06:00 UTC plus `workflow_dispatch`, with the same commands and pins as the
  `secrets` and `sca` jobs in `ci.yml`. GitHub only offers *Run workflow* once the file is on `main`, so the
  workflow also runs on pull requests that change `security.yml`; that run on this PR is the pre-merge check.
  The manual run from *Done when* moved to 02.17, after the merge. Its jobs are named `secrets (full history)`
  and `sca (weekly)`, so they can't be mistaken for the required `secrets` and `sca` checks (02.16).
  `tests/test_workflow_pins.py` fails if the pins in the two workflows drift apart, or if any third-party action
  isn't pinned to a full commit SHA. Locally, the full-history scan covers all refs (`git log --all`) and is clean.)
- **What:** `.github/workflows/security.yml` with `schedule` (e.g. Mondays 06:00 UTC) and
  `workflow_dispatch`. It runs a gitleaks **full-history** scan and the Trivy scan on `main`. Because there's
  no update bot (DEC-29), this weekly run is the early warning for newly disclosed vulnerabilities in
  dependencies that haven't changed. Same pinning rules as above.
- **Files:** `.github/workflows/security.yml`
- **Done when:** A manual `workflow_dispatch` run is green.
- **Verify:** Human: GitHub → Actions → *Security* → *Run workflow*, and check the result.
- **Commit message:** `ci: add weekly scheduled secret and dependency scans`

### 02.15 — Manual maintenance routine (DEC-29)
- [ ] Done
- **What:** `docs/maintenance.md`, a monthly checklist that replaces an update bot:
  1. `uv lock --upgrade` (it respects the 14-day cooldown, DEC-45), then run all checks from AGENTS.md; read the
     changelogs of upgraded packages. List any active `exclude-newer-package` overrides, and remove those that are
     no longer needed.
  2. Regenerate `requirements.txt` (02.9).
  3. For each pinned GitHub Action, gitleaks, Trivy and commitizen: look up the latest release **that is at least
     14 days old**, verify its checksum or SHA, and update the pin and comment in **every** workflow
     (`tests/test_workflow_pins.py` fails if they differ).
  4. Review the last weekly security run (02.14), and every `.trivyignore` entry: remove fixed or expired ones
     (DEC-48).
  5. Review the Python versions in the CI matrix against python.org's end-of-life dates.
  6. Commit with `build(deps): monthly dependency refresh (YYYY-MM)`.
- **Files:** `docs/maintenance.md`, `AGENTS.md` (link)
- **Done when:** The checklist is complete enough that an agent can run it end-to-end and print the commit
  commands for the human.
- **Verify:** `uv run pytest tests/test_docs_links.py -q` (the new links resolve)
- **Commit message:** `docs: add manual monthly maintenance routine`

### 02.16 — GitHub settings (human-only)
- [ ] Done
- **What:** The owner applies these in GitHub's web UI (agents can't and must not):
  - *Settings → General → Pull Requests:* allow **merge commits** only; disable squash and rebase merging (DEC-39).
  - *Settings → Rules → Rulesets* (or *Branches*) for `main`: require a pull request; require the status checks
    `quality`, `tests` (all matrix cells), `commits`, `secrets` and `sca`; block force pushes and deletion.
  - *Settings → Actions → General:* workflow permissions **read-only** by default; don't allow Actions to
    create or approve pull requests.
- **Files:** none
- **Done when:** A PR with a failing check can't be merged, and the merge button offers only "Create a merge commit".
- **Verify:** Human check on the stage 02 PR.
- **Commit message:** none (settings change). Note it in the PR description.

### 02.17 — Close the stage
- [ ] Done
- **What:** Replace AGENTS.md's *Commands* section with the real commands (`uv sync`, `uv run ruff check .`,
  `uv run ruff format .`, `uv run mypy`, `uv run pytest`, `uv run python scripts/check_repo_hygiene.py`) and
  the *Repo map* additions. Re-score [00-assessment](00-assessment.md#re-scoring-history): expect testing,
  CI/CD and dependency management to rise. Update [README](README.md#stages) status. Push the closing commit
  (DEC-47). If the stage PR doesn't exist yet, print this command for the human (DEC-43):

  ```sh
  gh pr create --base main --title "Stage 02: foundation tooling and CI" --body "Closes roadmap stage 02."
  ```

- **Files:** `AGENTS.md`, `roadmap/00-assessment.md`, `roadmap/README.md`, this file
- **Done when:** The PR is green and merged with a merge commit. After the merge, a manual *Security* run on
  `main` is green (GitHub → Actions → *Security* → *Run workflow*; moved here from 02.14).
- **Verify:** Every command in AGENTS.md's *Commands* section runs successfully from a fresh clone.
- **Commit message:** `docs(roadmap): close stage 02 and update agent commands`

## Stage acceptance criteria
- `uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` passes
  on a fresh clone, on all three operating systems.
- CI blocks merges on lint, types, tests, commit format, secrets, dependency vulnerabilities and repo hygiene.
- No new tool was added beyond the decision log.

## Out of scope
- Fixing the defects (stage 03), even though ruff and mypy will point at some of them.
- Turning the project into an installable package (stage 04).

## Agent notes
- When you look up action SHAs or binary checksums, take them from the project's official release page, and
  write the version in a comment next to the pin.
- If a CI matrix cell fails only because of a platform quirk in the **legacy** script (e.g. Windows paths),
  record it as a known issue linked to the stage 03 step that fixes it. Don't patch behavior in this stage.
