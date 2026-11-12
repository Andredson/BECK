# BECK Roadmap

This folder is the improvement plan for BECK (BIOS checker for Recalbox). Each **stage** is its own file and is
executed **one step at a time**, by a human or an AI agent, in the order below. The checkboxes in these files are the
**only** progress tracker (DEC-16): there are no GitHub milestones or issues mirroring them.

- Baseline review and scores: [00-assessment.md](00-assessment.md)
- Agent instructions for this repository: [../AGENTS.md](../AGENTS.md)

## Stages

| # | Stage | Depends on | Branch | Effort | Status |
|---|---|---|---|---|---|
| 00 | [Assessment](00-assessment.md) | — | — | — | Done (baseline 2026-11-02) |
| 01 | [Agent-ready repository](01-agent-ready-repo.md) | — | `stage/01-agent-ready-repo` | S | Done (2026-11-02) |
| 02 | [Foundation tooling & CI](02-foundation-tooling-and-ci.md) | 01 | `stage/02-foundation` | M | Done (2026-11-03) |
| 03 | [Critical fixes & data safety](03-critical-fixes-and-data-safety.md) | 02 | `stage/03-critical-fixes` | M | Done (2026-11-04) |
| 04 | [Architecture refactor](04-architecture-refactor.md) | 03 | `stage/04-architecture` | L | Done (2026-11-04) |
| 05 | [Testing hardening](05-testing-hardening.md) | 04 | `stage/05-testing` | M | Done (2026-11-05) |
| 06 | [CLI, UX & machine-readable output](06-cli-ux-and-machine-output.md) | 05 | `stage/06-cli` | M | Done (2026-11-06) |
| 07 | [Configuration & security](07-configuration-and-security.md) | 06 | `stage/07-config-security` | M | Done (2026-11-06) |
| 08 | [Documentation](08-documentation.md) | 07 | `stage/08-docs` | M | Done (2026-11-06) |
| 09 | [Agent Skills & automation](09-agent-skills-and-automation.md) | 08 | `stage/09-skills` | M | Done (2026-11-06) |
| 10 | [Packaging & release](10-packaging-and-release.md) | 09 | `stage/10-release` | M | Done (2026-11-11) |
| 11 | [Feature expansion](11-feature-expansion.md) | 10 | one branch per feature | L | Done (2026-11-12) |
| 12 | [Community & governance](12-community-and-governance.md) | 02 (can run in parallel with 03–11) | `stage/12-community` | S | Done (2026-11-09) |

Why this order: make the repository agent-ready first, because agents will execute most of the remaining work →
put tooling and CI in place so every later step is gated → fix the data-loss bugs with regression tests → refactor
under that safety net → then the CLI, configuration, docs, skills, release, and new features.

## How to execute a step (humans and agents)

1. Open the **lowest-numbered stage whose status is not Done** (stage 12 may be worked on in parallel once 02 is done).
2. Pick the **first step whose box is unchecked** (`- [ ] Done`) and that is not blocked.
3. Do **only that step**. Don't start the next step or fix unrelated things, even small ones. Note those as a
   proposal in the PR description instead.
4. Run the step's **Verify** command(s) and make sure they pass. When CI exists (stage 02+), also run the
   standard checks listed in [AGENTS.md](../AGENTS.md).
5. Tick the box (`- [x] Done`) in the same change, and update the stage's **Status** line.
6. Commit with the step's **Commit message** (Conventional Commits, DEC-14). Per **DEC-46**, an AI agent may
   stage and commit itself, with **no** `Co-Authored-By` or other attribution trailer:

   ```sh
   git add <files touched by the step>
   git commit -m "<commit message from the step>"
   ```

   Then, per **DEC-47**, the agent pushes the current stage branch with a plain `git push`: never `--force`,
   never to `main`, never tags. Creating branches, tagging, and opening or merging PRs stay human-only (DEC-43).
   The agent prints those commands as one copy-paste line, e.g. `git switch -c stage/NN-slug` before a
   stage's first step.

