# AGENTS.md

Instructions for AI coding agents (any vendor) and for humans working on **BECK**. This is the **only**
agent-instructions file in the repository (DEC-21). Don't create vendor-specific copies (see
[Agent tooling notes](#agent-tooling-notes)).

## Project overview

BECK (BIOS checker for Recalbox) matches a user's BIOS files against the MD5 hashes in the missing-BIOS
report that Recalbox generates, then copies the matching files, under the expected names, into the right
folders on the Recalbox over SMB.

**Status (2026-11-06):** prototype, not published yet. The application is the `beck` package in `src/beck/`, with a pure
core and adapters around it ([design](docs/ARCHITECTURE.md)). Its [known defects are fixed](roadmap/00-assessment.md#defects),
and it never renames local files, or deletes them unless `--move` or `--clean-unmatched` asks for it. The repository around it has tooling and
CI: lint, types, tests on Python 3.11–3.14 with a coverage gate, tests against a real Samba server, commit-message, secret and dependency checks. It is being improved stage by stage following
[roadmap/README.md](roadmap/README.md). The target is an installable CLI `beck` published on PyPI as `beck-bios`.

## Repository map

| Path | What it is |
|---|---|
| `check_bios.py` | A deprecated shim: it prints a notice and runs `beck.cli.main` with its own folder, importing from `src/` so that the pip route works. |
| `src/beck/` | The application ([design](docs/ARCHITECTURE.md)): `cli`, `config`, `credentials`, `models`, `hashing`, `matcher`, `executor`, `errors`, and `frontends/`, `transports/`, `output/`. `beck` finds its [settings](docs/cli.md#settings) from any folder, and `bios/` in the current one. |
| `bios/` | Input folder for the user's BIOS files. Everything except `bios/.keep` is gitignored. |
| `pyproject.toml`, `uv.lock`, `.python-version` | Project metadata, runtime and dev dependencies, tool settings (ruff, mypy, pytest, coverage, commitizen), the lockfile, and Python 3.11 for local work. Managed with uv; `exclude-newer` is the 14-day cooldown (DEC-45). The distribution is `beck-bios`, built with `uv_build` (DEC-18), and it installs the `beck` command. |
| `requirements.txt` | Runtime dependencies for pip users, **generated** from `uv.lock` (see [Commands](#commands)). Don't edit it by hand; CI fails if it drifts. |
| `tests/` | pytest suite: `tests/unit/` has a test file per module, full runs through `cli.main` (`test_cli.py`), and the architecture rules checked on the source (`test_architecture.py`). `tests/` has the package and shim tests, the Markdown link checker, and tests for the hygiene guard and the workflow pins. `tests/factories.py` builds test data (always random bytes, and reports in the real format), and `tests/fakes.py` is the in-memory SMB server the application tests use. `tests/fixtures/reports/` holds real and derived Recalbox reports, with provenance in `tests/fixtures/README.md`; the real report keeps its CRLF line endings byte-exact. |
| `tests/integration/samba/` | The Samba test server for integration tests, built with **Podman, never Docker** (DEC-55). See [its README](tests/integration/samba/README.md). |
| `scripts/check_repo_hygiene.py` | Fails if git tracks BIOS/ROM-like files, files over 1 MiB, or config files (each allowed exception has a reason). |
| `.github/workflows/ci.yml` | CI on every PR and push to `main`: `quality`, the `tests` matrix (Linux × Python 3.11–3.14; Windows and macOS removed, DEC-49) summarized by `tests-passed`, `integration` (a real Samba server, with Podman), `commits`, `secrets`, `sca`. |
| `.github/workflows/security.yml` | Weekly (Mondays 06:00 UTC): full-history secret scan and dependency scan. |
| `.gitleaks.toml`, `.trivyignore` | gitleaks settings (fake `beck-test-*` values allowed only under `tests/`); accepted Trivy findings, each with a link and an expiry date. |
| `.editorconfig`, `.gitattributes` | Editor settings; LF line endings in the repository. |
| `roadmap/` | The improvement plan: [index and decision log](roadmap/README.md), [assessment](roadmap/00-assessment.md), one file per stage. |
| `docs/agents.md` | Which AI agents were tested loading this file, and how to test another one. |
| `docs/ARCHITECTURE.md` | [The design](docs/ARCHITECTURE.md): the core is pure and adapters do the I/O. Data flow, and the rules to keep, which `tests/unit/test_architecture.py` enforces. Read it before changing `src/beck/`. |
| `docs/cli.md` | [The `beck` command](docs/cli.md): commands, flags, exit codes and what gets deleted. |
| `docs/json-output.md`, `docs/schemas/` | [The `--json` output](docs/json-output.md) and its JSON Schema files: a **public contract** (DEC-23). Ask the owner before changing an existing field. `tests/unit/test_json_contract.py` checks every kind of document against the schemas, and its `V1_FIELDS` records what version 1 promises, so a new field goes in the output, the schema, the guide and that record. |
| `docs/spikes/` | Results of technical experiments, such as [`smbprotocol` vs `pysmb`](docs/spikes/smbprotocol.md). |
| `docs/maintenance.md` | [Monthly maintenance routine](docs/maintenance.md): dependency upgrades, pin refreshes, security review (replaces an update bot, DEC-29). Follow it when asked to update dependencies, or when the weekly *Security* run or an expired `.trivyignore` entry fails. |
| `.github/pull_request_template.md` | PR description template with the roadmap checklist. Fill it in when preparing a PR description for the human. |
| `docs/adr/` | [Architecture Decision Records](docs/adr/README.md): the reasoning and rejected alternatives behind every DEC. Read the relevant ADR before proposing to change a decision. |
| `README.md` | User-facing readme: install with pip or uv, configure, run, the legal notice. It says BECK deletes local files only when asked. The full rewrite is step 08.1. Development commands are in [Commands](#commands) below. |
| `LICENSE` | GNU GPL v3 text. Package metadata uses `GPL-3.0-only` (DEC-13). |

## Commands

Prerequisite: [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs Python 3.11 (from
`.python-version`) by itself. CI runs exactly these commands (DEC-25).

```sh
uv sync                                       # create .venv with runtime and dev dependencies from uv.lock
uv run ruff format .                          # format the code (CI runs `uv run ruff format --check .`)
uv run ruff check .                           # lint, including the S security rules (DEC-32)
uv run mypy                                   # type-check: strict everywhere
uv run pytest                                 # tests; they never touch the network or a device
uv run python scripts/check_repo_hygiene.py   # no BIOS files, large files or tracked config files
uv build                                      # build the wheel and sdist into dist/ (ignored by git)
```

Integration tests need the [Samba test server](tests/integration/samba/README.md), and are skipped without it:

```sh
podman build -t beck-samba tests/integration/samba && podman run -d --rm -p 127.0.0.1:4450:445 --name beck-samba beck-samba
BECK_TEST_SMB_HOST=127.0.0.1 BECK_TEST_SMB_PORT=4450 uv run pytest -m integration
```

Before committing, this must pass; it's what the `quality` and `tests` CI jobs run:

```sh
uv lock --check && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv run python scripts/check_repo_hygiene.py
```

- **After any change to dependencies**, regenerate the pip file: `uv export --no-dev --no-hashes --no-emit-project -o requirements.txt`.
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
- `uv run python check_bios.py`, `uv run beck` and `uv run beck check` connect to whatever target your settings name, which may be a **real Recalbox**, over SMB, and upload files to it. Don't run them unless the human explicitly asks you to in this session. `uv run beck config init` writes to your home folder.

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
  unless an explicit opt-in flag asks for it, and only `executor.py` may delete (a test enforces this). Files on the device are kept unless `--overwrite` is passed (DEC-61).
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

## Using BECK as a tool

For an agent asked to run BECK on someone's files, rather than to change its code. [JSON output](docs/json-output.md) has every
field, with [the schemas](docs/schemas/), and [the `beck` command](docs/cli.md) has every flag.

1. **Look first.** Always run `beck --json check --dry-run …` first, and show the human the plan: `uploads` (with `replaces` and
   `warning`), `incorrect`, `still_missing`, `unreadable` and `deleted`. A dry run changes nothing, but it does connect to the target,
   so use only a target the human named. `beck --json scan --source DIR` and `beck --json report --report-file FILE` work with no
   network.
2. **Parse stdout as JSON, and branch on the exit code.** Stdout holds one document, even for an error or a bad flag, and logs go to
   stderr. Check that `schema_version` is `1`. The exceptions: `--help` and `--version` print text, and Ctrl-C prints no document.

   | Exit code | What it means | What to do |
   |---|---|---|
   | 0 | The run finished. Files may still be missing. | Tell the human what's in `still_missing` and `incorrect`. |
   | 1 | A bug in BECK. | Stop, and show the human stderr. The lists can't be trusted, because a bug can stop a run partway. |
   | 2 | A bad flag or setting, or a deletion nobody confirmed. Nothing changed. | Read `errors`. Don't answer a refused deletion by adding `--yes`. |
   | 3 | The target failed, or some items did, and the others finished. | Read `errors`, and `uploads[].status`, before running it again. |
   | 4 | No report, or one BECK can't read. | Ask the human to generate a new one on the device. |
   | 5 | `--fail-if-missing` found required files missing or incorrect. `errors` is empty. | Tell the human what's in `still_missing` and `incorrect`. |

3. **Never add `--yes`, `--overwrite`, `--move` or `--clean-unmatched` without the human's explicit approval in this session,** for
   this run. `--overwrite` keeps no copy of what it replaces. `--move` and `--clean-unmatched` delete local files, and `--clean-unmatched` can
   delete [good BIOS files](docs/cli.md#what-beck-deletes-and-when) after a rescan. First run the same command with `--dry-run`, and
   show the human `deleted` and `replaces`. `--json` never asks, so `--yes` would be what confirms the deletion, on the human's behalf.
4. **Never pass passwords on the command line,** where anyone can read them, and that includes setting `BECK_SMB_PASSWORD` in a command you
   run, which ends up in shell history and logs. BECK refuses a `--target` URL holding a password, with exit code 2. With a user and no
   password, `--json` exits with 2, because it never asks: tell the human, who can set the variable or run BECK themselves. Don't show
   anyone what's in an old `config/config.yml`.

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

- Keep changes minimal and focused on the current step.
- Enforced by CI: `ruff format` and `ruff check` (including the `S` security rules), and `mypy` strict for new
  code. Also expected: type hints everywhere, `pathlib` for paths, no bare `except:`, and `sys.exit` only at the CLI
  boundary. There are no ruff or mypy exemptions for BECK's own code, only the mypy import override for `pysmb`. Don't add new ones.
- Pure core (`models`, `hashing`, `matcher`) with device and network I/O only in adapters (`frontends/`,
  `transports/`, `output/`). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and its rules.
- MD5 is used to **identify** files, not for security: `hashlib.md5(..., usedforsecurity=False)`.

## Testing

- **Unit tests,** `uv run pytest` (pytest + pytest-cov), need nothing else. CI runs them on Linux with Python 3.11–3.14 (not on
  Windows or macOS, DEC-49), and uploads `coverage.xml` as a workflow artifact. Write tests that don't depend on the platform
  to catch Windows-only bugs, e.g. assert that a file handle is closed rather than relying on Windows locking.
- **Integration tests** (`tests/integration/`, marked `integration`) run against the Samba test server, started with Podman as in
  [Commands](#commands). They skip themselves without `BECK_TEST_SMB_HOST` and `BECK_TEST_SMB_PORT`, but CI fails if any is
  skipped. They refuse any server without the test server's seeded file, so that they can't write to a real device. Never
  work around that.
- Unit tests replace pysmb with the fake from `tests/fakes.py` (`install_fake_smb(monkeypatch)`, which also
  fails any real socket connection) and work in `tmp_path`, never in the repository folder.
- Every bug fix ships with a regression test. `uv run pytest --cov` fails below 90 % branch coverage on the package, and
  `# pragma: no cover` doesn't work here. Integration tests don't count towards that.
- **Never real BIOS bytes.** Test files are random bytes (`tests/factories.py`); MD5 values and file names are fine. Tests never
  touch the network, except the local Samba test server.
- Color settings in your shell can't affect results: `tests/conftest.py` sets `NO_COLOR` for every test.

## Commits and pull requests

- **Conventional Commits** (`type(scope): summary`, with types such as feat, fix, docs, test, refactor, build,
  ci, chore, perf). Add `!` for breaking changes. CI checks every commit in a PR with commitizen (DEC-38).
- One branch and one PR per stage (`stage/NN-slug`), one commit per step, merged with a merge commit (DEC-14,
  DEC-39).
- `main` is protected by a ruleset: changes arrive only through a PR, merge commits only, and the checks
  `quality`, `tests-passed`, `integration`, `commits`, `secrets` and `sca` must pass. Nobody can bypass it.
- Agents commit (DEC-46) and push the stage branch (DEC-47); the human creates branches, opens and merges PRs,
  and tags (DEC-43).

## Legal

BIOS files are copyrighted. BECK only matches files the user already owns; it never includes, downloads or
distributes them. Contributions are licensed under GPL-3.0-only.

## Keeping this file current

Every stage's closing step updates this file: commands, repo map, skills index and rules. If you notice this file
is out of date with the repository, say so and propose the fix as part of your current step.
