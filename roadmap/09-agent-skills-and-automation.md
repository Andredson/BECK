# Stage 09 — Agent Skills & automation

**Status:** Not started · **Depends on:** 08 · **Branch:** `stage/09-agent-skills` · **Effort:** M

## Goal
Package BECK's recurring workflows as **Agent Skills**, in the open SKILL.md format, so that any agent can
follow them reliably. Store them in one vendor-neutral place (`.agents/skills/`), indexed from AGENTS.md
(DEC-22). Document how agents use BECK itself through its JSON contract.

## Why
- AI-agent readiness is the target of DEC-05. AGENTS.md (stage 01) holds the rules and the JSON output (stage 06)
  is the interface; skills add **repeatable procedures** for multi-step tasks.
- Skills don't depend on any one vendor: the SKILL.md format is an open standard (agentskills.io). Only the
  *auto-discovery folder* differs per tool. The AGENTS.md index covers every agent, including tools that
  don't scan `.agents/` (Claude Code, for one, only auto-discovers `.claude/skills/`).

## Decisions applied
DEC-05, DEC-21, DEC-22, DEC-23, DEC-43.

## Skill format used in this repository

```markdown
---
name: add-report-fixture
description: Add an anonymized Recalbox missing-BIOS report as a test fixture with its expected parser output. Use when someone provides a new report or a new Recalbox version needs support.
license: GPL-3.0-only
compatibility: Needs git, uv and Python 3.11+. No network access required.
---

# Add a report fixture

## When to use
## Inputs you need from the human
## Steps
## Verify
## Never do
```

- Only fields defined by the spec, and only single-line values (keeps validation trivial, 09.9).
- `name`: lowercase letters, digits and hyphens; must equal the folder name. Check the current spec limits in 09.1.
- `description` says **what it does and when to use it**; agents decide from this line alone.
- The body is plain Markdown. Supporting files go in `scripts/` or `references/` next to `SKILL.md`, are
  referenced by relative path, and use the standard library only.

## Steps

### 09.1 — Confirm the current Agent Skills spec
- [ ] Done
- **What:** Read the current specification at agentskills.io and record in `docs/agents.md` (a "Skills" section):
  the allowed frontmatter fields, the length limits for `name` and `description`, the folder conventions, and
  which tools in the 01.3 support matrix auto-discover which folder. If the spec changed in a way that affects
  DEC-22 (e.g. a standard repository folder was defined), **stop and ask the owner** before continuing.
- **Files:** `docs/agents.md`
- **Done when:** The section lists the spec version or date it was checked against.
- **Verify:** `uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `docs(agents): record the Agent Skills specification in use`

### 09.2 — Skills folder and AGENTS.md index
- [ ] Done
- **What:** Create `.agents/skills/README.md` (the format above, how to add a skill) and an **index table** in
  AGENTS.md with columns: skill, path, use it when. Add the rule: "When a task matches a skill, read its whole
  `SKILL.md` before acting, and follow it over your general habits." No copies, symlinks or vendor folders (DEC-22).
- **Files:** `.agents/skills/README.md`, `AGENTS.md`
- **Done when:** The index exists, even before any skill is listed in it.
- **Verify:** `test -f .agents/skills/README.md && grep -q '.agents/skills' AGENTS.md`
- **Commit message:** `docs(agents): add skills folder and index`

### 09.3 — Skill: `execute-roadmap-step`
- [ ] Done
- **What:** Encodes the protocol from [roadmap README](README.md#how-to-execute-a-step-humans-and-agents):
  1. find the next step; check its blockers;
  2. confirm there is no missing decision; if there is, ask the owner with alternatives;
  3. implement only that step;
  4. run its Verify plus the standard checks;
  5. tick the box;
  6. commit with the step's message and no attribution trailer (DEC-46), then print `git push` as one copy-paste
     line;
  7. on the closing step, print the push and PR commands (human-only, DEC-43).

  Include a short "common mistakes" list: doing two steps at once, adding an unlisted tool, pushing or creating
  branches/PRs/tags, adding an attribution trailer to commits, touching a real Recalbox.
- **Files:** `.agents/skills/execute-roadmap-step/SKILL.md`, `AGENTS.md` (index row)
- **Done when:** An agent given only "do the next roadmap step" follows it correctly in a dry exercise.
- **Verify:** `uv run pytest tests/test_skills.py -q` (after 09.9; until then, a manual review)
- **Commit message:** `feat(skills): add execute-roadmap-step skill`

### 09.4 — Skill: `quality-gates`
- [ ] Done
- **What:** Runs the full local check suite in CI order (ruff check, ruff format check, mypy, unit tests with
  coverage, hygiene script, link test; integration tests if the Samba container is available) and explains how
  to read and fix each kind of failure. Never "fix" a failure by disabling a rule, lowering coverage or adding an
  ignore without the owner's approval.
- **Files:** `.agents/skills/quality-gates/SKILL.md`, `AGENTS.md`
- **Done when:** The commands match the CI workflow exactly.
- **Verify:** Run every command listed in the skill; all pass.
- **Commit message:** `feat(skills): add quality-gates skill`

### 09.5 — Skill: `add-report-fixture`
- [ ] Done
- **What:** Turn a report provided by a human into a fixture:
  1. ask for the Recalbox version and the menu path used;
  2. anonymize (with a list of what to look for);
  3. place it at `tests/fixtures/reports/recalbox-<version>/`;
  4. write `.expected.json` by reading the report by hand, **not** by running the parser (that would just copy
     current bugs);
  5. update the provenance table;
  6. run the parser tests;
  7. if the format differs from known versions, stop and describe the difference to the owner.
- **Files:** `.agents/skills/add-report-fixture/SKILL.md`, `AGENTS.md`
- **Done when:** The steps reproduce the existing fixtures' structure.
- **Verify:** Manual review against `tests/fixtures/README.md`.
- **Commit message:** `feat(skills): add add-report-fixture skill`

### 09.6 — Skill: `add-frontend-adapter`
- [ ] Done
- **What:** The procedure stage 11 will use for Batocera, RetroBat and others:
  1. collect real reference data (report or BIOS list) and fixtures;
  2. write an ADR;
  3. implement `FrontendAdapter` in `src/beck/frontends/<name>.py` and register it;
  4. add parametrized fixture tests;
  5. document it in the README and troubleshooting guide;
  6. add the agent support note.

  Point to `recalbox.py` as the reference implementation.
- **Files:** `.agents/skills/add-frontend-adapter/SKILL.md`, `AGENTS.md`
- **Done when:** The steps cover everything `recalbox.py` needed.
- **Verify:** Manual review against `docs/ARCHITECTURE.md`.
- **Commit message:** `feat(skills): add add-frontend-adapter skill`

### 09.7 — Skill: `diagnose-missing-bios` (user-facing)
- [ ] Done
- **What:** For agents **helping an end user** (not developing BECK):
  1. run `beck --json check --dry-run …` (never without `--dry-run` first);
  2. explain the plan in plain language;
  3. for each entry still missing, explain the likely reasons using the `still_missing` and `unmatched`
     data and `docs/troubleshooting.md`;
  4. only run without `--dry-run` after the user approves;
  5. never use `--move`, `--clean-unmatched` or `--yes` unless the user asked for that exact flag;
  6. never ask the user to paste a password into the chat; point them to `BECK_SMB_PASSWORD` or the prompt.

  Also add a `references/exit-codes.md` that copies the table from `docs/cli.md`, with a note to keep both in sync.
- **Files:** `.agents/skills/diagnose-missing-bios/SKILL.md`, `.agents/skills/diagnose-missing-bios/references/exit-codes.md`, `AGENTS.md`
- **Done when:** A test (09.9) checks that the exit-code table in the reference matches `docs/cli.md`.
- **Verify:** `uv run pytest tests/test_skills.py -q`
- **Commit message:** `feat(skills): add diagnose-missing-bios skill for end-user support`

### 09.8 — Using BECK with agents: documentation
- [ ] Done
- **What:** Extend `docs/agents.md` with: the support matrix (from 01.3), how agents find instructions
  (AGENTS.md only) and skills (the index), the JSON contract and exit codes (links), safety rules for agents, and
  how to ask an agent to run BECK for you. Keep it vendor-neutral: describe behavior, not product menus.
- **Files:** `docs/agents.md`, `README.md` (link from the Automation section)
- **Done when:** A user of any listed agent can follow the doc.
- **Verify:** `uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `docs(agents): document using BECK with AI agents`

