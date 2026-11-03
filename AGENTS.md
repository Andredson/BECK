# AGENTS.md

Instructions for AI coding agents (any vendor) and for humans working on **BECK**. This is the **only**
agent-instructions file in the repository (DEC-21). Don't create vendor-specific copies (see
[Agent tooling notes](#agent-tooling-notes)).

## Project overview

BECK (BIOS checker for Recalbox) matches a user's BIOS files against the MD5 hashes in the missing-BIOS
report that Recalbox generates, then copies the matching files, under the expected names, into the right
folders on the Recalbox over SMB.

**Status (2026-11-03):** prototype. The application is a single script, `check_bios.py`, with known defects
(D1–D16 in [roadmap/00-assessment.md](roadmap/00-assessment.md#defects)). The repository around it has tooling and
CI (stage 02): lint, types, tests on Python 3.11–3.14, commit-message, secret and dependency checks. It is being improved stage by stage following
[roadmap/README.md](roadmap/README.md). The target is an installable CLI `beck` published on PyPI as `beck-bios`.

## Repository map

| Path | What it is |
|---|---|
| `check_bios.py` | The whole application today: SMB access, report parsing, hashing, matching, upload, output. |
| `config/config.yml` | SMB settings (`user`, `passwd`, `server`, `port`). **Tracked by git until step 03.2.** Never commit real credentials. |
| `bios/` | Input folder for the user's BIOS files. Everything except `bios/.keep` is gitignored. |
| `pyproject.toml`, `uv.lock`, `.python-version` | Project metadata, runtime and dev dependencies, tool settings (ruff, mypy, pytest, coverage, commitizen), the lockfile, and Python 3.11 for local work. Managed with uv; `exclude-newer` is the 14-day cooldown (DEC-45). Not an installable package until stage 04 (`package = false`). |
| `requirements.txt` | Runtime dependencies for pip users, **generated** from `uv.lock` (see [Commands](#commands)). Don't edit it by hand; CI fails if it drifts. |
| `tests/` | pytest suite: an import smoke test that blocks file and network access, the Markdown link checker, and tests for the hygiene guard and the workflow pins. |
| `scripts/check_repo_hygiene.py` | Fails if git tracks BIOS/ROM-like files, files over 1 MiB, or config files (each allowed exception has a reason). |
| `.github/workflows/ci.yml` | CI on every PR and push to `main`: `quality`, the `tests` matrix (Linux × Python 3.11–3.14; Windows and macOS removed, DEC-49) summarized by `tests-passed`, `commits`, `secrets`, `sca`. |
| `.github/workflows/security.yml` | Weekly (Mondays 06:00 UTC): full-history secret scan and dependency scan. |
| `.gitleaks.toml`, `.trivyignore` | gitleaks settings (fake `beck-test-*` values allowed only under `tests/`); accepted Trivy findings, each with a link and an expiry date. |
| `.editorconfig`, `.gitattributes` | Editor settings; LF line endings in the repository. |
| `roadmap/` | The improvement plan: [index and decision log](roadmap/README.md), [assessment](roadmap/00-assessment.md), one file per stage. |
| `docs/agents.md` | Which AI agents were tested loading this file, and how to test another one. |
| `docs/maintenance.md` | [Monthly maintenance routine](docs/maintenance.md): dependency upgrades, pin refreshes, security review (replaces an update bot, DEC-29). Follow it when asked to update dependencies, or when the weekly *Security* run or an expired `.trivyignore` entry fails. |
| `.github/pull_request_template.md` | PR description template with the roadmap checklist. Fill it in when preparing a PR description for the human. |
| `docs/adr/` | [Architecture Decision Records](docs/adr/README.md): the reasoning and rejected alternatives behind every DEC. Read the relevant ADR before proposing to change a decision. |
| `README.md` | User-facing readme. Its install and run commands are **wrong** until step 03.1 (D13); use the [Commands](#commands) section below instead. |
| `LICENSE` | GNU GPL v3 text. Package metadata uses `GPL-3.0-only` (DEC-13). |

## Commands

Prerequisite: [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs Python 3.11 (from
`.python-version`) by itself. CI runs exactly these commands (DEC-25).

```sh
uv sync                                       # create .venv with runtime and dev dependencies from uv.lock
uv run ruff format .                          # format the code (CI runs `uv run ruff format --check .`)
uv run ruff check .                           # lint, including the S security rules (DEC-32)
uv run mypy                                   # type-check: strict, with a relaxed override for check_bios.py until stage 03
uv run pytest                                 # tests; they never touch the network or a device
uv run python scripts/check_repo_hygiene.py   # no BIOS files, large files or tracked config files
```

Before committing, this must pass; it's what the `quality` and `tests` CI jobs run:

```sh
uv lock --check && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv run python scripts/check_repo_hygiene.py
```

- **After any change to dependencies**, regenerate the pip file: `uv export --no-dev --no-hashes -o requirements.txt`.
  Adding a dependency needs a DEC first (see [Hard rules](#hard-rules)); `uv add` and `uv lock` respect the cooldown.
- **The other CI checks**, if you have the tools installed (the pinned versions are in the `env:` block of
  `.github/workflows/ci.yml`; `X` below is `COMMITIZEN_VERSION`):

  ```sh
  uvx --exclude-newer "14 days" --from "commitizen==X" cz check --rev-range origin/main..HEAD
  gitleaks git --config .gitleaks.toml --redact --log-opts="origin/main..HEAD" .
  trivy fs --scanners vuln --include-dev-deps --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --show-suppressed --skip-dirs .venv --skip-files requirements.txt .
  VIRTUAL_ENV=.venv trivy fs --scanners license --skip-dirs .venv --skip-files uv.lock .
  ```

- **Updating dependencies or pins** follows [docs/maintenance.md](docs/maintenance.md).
- `uv run python check_bios.py` connects to a **real Recalbox** over SMB and, before step 03.10, **deletes local
  files**. Don't run it unless the human explicitly asks you to in this session.

## Working on the roadmap (protocol)

1. Read [roadmap/README.md](roadmap/README.md): the stage table, the step format and the decision log.
2. Take the **first unchecked, unblocked step** of the lowest-numbered stage that isn't done (stage 12 may run
   in parallel after stage 02).
3. Do **only that step**. Put unrelated improvements in the PR description as proposals, not in the diff.
4. Run the step's **Verify** command(s), and the standard checks once they exist (stage 02+).
5. Tick the step's box and update the stage **Status** in the same change.
6. **Commit** the step yourself (DEC-46), with no `Co-Authored-By` or other attribution trailer:
   ```sh
   git add <files touched by the step>
   git commit -m "<the step's Commit message>"
   ```
   Then push the current stage branch with a plain `git push` (DEC-47). Before a stage's first step, ask the
   human to create the branch (`git switch -c stage/NN-slug`), as a one copy-paste line.
7. On a stage's closing step, print the `gh pr create` command for the human. The human merges with a
   **merge commit** (DEC-39).
8. If the step needs something missing (data, access, a human-only setting), mark it `BLOCKED` as described in
   the roadmap README and move to the next unblocked step.

## Hard rules

- **Commit and push yes; branches, PRs and tags no.** You may `git add`, `git rm --cached` and `git commit`
  (DEC-46), with **no** `Co-Authored-By` or other attribution trailer, and push the **current stage branch** with
  a plain `git push` after each step (DEC-47). Never push to `main`, never force-push, never push tags. Never
  run `git tag`, `git switch -c` / `git checkout -b` / `git branch <name>`, `gh pr create` / `gh pr merge` /
  `gh release`, and never rewrite history (`commit --amend` on pushed commits, `rebase`, `reset --hard`). Hand
  those over to the human as one copy-paste line (DEC-43). Read-only git and gh (`status`, `diff`, `log`,
  `gh run view`, `gh pr view`) are fine.
- **No BIOS files, ever.** Never add, download, generate from real dumps, or commit BIOS/ROM files. Tests use
  random bytes. MD5 values and file names are fine.
- **No real credentials or personal data.** Never write a real password anywhere in the repo, in logs or in test
  output. Reports used as fixtures must be anonymized. Fake test credentials must look obviously fake (e.g.
  `beck-test-password`).
- **Non-destructive by default (DEC-02).** Code you write must never delete or rename a user's local file
  unless an explicit opt-in flag asks for it. Remote overwrites follow the policy decided in step 06.5.
- **No real devices without explicit OK.** Don't connect to a real Recalbox or SMB server unless the human asks
  in this session. Use the local transport, fakes, or the Samba test container (stage 05).
- **No silent tools or dependencies.** Don't add a library, tool, service, GitHub Action or bot that isn't in the
  [decision log](roadmap/README.md#decision-log). Explain to the human what it's for, give 2–4 alternatives with
  trade-offs and a recommendation, and record the answer as a new DEC and in an ADR
  ([how to](docs/adr/README.md#adding-a-decision)) before using it.
- **Python ≥ 3.11 compatible** (DEC-08): no syntax or stdlib APIs newer than 3.11 unless guarded.
- **Respect the 14-day dependency cooldown** (DEC-45, `exclude-newer` in `pyproject.toml`). Never remove or shorten
  it to get a newer release; ask the human. Pin GitHub Actions and downloaded tools to releases at least 14 days
  old as well.
- **Vendor-neutral.** Project knowledge goes in this file, `docs/`, or `.agents/skills/`, never in
  vendor-specific files.

## Agent tooling notes

- **AGENTS.md is read natively** by most coding agents. For Claude Code (≥ 2.1.277) this only holds while there
  is **no** `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` in the working directory or above it, so
  **don't create those files**. If you personally need a `CLAUDE.local.md`, set *Project instructions* to
  `claude-md-and-agents-md` in Claude Code's `/config` so this file still loads.
- **Gemini CLI** users can point their own (user-level) `context.fileName` setting at `AGENTS.md`. Don't add
  `.gemini/` to the repo.
- The tested support matrix, and the procedure for testing another agent, live in
  [docs/agents.md](docs/agents.md). Tested so far: Claude Code and opencode (DEC-44).

### Skills

Agent Skills live in `.agents/skills/<name>/SKILL.md` (open agentskills.io format, DEC-22). When a task matches a
skill below, **read its whole `SKILL.md` before acting** and follow it.

| Skill | Path | Use it when |
|---|---|---|
| *(none yet; added in stage 09)* | | |

## Code style

- Today: one script. Keep changes minimal and focused on the current step.
- Enforced by CI: `ruff format` and `ruff check` (including the `S` security rules), and `mypy` strict for new
  code. Also expected: type hints everywhere, `pathlib` for paths, no bare `except:`, and `sys.exit` only at the CLI
  boundary. `check_bios.py` still has per-file ruff ignores and a relaxed mypy override; each entry names the
  stage 03 step that removes it. Don't add new ones.
- From stage 04: pure core (`models`, `hashing`, `matcher`) with I/O only in adapters (`frontends/`,
  `transports/`, `output/`). See `docs/ARCHITECTURE.md` once it exists.
- MD5 is used to **identify** files, not for security: `hashlib.md5(..., usedforsecurity=False)`.

## Testing

- `uv run pytest` (pytest + pytest-cov). CI runs it on Linux with Python 3.11–3.14 (not on Windows or macOS,
  DEC-49), and uploads `coverage.xml` as a workflow artifact. Write tests that don't depend on the platform
  to catch Windows-only bugs, e.g. assert that a file handle is closed rather than relying on Windows locking. Today the suite covers repository tooling and an import smoke
  test, not the application's behavior.
- From stage 03: every bug fix ships with a regression test. From stage 05: ≥ 90 % branch coverage on the
  package, plus integration tests against the Samba container (marked `integration`).
- Tests never touch the network (except the local Samba container) and never use real BIOS content.

## Commits and pull requests

- **Conventional Commits** (`type(scope): summary`, with types such as feat, fix, docs, test, refactor, build,
  ci, chore, perf). Add `!` for breaking changes. CI checks every commit in a PR with commitizen (DEC-38).
- One branch and one PR per stage (`stage/NN-slug`), one commit per step, merged with a merge commit (DEC-14,
  DEC-39).
- `main` is protected by a ruleset: changes arrive only through a PR, merge commits only, and the checks
  `quality`, `tests-passed`, `commits`, `secrets` and `sca` must pass. Nobody can bypass it.
- Agents commit (DEC-46) and push the stage branch (DEC-47); the human creates branches, opens and merges PRs,
  and tags (DEC-43).

## Legal

BIOS files are copyrighted. BECK only matches files the user already owns; it never includes, downloads or
distributes them. Contributions are licensed under GPL-3.0-only.

## Keeping this file current

Every stage's closing step updates this file: commands, repo map, skills index and rules. If you notice this file
is out of date with the repository, say so and propose the fix as part of your current step.
