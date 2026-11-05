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
| 06 | [CLI, UX & machine-readable output](06-cli-ux-and-machine-output.md) | 05 | `stage/06-cli` | M | Not started |
| 07 | [Configuration & security](07-configuration-and-security.md) | 06 | `stage/07-config-security` | M | Not started |
| 08 | [Documentation](08-documentation.md) | 07 | `stage/08-docs` | M | Not started |
| 09 | [Agent Skills & automation](09-agent-skills-and-automation.md) | 08 | `stage/09-agent-skills` | M | Not started |
| 10 | [Packaging & release](10-packaging-and-release.md) | 09 | `stage/10-release` | M | Not started |
| 11 | [Feature expansion](11-feature-expansion.md) | 10 | one branch per feature | L | Not started |
| 12 | [Community & governance](12-community-and-governance.md) | 02 (can run in parallel with 03–11) | `stage/12-community` | S | Not started |

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