### 09.9 — Skill validation test
- [ ] Done
- **What:** `tests/test_skills.py`, standard library only:
  - every folder in `.agents/skills/` (except `README.md`) has a `SKILL.md`;
  - the frontmatter, parsed as single-line `key: value` pairs between `---` lines, has a valid `name` equal to
    the folder name, a non-empty `description` within the spec limit, and no keys outside the spec;
  - every relative link inside a skill resolves;
  - every skill appears in the AGENTS.md index, and every index row points to an existing skill;
  - the exit-code reference matches `docs/cli.md` (09.7).
- **Files:** `tests/test_skills.py`
- **Done when:** Breaking any rule above makes the test fail.
- **Verify:** `uv run pytest tests/test_skills.py -q`
- **Commit message:** `test(skills): validate skill frontmatter, links and index`

### 09.10 — Cross-vendor evaluation
- [ ] Done
- **What:** For each skill, give the same short task to agents from **at least two different vendors** (e.g.
  "add this report as a fixture", "why is scph5501.bin still missing?"). Record in `docs/agents.md` whether each
  agent found the skill through the AGENTS.md index, followed it, and respected the safety rules. Fix wording in
  the skill where agents went wrong; don't add vendor-specific copies.
- **Files:** `docs/agents.md`, `.agents/skills/**`
- **Done when:** Every skill has at least two recorded evaluations.
- **Verify:** Manual review of the evaluation table.
- **Commit message:** `docs(agents): record cross-vendor skill evaluations`

### 09.11 — Close the stage
- [ ] Done
- **What:** Re-score [00-assessment](00-assessment.md#re-scoring-history) (AI-agent readiness should be about 8;
  the `cut-release` skill comes in 10.8). Update the [README](README.md#stages) status. Print the push and PR
  commands for the human:

  ```sh
  git push -u origin stage/09-agent-skills
  gh pr create --base main --title "Stage 09: Agent Skills and automation" --body "Closes roadmap stage 09."
  ```

- **Files:** `roadmap/00-assessment.md`, `roadmap/README.md`, this file
- **Done when:** The PR is merged with a merge commit.
- **Verify:** The full check suite in AGENTS.md passes, including `tests/test_skills.py`.
- **Commit message:** `docs(roadmap): close stage 09 and re-score assessment`

## Stage acceptance criteria
- Five skills exist in `.agents/skills/`, are valid per the spec, are indexed in AGENTS.md, and have been
  evaluated with two vendors.
- `docs/agents.md` explains agent usage without depending on one vendor.

## Out of scope
- An MCP server (DEC-05). Vendor-specific skill folders or symlinks (DEC-22).

## Agent notes
- A skill is a procedure, not documentation. If a skill grows beyond about 150 lines, move the reference
  material into `references/` and keep `SKILL.md` focused on the steps.
