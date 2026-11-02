# ADR-0003 — Tooling

- **Status:** Accepted
- **Date:** 2026-11-02
- **Decisions covered:** DEC-07, DEC-08, DEC-17, DEC-18, DEC-19, DEC-24, DEC-26, DEC-27, DEC-28, DEC-29, DEC-36,
  DEC-40, DEC-42

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
