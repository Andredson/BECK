# ADR-0003 — Tooling

- **Status:** Accepted
- **Date:** 2026-11-02
- **Decisions covered:** DEC-07, DEC-08, DEC-17, DEC-18, DEC-19, DEC-24, DEC-26, DEC-27, DEC-28, DEC-29, DEC-36,
  DEC-40, DEC-42, DEC-45, DEC-49

## Context
At baseline the project had no tooling: no lockfile, tests, linters or packaging. The owner asked that every
tool choice be explained with its purpose and alternatives rather than picked as a default. The rejected options
below were all offered with that explanation. A recurring preference from the owner: **fewer tools and
dependencies**, even where a tool was recommended.

## DEC-07 — uv, ruff, mypy, pytest
- **Decision:** uv for environments, the lockfile and building; ruff for lint and format; mypy for types; pytest for tests.
- **Alternatives considered:** *pip/venv plus the same tools* (no lockfile tool; more manual) and *Poetry*: not chosen.
- **Consequences:** One lockfile (`uv.lock`). Every check is `uv run …` (see DEC-25 and DEC-27). `requirements.txt`
  is generated from the lockfile until 1.0 (step 02.9).

## DEC-08 — Python ≥ 3.11
- **Status:** The operating-system part is superseded by [DEC-49](#dec-49--ci-on-linux-only); the Python
  versions stand.
- **Decision:** Support Python 3.11 and newer. The CI matrix is 3.11–3.14 on Linux, Windows and macOS.
- **Alternatives considered:** *3.12+* (drops some older distributions) and *keep 3.10+*: not chosen; 3.10 reached
  end-of-life in October 2026.
- **Consequences:** The standard library provides `tomllib` (DEC-24) and `hashlib.file_digest`. The monthly
  maintenance routine reviews end-of-life dates.

## DEC-17 — argparse for the CLI
- **Decision:** Use the standard-library `argparse`.
- **Alternatives considered:** *Click* (decorators, a test helper; one dependency) and *Typer* (type-hint based,
  shell completion, pretty help; several dependencies): not chosen.
- **Consequences:** No CLI dependency, but more code. Shell completion would need an extra package (and a DEC).

## DEC-18 — uv_build as the build backend
- **Decision:** Use `uv_build`; the version is bumped with `uv version --bump`.
- **Alternatives considered:** *hatchling*, optionally with `hatch-vcs` to take the version from git tags, and
  *setuptools* (more configuration, no advantage here): not chosen.
- **Consequences:** The version is a static field in `pyproject.toml`, changed in a release commit, and the release
  workflow checks that it matches the tag. `module-name = "beck"` must be set, because the distribution is called
  `beck-bios`.

## DEC-19 — platformdirs for the config folder
- **Decision:** Find the user config folder with `platformdirs` (e.g. `~/.config/beck` on Linux, `%APPDATA%\beck` on
  Windows).
- **Alternatives considered:** *Hand-rolled standard-library code* (no dependency, but we own the edge cases) and
  *the current directory only* (the problem BECK has today): not chosen.
- **Consequences:** One small runtime dependency, added in step 07.2. It's also reused for the hash cache (11.6).

## DEC-24 — TOML configuration
- **Decision:** Config files are TOML, read with the standard-library `tomllib`. PyYAML is dropped; a legacy
  `config/config.yml` gets a migration message.
- **Alternatives considered:** *Keep YAML*: not chosen; there would be no migration, but PyYAML would stay as a
  dependency only for a 4-key file.
- **Consequences:** Step 07.3 reads the legacy file with a tiny line parser, so there's no YAML dependency even for
  the migration.

## DEC-26 — smbprotocol instead of pysmb
- **Decision:** Switch to `smbprotocol` and its high-level `smbclient` API in the stage 04 transport rewrite.
- **Alternatives considered:** *Keep pysmb*: not chosen. It's already in use, has pure-Python dependencies and also
  speaks SMB1, but its lower-level API means writing our own helpers (e.g. recursive mkdir).
- **Consequences:** Heavier dependencies (`cryptography`, `pyspnego`), but SMB 2/3 with native `makedirs`, `stat`
  and file objects. **Gated:** the step 04.1 spike must show it works against a real Recalbox, including guest
  login. Otherwise a new DEC supersedes this one.

## DEC-27 — No task runner
- **Decision:** Plain `uv run …` commands, documented in AGENTS.md and CONTRIBUTING and called directly by CI.
- **Alternatives considered:** *nox* (Python sessions, local multi-version runs), *just* (needs a separate binary) and
  *Make* (awkward on Windows): not chosen.
- **Consequences:** The command list in AGENTS.md is the single source of truth, and CI must call exactly those commands.

## DEC-28 — No git hooks
- **Decision:** No pre-commit framework. Every check runs in CI.
- **Alternatives considered:** *pre-commit* (the de facto standard; recommended during planning), *prek* (a faster,
  newer reimplementation) and *lefthook*: not chosen by the owner.
- **Consequences:** Problems surface on the PR, not at commit time. A repository hygiene script (step 02.8) does in CI
  what a hook would do: block BIOS files, large files and tracked secrets.

## DEC-29 — No dependency-update bot
- **Decision:** No Dependabot or Renovate. A documented monthly manual routine instead.
- **Alternatives considered:** *Dependabot* (built into GitHub; recommended during planning) and *Renovate* (more
  configurable, multi-platform): not chosen by the owner.
- **Consequences:** Updates depend on the routine in `docs/maintenance.md` (step 02.15). The weekly Trivy scan
  (step 02.14) is the early warning for new vulnerabilities in unchanged dependencies.

## DEC-36 — No extra test tools
- **Decision:** Only pytest, pytest-cov and the Samba container.
- **Alternatives considered:** *hand-rolled golden files*, *syrupy* snapshots, *mutmut* mutation testing, and
  *hypothesis* property-based testing (offered as the recommended runtime-testing option, see DEC-33): not chosen.
- **Consequences:** CLI tests assert on key output lines, and parser robustness relies on explicit edge-case
  fixtures (step 05.2).

## DEC-40 — Own minimal Samba Dockerfile for tests
- **Decision:** Build the integration-test SMB server from our own Dockerfile: Debian-slim pinned by digest, plus the
  `samba` package and a Recalbox-like `smb.conf`.
- **Alternatives considered:** *A community Samba image* configured through env vars: less code, but you trust a
  third-party maintainer. Not chosen.
- **Consequences:** We maintain a small Dockerfile and config (step 05.4), including updating the base image digest.

## DEC-42 — A small pytest link checker
- **Decision:** A standard-library pytest test checks relative links and anchors between repository Markdown files.
- **Alternatives considered:** *lychee in CI* (also checks external URLs; sometimes flaky when sites are down) and
  *no link checking*: not chosen.
- **Consequences:** External URLs aren't checked. The test (step 02.6) runs in the normal suite and covers the
  roadmap's many cross-links.

## DEC-45 — 14-day dependency cooldown
- **Date:** 2026-11-02 (step 02.2)
- **Context:** When the dev dependencies were first added, 6 of the 20 locked packages had been published less
  than 14 days earlier (types-PyYAML 3 days; mypy 5; pyasn1, pytest and ruff 6; coverage 11). Malicious releases
  on package indexes are usually detected and yanked within days. With no update bot (DEC-29), a cooldown is a
  cheap guard that needs no new tool.
- **Decision:** `exclude-newer = "14 days"` in `[tool.uv]`. Every resolution, local or in CI, ignores
  distributions uploaded in the last 14 days. uv records the rolling span (`exclude-newer-span = "P14D"`) in
  `uv.lock`, so `uv lock --check` stays stable. An urgent security fix can bypass the cooldown for one package
  with `exclude-newer-package`; the reason is recorded in the commit and in the monthly maintenance notes.
- **Alternatives considered:**
  - *A 7-day cooldown*: half the delay for fixes, while still catching most quickly-yanked releases. Not chosen.
  - *No cooldown*, relying on Trivy and the monthly review: not chosen.
- **Consequences:** Re-locking moved six packages to slightly older releases (e.g. pyasn1 0.6.5 → 0.6.4,
  mypy 2.4.1 → 2.4.0). Dependency upgrades always lag at least 14 days behind upstream. The same rule should
  guide manual pins elsewhere (GitHub Action SHAs, gitleaks, Trivy and commitizen versions): pick releases at
  least 14 days old.

## DEC-49 — CI on Linux only
- **Date:** 2026-11-03 (before merging stage 02). Supersedes the operating-system part of
  [DEC-08](#dec-08--python--311).
- **Context:** The closing commit of stage 02 couldn't be merged. GitHub found no hosted macOS runner for one matrix
  cell, `tests (macos-latest, py3.11)`, in three attempts of about 15 minutes each, while it was showing notices
  about macOS arm64 capacity. No step ever ran, and the same cell had passed on the five previous commits. The owner
  then asked to disable the macOS and Windows checks. No reason was given for dropping Windows.
- **Decision:** The test matrix runs on `ubuntu-latest` only, for Python 3.11–3.14. CI jobs added later follow the
  same rule. DEC-08's Python versions are unchanged.
- **Alternatives considered:** None were offered; this was the owner's instruction. Waiting and re-running the cell,
  or revisiting the macOS runner choice if the problem recurred, had been mentioned just before.
- **Consequences:** CI is faster and no longer depends on macOS runner capacity. CI no longer catches bugs that only
  appear on Windows or macOS, such as D7 (a file still open when it's deleted fails on Windows): step 03.3 tests D7
  by asserting that the file is closed, and the portability score can't rise on CI evidence alone. The stage 10
  wheel smoke install runs on Linux only. To bring a platform back, add it to the `os` list in `ci.yml` and record
  a new DEC; `tests-passed` and the branch ruleset need no change.
