# Stage 08 — Documentation

**Status:** In progress · **Depends on:** 07 · **Branch:** `stage/08-docs` · **Effort:** M

## Goal
Make the documentation complete enough that a Recalbox user with no Python background can install and use BECK,
and a contributor (human or agent) can understand and change it. Everything is Markdown in the repository
(DEC-30) and checked by the link test (DEC-42).

## Why
- Documentation scored 3/10 at baseline; licensing 6/10, partly because of the missing legal notices.
- Most user problems with this kind of tool come from network setup (SMB, hostnames) and from not knowing how
  to generate the report, and neither is documented today.

## Decisions applied
DEC-13, DEC-20, DEC-30, DEC-42, DEC-43.

## Steps

### 08.1 — Rewrite the README
- [x] Done (2026-11-06: followed literally from an empty home folder, with uv and with pipx, from `git+https://github.com/Andredson/BECK` to an upload on the Samba test server. The troubleshooting guide (08.3) and
  `CONTRIBUTING.md` (12.1) don't exist yet, so for now the README has a short table of its own and points contributors to `AGENTS.md`. Only the CI badge, so no DEC was needed. Rough wording such as `1 files` is in the code, so it isn't
  part of this step, despite what the stage 07 re-score says. Beyond the list below: `AGENTS.md`'s description of the README.)
- **What:** Structure:
  1. One-line description, then badges. Use only the GitHub-native CI status badge. A PyPI or Python-version
     badge from shields.io is a third-party service: **ask the owner first** and record a DEC if accepted.
  2. **What it does**, with a short flow: report → scan → match → copy.
  3. **Legal notice**: no BIOS files included; use only dumps you own.
  4. **Install** (`pipx install beck-bios` or `uv tool install beck-bios` once published, with the git-URL
     form until then).
  5. **Quick start**: generate the report on Recalbox → `beck config init` → put files in the source folder →
     `beck check --dry-run` → `beck check`.
  6. **Safety**: nothing is deleted unless you ask (`--move`, `--clean-unmatched`).
  7. **Configuration** (link), **Automation and AI agents** (`--json`, exit codes; link), **Troubleshooting**
     (link), **Contributing** (link), **License** (GPL-3.0-only).
- **Files:** `README.md`
- **Done when:** A reader can go from zero to a successful dry run using only the README and its links.
- **Verify:** `uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `docs(readme): rewrite for installation, quick start and safety`

### 08.2 — User guide: generating the report on Recalbox
- [x] Done (2026-11-06: the owner generated a report on the Recalbox 10.1.1 VM, as other sign-offs did (DEC-51, DEC-52), and the agent confirmed it over SSH, read-only, with the owner's OK: the file was at the path the guide gives, dated that
  minute. The real-device run is still step 10.11. The owner's screen said 21 not found and 151 correct, and the report listed 81 entries, so the guide says to go by the report. All 81 parsed, with none refused by 07.6. Beyond the list
  below: links from `README.md` and `AGENTS.md`.)
- **What:** `docs/user-guide/generate-report.md`: the exact menu path to generate `missing_bios_report.txt`
  for each Recalbox version that has a fixture (DEC-09), where the file ends up, and how to check it's there
  (SMB share or local path). **The owner confirms the menu path** (it was recorded during 03.13). Add a
  placeholder slot for screenshots; screenshots are optional and must not show personal data.
- **Files:** `docs/user-guide/generate-report.md`
- **Done when:** The owner has checked the steps on their device.
- **Verify:** Owner sign-off, plus the link test.
- **Commit message:** `docs(guide): explain how to generate the missing BIOS report on Recalbox`

### 08.3 — Troubleshooting guide
- [ ] Done
- **What:** `docs/troubleshooting.md`, organized by **symptom → cause → fix**, each tied to the exit code and
  message BECK prints. Cover at least:
  - `recalbox.local` doesn't resolve (mDNS on Windows; use the IP address);
  - connection refused or timeout;
  - authentication failed (guest vs user);
  - share not found;
  - report not found (not generated yet);
  - a file "not matched" (wrong dump, zipped file, wrong region);
  - permission denied on the target;
  - a Windows path or long-path issue.
- **Files:** `docs/troubleshooting.md`, `README.md` (replace its short table with a link)
- **Done when:** Every `BeckError` subclass and exit code appears in at least one entry.
- **Verify:** `uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `docs: add troubleshooting guide keyed by error message`

### 08.4 — Generated CLI reference with a sync test
- [ ] Done
- **What:** `scripts/gen_cli_reference.py` renders `beck --help` and every subcommand's `--help` into
  `docs/cli-reference.md` (standard library only, with a fixed terminal width via the `COLUMNS` env var so the
  output is stable). Add `tests/test_cli_reference.py`, which fails if the file is out of date. The
  hand-written `docs/cli.md` (06.1) stays the narrative guide and links to the reference.
- **Files:** `scripts/gen_cli_reference.py`, `docs/cli-reference.md`, `tests/test_cli_reference.py`
- **Done when:** Changing a flag's help text without regenerating the file fails the test.
- **Verify:** `uv run python scripts/gen_cli_reference.py && git diff --exit-code docs/cli-reference.md && uv run pytest tests/test_cli_reference.py -q`
- **Commit message:** `docs(cli): generate the command reference from argparse`

### 08.5 — Docstrings
- [ ] Done
- **What:** Enable ruff's `D` rules with the Google convention for `src/` (not for tests). Write docstrings for
  every public module, class and function, explaining *why* where it isn't obvious, not restating the
  signature.
- **Files:** `pyproject.toml`, `src/beck/**`
- **Done when:** `ruff check` passes with `D` rules enabled for `src/`.
- **Verify:** `uv run ruff check .`
- **Commit message:** `docs(code): add docstrings to the public API`

### 08.6 — Changelog with git-cliff (DEC-20)
- [ ] Done
- **What:**
  - `cliff.toml`: Keep a Changelog layout; sections mapped from Conventional Commit types (feat → Added,
    fix → Fixed, refactor/perf → Changed, `!` → a **Breaking** marker, docs/test/ci/build/chore hidden or
    grouped).
  - Commits from before the roadmap aren't conventional: list them under "Earlier history" in a single
    `0.1.0` entry dated 2023-12-31 → 2025-07-21, instead of dropping them.
  - Generate `CHANGELOG.md` with a pinned version: `uvx git-cliff@<version> -o CHANGELOG.md`. Add the
    regeneration command to `docs/maintenance.md` and to the release steps (stage 10).
- **Files:** `cliff.toml`, `CHANGELOG.md`, `docs/maintenance.md`
- **Done when:** `CHANGELOG.md` shows the roadmap stages' changes under `Unreleased`, grouped correctly.
- **Verify:** `uvx git-cliff -o CHANGELOG.md && git diff --stat CHANGELOG.md` (only the expected changes)
- **Commit message:** `docs(changelog): generate CHANGELOG.md with git-cliff`

### 08.7 — License notices (DEC-13)
- [ ] Done
- **What:** Add `# SPDX-License-Identifier: GPL-3.0-only` as the first comment line of every Python file in
  `src/`, `scripts/` and `tests/`. Add `tests/test_license_headers.py`, which fails if any tracked `.py` file
  lacks it. State "GPL-3.0-only" in the README's License section, and keep `LICENSE` unchanged.
- **Files:** `**/*.py`, `tests/test_license_headers.py`, `README.md`
- **Done when:** The license-header test passes and a new file without the header fails it.
- **Verify:** `uv run pytest tests/test_license_headers.py -q`
- **Commit message:** `chore(license): add SPDX identifiers to source files`

### 08.8 — Close the stage
- [ ] Done
- **What:** Update AGENTS.md: docs map, "regenerate the CLI reference and changelog when you change flags or
  release". Re-score [00-assessment](00-assessment.md#re-scoring-history) and mark D13 fully fixed. Update the
  [README](README.md#stages) status. Push the closing commit (DEC-47). If the stage PR doesn't exist yet, print
  this command for the human (DEC-43):

  ```sh
  gh pr create --base main --title "Stage 08: documentation" --body "Closes roadmap stage 08."
  ```

- **Files:** `AGENTS.md`, `roadmap/00-assessment.md`, `roadmap/README.md`, this file
- **Done when:** The PR is merged with a merge commit.
- **Verify:** The full check suite in AGENTS.md passes.
- **Commit message:** `docs(roadmap): close stage 08 and re-score assessment`

## Stage acceptance criteria
- README, guide, troubleshooting, CLI reference, JSON docs, architecture, ADRs, security and maintenance docs all
  exist and link correctly.
- The changelog and CLI reference are generated, not hand-maintained.

## Out of scope
- A docs website (DEC-30). Translations (optional item in stage 11).

## Agent notes
- Write for a Recalbox user first: short sentences, exact menu names, copy-pasteable commands. Keep technical
  depth in `docs/ARCHITECTURE.md`.