7. When the last step of a stage is done, run the stage's **Closing step**: update AGENTS.md, re-score
   [00-assessment.md](00-assessment.md), then the agent pushes the closing commit (DEC-47). If the stage PR doesn't
   exist yet, the agent prints the `gh pr create` command and the human opens it (DEC-43). The PR is merged with a
   **merge commit** (DEC-39) after CI is green.

### Blocked steps
If a step needs something that isn't available (e.g. a real Recalbox report, a human-only GitHub setting), leave the
box unchecked, add `> BLOCKED (YYYY-MM-DD): <reason>` under it, and continue with the next unblocked step in
the same stage. A stage can't be closed while it has blocked steps.

### When a decision is missing
If a step needs a choice that isn't in the decision log below (a new tool, library, service, or behavior),
**stop and ask the project owner**. Explain what the tool is for, give 2–4 alternatives with trade-offs, and
recommend one. Record the answer as a new `DEC-NN` row here, and record the reasoning and the rejected
alternatives in an ADR ([how to](../docs/adr/README.md#adding-a-decision)). Never introduce a dependency or
tool silently.

### Changing a decision
Don't edit an existing row. Add a new row that says `Supersedes DEC-NN`, mark the old ADR section as superseded
([how to](../docs/adr/README.md#changing-a-decision)), and update the affected stage files.

## Step format used in every stage file

```markdown
### NN.M — Short title
- [ ] Done
- **What:** the change, concretely.
- **Files:** files created or modified.
- **Done when:** observable acceptance criteria.
- **Verify:** exact command(s) to run.
- **Commit message:** `type(scope): summary`
- **Blocked by:** (only when gated) what must exist first.
```

## Maintaining this roadmap

- **Re-score at every stage close.** Each stage's closing step re-scores [00-assessment.md](00-assessment.md#re-scoring-history) and
  adds a row to its history.
- **New stages are new files,** `13-<slug>.md` and on, added to [the stage table](#stages). Copy an existing stage's layout: the
  **Status** line (status, dependencies, branch, effort), then *Goal*, *Why*, *Decisions applied*, *Steps* in
  [the step format](#step-format-used-in-every-stage-file) ending with a closing step, *Stage acceptance criteria*, *Out of scope* and
  *Agent notes*. A stage may add a reference section before its steps, as 06 and 07 do.
- **Completed stages stay** in this folder, as the history of what was done and why.
- **A decision is never edited.** A change is a new DEC row that says *Supersedes DEC-NN*
  ([how](#changing-a-decision)).
- **There's no scheduled review of the whole roadmap,** by the owner's choice (2026-11-09). Python end-of-life dates are checked in
  the [monthly maintenance routine](../docs/maintenance.md#5-python-versions).

## Decision log

All decisions confirmed with the project owner. DEC-01 to DEC-43 were made on 2026-11-02 while planning;
later rows give their own date and step. The reasoning and rejected alternatives for every row are in the
[Architecture Decision Records](../docs/adr/README.md).

### Product and scope

| ID | Decision |
|---|---|
| DEC-01 | Vision: an installable CLI tool with the command `beck`. |
| DEC-02 | Non-destructive by default: copy only. Deleting local files is opt-in (`--move`, `--clean-unmatched`); `--dry-run` previews everything. |
| DEC-03 | Recalbox first, behind a pluggable frontend-adapter interface; Batocera / RetroBat / RetroPie in a late stage. |
| DEC-04 | Transports: SMB plus a local path (mounted SD card / USB, or running on the device). SSH/SFTP deferred. |
| DEC-09 | The owner supplies real, anonymized `missing_bios_report.txt` files per Recalbox version as fixtures; parser work is gated on them. Supported versions = versions with fixtures. |
| DEC-10 | Credentials: gitignored config with a committed example, `BECK_*` environment variables, `getpass` prompt, guest/anonymous supported (Recalbox default). |
| DEC-12 | Open to outside contributors. |
| DEC-13 | License metadata: SPDX `GPL-3.0-only`. |
| DEC-15 | PyPI distribution name `beck-bios`; the command stays `beck`. |
| DEC-75 | **Supersedes DEC-04's deferral of SSH/SFTP.** Two stage 11 features are dropped: 11.6, the hash cache, and 11.11, an SSH/SFTP transport. Their steps stay in the roadmap, marked as dropped. *(2026-11-11, before step 11.1)* |
| DEC-76 | **Supersedes the part of DEC-75 that kept dropped steps in the roadmap.** 11.10, translations, is dropped too. Dropped features are removed from the stage file, and this log keeps the record: 11.6, 11.10 and 11.11 are gone from `11-feature-expansion.md`, and the other steps keep their numbers. *(2026-11-11, before step 11.1)* |
| DEC-77 | Support for other systems leaves the roadmap: steps 11.7 (Batocera), 11.8 (RetroBat) and 11.9 (RetroPie and Lakka research) become GitHub issues [#21](https://github.com/Andredson/BECK/issues/21), [#22](https://github.com/Andredson/BECK/issues/22) and [#23](https://github.com/Andredson/BECK/issues/23), for the owner or any contributor to develop later. DEC-03's adapter interface stays. *(2026-11-11, before step 11.1)* |
| DEC-79 | **BECK asks Recalbox's web API what's missing (step 11.2).** For an SMB target, `check` and `report` first send `GET http://<host>:81/api/bios`, and read the report on the device only if that doesn't give a list they can read, with a warning. `--no-api` skips the API, and folder targets and `--report-file` never use it. It uses the standard library's HTTP client, with no new dependency. `--json` gets `missing_from`: `api`, `report` or `report_file`. *(2026-11-11, step 11.2)* |

### AI-agent support

| ID | Decision |
|---|---|
| DEC-05 | AI support = AGENTS.md + machine-readable output (`--json`, stable exit codes) + Agent Skills. **No MCP server.** |
| DEC-06 | AGENTS.md is created together with this roadmap (not deferred to a stage). |
| DEC-21 | AGENTS.md **only**: no `CLAUDE.md`, `GEMINI.md`, `.gemini/` or other vendor shims. |
| DEC-22 | Skills live in `.agents/skills/<name>/SKILL.md` (agentskills.io format, spec fields only) and are indexed in AGENTS.md. No vendor folders or symlinks. |
| DEC-23 | `--json` output carries `schema_version`, is described by a JSON Schema file, and is checked by contract tests; exit codes 0–5 are documented. `jsonschema` is a dev-only dependency. |
| DEC-43 | Agents never commit, push, create branches, push tags or open PRs. They print the exact `git` / `gh` commands for the human to run. |
| DEC-46 | **Supersedes the commit part of DEC-43.** Agents may stage (`git add`, `git rm --cached`) and run `git commit` with the step's message, never adding a `Co-Authored-By` or other attribution trailer. Pushing, creating or switching branches, tags, PRs, merges and releases stay human-only; agents hand those over as one copy-paste line. *(2026-11-02, before step 02.8)* |
| DEC-47 | **Supersedes the push part of DEC-43.** After committing a step, agents may push the **current stage branch** with a plain `git push`: never `--force` / `--force-with-lease`, never directly to `main`, never tags. Creating branches, PRs, merges, tags and releases stay human-only. *(2026-11-02, before step 02.10)* |
| DEC-44 | The agent support matrix (`docs/agents.md`) covers only agents the owner actually uses (2026-11-02: Claude Code, opencode). Other agents are added when a contributor tests one. *(2026-11-02, step 01.3)* |
| DEC-69 | A PR must say whether AI tools helped write it, by ticking one of two boxes in the PR template, and name the tools if they did. A reviewer checks it; nothing automatic enforces it. *(2026-11-07, step 12.3)* |

### Tooling

| ID | Decision |
|---|---|
| DEC-07 | Tooling: uv (environments, lockfile, build), ruff (lint + format), mypy (types), pytest (tests). |
| DEC-08 | Python ≥ 3.11 (3.10 reached end-of-life in October 2026). CI matrix 3.11–3.14 × Linux / Windows / macOS. |
| DEC-17 | CLI parsing: `argparse` (standard library, no dependency). |
| DEC-18 | Build backend: `uv_build`; version bumped with `uv version --bump`. |
| DEC-19 | User config folder resolved with `platformdirs`. |
| DEC-24 | Config format: TOML, read with the standard-library `tomllib`. PyYAML is dropped; legacy `config/config.yml` gets a migration message. |
| DEC-26 | SMB library: switch from pysmb to `smbprotocol` (`smbclient` high-level API) during the stage 04 transport rewrite. |
| DEC-27 | No task runner: plain `uv run …` commands, documented in AGENTS.md / CONTRIBUTING and called by CI. |
| DEC-28 | No git hooks (no pre-commit framework); every check runs in CI. |
| DEC-29 | No dependency-update bot; a documented manual update routine instead (`docs/maintenance.md`). |
| DEC-36 | No extra test tools: pytest + pytest-cov + Samba container only (no hypothesis, snapshot libraries, or mutation testing). |
| DEC-40 | The Samba test server is built from our own minimal Dockerfile (pinned Debian-slim + `samba`, Recalbox-like `smb.conf`). |
| DEC-42 | Docs link check: a small pytest test that resolves relative links and anchors between repository Markdown files. |
| DEC-45 | Dependency cooldown: `[tool.uv] exclude-newer = "14 days"`, so uv only resolves releases uploaded at least 14 days ago, for runtime and dev dependencies. Urgent fixes use a per-package `exclude-newer-package` override with a recorded reason. *(2026-11-02, step 02.2)* |
| DEC-49 | **Supersedes the operating-system part of DEC-08.** CI runs on Linux only (`ubuntu-latest` × Python 3.11–3.14); Windows and macOS are removed from the test matrix, and later CI jobs (such as the stage 10 wheel smoke install) are Linux-only too. DEC-08's Python versions stand. *(2026-11-03, before merging stage 02)* |
| DEC-50 | When a report entry lists two locations (`<path> or <path>`), BECK uses the **first** one. *(2026-11-04, step 03.4)* |
| DEC-53 | **Supersedes DEC-26.** BECK keeps `pysmb` behind the `Transport` interface, instead of switching to `smbprotocol`. No SMB encryption. *(2026-11-04, step 04.1)* |
| DEC-54 | When a report lists a file as `INCORRECT` (on the device with a wrong hash), BECK **keeps the device's file and reports it**, and never uploads to that target, even with a valid local file. The general overwrite policy stays with step 06.5. *(2026-11-05, step 05.3a)* |
| DEC-55 | **Supersedes the Docker part of DEC-40.** The project uses **Podman only**, locally and in CI, and the test server is built from a `Containerfile`. *(2026-11-05, step 05.4)* |
| DEC-56 | `--clean-unmatched` stays as DEC-02 planned it, with a prominent warning that files stop matching after a rescan. *(2026-11-05, step 06.1)* |
| DEC-57 | A `beck export DIR` command (11.12), not a flag, copies every `.rom` or `.bin` file under the target's BIOS root to this machine, and skips any file that already exists locally. *(2026-11-05, step 11.12)* |
| DEC-58 | **Supersedes the definition in DEC-57.** `beck export` copies **every file** under the target's BIOS root, not only `.rom` and `.bin` files. *(2026-11-05, step 11.12)* |
| DEC-59 | CLI rules: `--clean-unmatched` never deletes a file valid for an `INCORRECT` target; a required `INCORRECT` file counts for `--fail-if-missing`; a transport error (3) beats `--fail-if-missing` (5); an unreadable local file doesn't change the exit code. *(2026-11-05, step 06.1)* |
| DEC-60 | **Supersedes DEC-58.** `beck export` copies only `.rom` and `.bin` files, in any case, under the target's BIOS root, as DEC-57 said. *(2026-11-05, step 11.12)* |
| DEC-61 | A file already on the device is **kept and reported**, and `--overwrite` replaces it, including files listed as `INCORRECT` (the flag DEC-54 left open). *(2026-11-05, step 06.5)* |
| DEC-62 | What BECK does, and its exit code, **don't depend on whether its output can be written**. The run carries on when stdout fails: a closed pipe is silent, and any other failure prints one line on stderr. *(2026-11-05, step 06.7b)* |
| DEC-63 | `types-jsonschema` is a dev-only dependency, so that mypy can check the tests that use `jsonschema`, which ships no type hints. *(2026-11-06, step 06.8)* |
| DEC-67 | BECK's first public version is `0.5.0`, rehearsed as `0.5.0rc1`. *(2026-11-06, step 10.9)* |
| DEC-68 | The README uses absolute GitHub links, which work on GitHub and on PyPI's project page. *(2026-11-06, step 10.9)* |
| DEC-73 | From `1.0.0`, the package says `Development Status :: 5 - Production/Stable`, and the README says BECK is stable. *(2026-11-11, step 10.11)* |
| DEC-65 | The release workflow passes built files between jobs with `actions/download-artifact`, pinned by SHA, so what's published is exactly what was built and checked. *(2026-11-06, step 10.6)* |
| DEC-66 | `actionlint` is run by hand with `uvx` when a workflow changes, and isn't in CI. *(2026-11-06, step 10.6)* |
| DEC-64 | An upload whose size, or with `--verify` whose MD5, doesn't match has the status `failed`, not `uploaded` with an `error`. *(2026-11-06, step 07.7)* |
| DEC-70 | **From 1.0, `beck` needs a command.** With none, it's a usage error with exit code 2, and nothing runs; with `--json`, it prints the rejected-command document, with `command: null`. Until then it ran `check` and printed a hint. *(2026-11-11, step 10.11)* |
| DEC-74 | **A file that isn't a zip archive never fills a `.zip` target** (a fix, in `1.0.1`): the target stays missing, and `beck --json check` lists the file in a new `not_a_zip` list, with `path` and `target`. Recalbox hashes a `.zip` target by the files inside it, so 1.0.0 could upload a single file, such as `neocd.bin`, as `neocdz.zip`, which Recalbox can't open. *(2026-11-11, fix after the 11.2 research on the VM)* |
| DEC-78 | **Zip-aware matching (step 11.4).** A zip archive fills a `.zip` target when its contents MD5 is listed: the MD5 of its members' bytes in the order of their names, sorted byte by byte, as Recalbox computes it. A file inside a zip fills any other target by its own MD5, through a temporary copy. Fixed limits of 1,000 members and 512 MiB unpacked per archive, not configurable. `--json` gets a `member` field wherever a local file can be a member, and `beck scan` a `contents_md5`. *(2026-11-11, step 11.4)* |
| DEC-80 | **Results by system (step 11.3).** `check` and `report` count each system's targets, as the report or web API names the systems: satisfied (in `check` only), still missing by whether they're required, and incorrect. People see a "By system:" block, before `check`'s final line, hidden by `-q`, and at the end of `report`, which still lists its files by folder. `--json` gets a `systems` list. *(2026-11-12, step 11.3)* |

### CI/CD, security, and release

| ID | Decision |
|---|---|
| DEC-11 | Releases: PyPI via trusted publishing, plus GitHub Releases. |
| DEC-25 | GitHub with thin CI YAML: every check is a local `uv run …` command that CI just calls, so changing CI host means rewriting only the YAML. |
| DEC-32 | SAST: ruff `S` rules (flake8-bandit) in the normal lint step. |
| DEC-33 | Runtime ("DAST"-equivalent) testing: integration tests against a real Samba server in a container. Classic web DAST doesn't apply to a CLI. |
| DEC-34 | SCA: Trivy filesystem scan (vulnerabilities + licenses) on every PR and weekly; pinned by commit SHA / verified checksum. |
| DEC-35 | Secret scanning: gitleaks in CI (PR range + full history on schedule). |
| DEC-37 | Release supply chain: PyPI attestations (from trusted publishing) + an SBOM generated by Trivy, attached to each GitHub Release. |
| DEC-38 | Conventional Commits are checked in CI with commitizen (`uvx --from commitizen cz check …`). |
| DEC-41 | Release pre-flight: `uvx twine check dist/*` + TestPyPI rehearsal (release-candidate tags go to TestPyPI). |
| DEC-48 | Trivy is **kept** after reviewing its March 2026 supply-chain compromise (GHSA-69fq-xp46-6x23): install only a release binary that is at least 14 days old, from an immutable GitHub release, verified against a pinned SHA-256; never use `aquasecurity/trivy-action` or `setup-trivy`. Accepted findings go in `.trivyignore` with a link and an expiry date. *(2026-11-02, step 02.13)* |

### Process and documentation

| ID | Decision |
|---|---|
| DEC-14 | One branch + PR per stage, one commit per step, Conventional Commits, CI green before merge. |
| DEC-16 | Progress is tracked only through the checkboxes in `roadmap/*.md`. |
| DEC-20 | `CHANGELOG.md` generated by git-cliff from Conventional Commits (Keep a Changelog layout). |
| DEC-30 | Documentation is Markdown in the repository; no docs website. |
| DEC-31 | Code of conduct: a short custom section inside `CONTRIBUTING.md`. |
| DEC-39 | Stage PRs are merged with a merge commit, so step commits stay on `main`. |
| DEC-51 | Step 03.13 and stage 03's acceptance are signed off on a Recalbox 10.1.1 **VM**, not a real device. Later real-device checks (04.1, the stage 10 release check) still apply. *(2026-11-04, step 03.13)* |
| DEC-52 | Step 04.1 runs on the Recalbox 10.1.1 **VM**, not a real device. The real-device run moves to the release check in step 10.11. *(2026-11-04, step 04.1)* |
| DEC-71 | Step 10.11 is three commits, not one (an exception to DEC-14's one commit per step): the removals and the 1.0 criteria as `feat!:`, so the changelog names each removal, then `chore(release): 1.0.0rc1`, then `chore(release): 1.0.0` after the owner's run on a real device. *(2026-11-11, step 10.11)* |
| DEC-72 | **Supersedes DEC-52's move of the real-device run to step 10.11.** 1.0's end-to-end run is on the Recalbox 10.1.1 **VM**, not real hardware. *(2026-11-11, step 10.11)* |

## Verified facts behind some decisions (checked 2026-11-02)

- Claude Code (≥ 2.1.277) reads `AGENTS.md` natively, **but only when there is no `CLAUDE.md`,
  `.claude/CLAUDE.md` or `CLAUDE.local.md`** in the working directory or above. Adding one of those makes it
  ignore `AGENTS.md` unless the user sets *Project instructions* to `claude-md-and-agents-md`. This is why
  DEC-21 forbids those files.
- Claude Code does not read anything under `.agents/` on its own and only auto-discovers skills in
  `.claude/skills/`. The AGENTS.md skills index (DEC-22) is what makes `.agents/skills/` reachable for it and
  for any other agent.
- Gemini CLI has a `context.fileName` setting that each user can point at `AGENTS.md`. Whether it reads
  `AGENTS.md` by default was **not** tested: step 01.3 covered only the owner's agents (DEC-44).
- Step 01.3 (2026-11-02) confirmed by test that Claude Code 2.1.316 and opencode 1.18.33 both load `AGENTS.md`
  natively from this repository ([docs/agents.md](../docs/agents.md)).
- The availability of the PyPI name `beck-bios` could not be checked from the planning session. Step 10.1 checks it.

## Glossary

- **D1…D16**: defects found in the baseline review, listed in [00-assessment.md](00-assessment.md).
- **DEC-NN**: a decision from the log above.
- **NN.M**: step M of stage NN (e.g. `03.5`).
- **Owner**: the project maintainer (the human who runs git commands, merges PRs and makes decisions).
