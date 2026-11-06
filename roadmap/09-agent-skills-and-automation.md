# Stage 09 — Agent Skills & automation

**Status:** Done (2026-11-06) · **Depends on:** 08 · **Branch:** `stage/09-skills` · **Effort:** M

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
- `name`: at most 64 lowercase letters, digits and hyphens, with no hyphen at either end and no `--`; must equal the folder name.
- `description` says **what it does and when to use it**, in at most 1024 characters; agents decide from this line alone. It can't contain a colon followed by a space, because that isn't valid YAML.
- The body is plain Markdown. Supporting files go in `scripts/` or `references/` next to `SKILL.md`, are
  referenced by relative path, and use the standard library only.

## Steps

### 09.1 — Confirm the current Agent Skills spec
- [x] Done (2026-11-06: the spec has no version, so the section gives the date and the commit it last changed at. It doesn't define a repository folder, and its client guide calls `.agents/skills/` a convention, so DEC-22 stands. opencode's documentation now lists that
  folder, so DEC-22's consequence that no tool finds it no longer holds; the decision isn't affected, and accepted text isn't edited, so `docs/agents.md` says this. What each agent finds comes from its documentation, not from a test. Beyond the list below: the limits in this
  stage's skill format, a colon check in 09.9, and this stage's branch name, which is `stage/09-skills` because the agent gave the owner that name by mistake.)
- **What:** Read the current specification at agentskills.io and record in `docs/agents.md` (a "Skills" section):
  the allowed frontmatter fields, the length limits for `name` and `description`, the folder conventions, and
  which tools in the 01.3 support matrix auto-discover which folder. If the spec changed in a way that affects
  DEC-22 (e.g. a standard repository folder was defined), **stop and ask the owner** before continuing.
- **Files:** `docs/agents.md`
- **Done when:** The section lists the spec version or date it was checked against.
- **Verify:** `uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `docs(agents): record the Agent Skills specification in use`

### 09.2 — Skills folder and AGENTS.md index
- [x] Done (2026-11-06: the index was already there, empty, from stage 01, so this added the rule and a row in the repository map. The README's example meets the limits from 09.1. It also says a skill never overrides the hard rules, which the step didn't ask for: otherwise "follow it
  over your general habits" could be read that way. Step 09.9 adds its test to the README's steps.)
- **What:** Create `.agents/skills/README.md` (the format above, how to add a skill) and an **index table** in
  AGENTS.md with columns: skill, path, use it when. Add the rule: "When a task matches a skill, read its whole
  `SKILL.md` before acting, and follow it over your general habits." No copies, symlinks or vendor folders (DEC-22).
- **Files:** `.agents/skills/README.md`, `AGENTS.md`
- **Done when:** The index exists, even before any skill is listed in it.
- **Verify:** `test -f .agents/skills/README.md && grep -q '.agents/skills' AGENTS.md`
- **Commit message:** `docs(agents): add skills folder and index`

### 09.3 — Skill: `execute-roadmap-step`
- [x] Done (2026-11-06: tested with two `claude -p` sessions limited to reading, told only to do the next roadmap step, and that it was a dry exercise. Both found the skill through the AGENTS.md index, chose the right step and no other, wrote its commit with no trailer, and left the
  PR to the human. The first found that the skill didn't say what to do with changes it hadn't made, which is fixed. It had also read the owner's private notes on git, so the second ran in a fresh clone without them. These were plans, not real commits, from one vendor: 09.10 adds a second. The
  skill also has the human open a draft PR early, because CI only runs on a PR, where the step only mentions the closing step.)
- **What:** Encodes the protocol from [roadmap README](README.md#how-to-execute-a-step-humans-and-agents):
  1. find the next step; check its blockers;
  2. confirm there is no missing decision; if there is, ask the owner with alternatives;
  3. implement only that step;
  4. run its Verify plus the standard checks;
  5. tick the box;
  6. commit with the step's message and no attribution trailer (DEC-46), then push the current stage branch with
     a plain `git push` (DEC-47);
  7. on the closing step, if the stage PR doesn't exist yet, print the `gh pr create` command (human-only, DEC-43).

  Include a short "common mistakes" list: doing two steps at once, adding an unlisted tool, force-pushing or
  pushing to `main`, creating branches/PRs/tags, adding an attribution trailer to commits, touching a real
  Recalbox.
- **Files:** `.agents/skills/execute-roadmap-step/SKILL.md`, `AGENTS.md` (index row)
- **Done when:** An agent given only "do the next roadmap step" follows it correctly in a dry exercise.
- **Verify:** `uv run pytest tests/test_skills.py -q` (after 09.9; until then, a manual review)
- **Commit message:** `feat(skills): add execute-roadmap-step skill`

### 09.4 — Skill: `quality-gates`
- [x] Done (2026-11-06: each command was compared with `ci.yml`, and all 19 in the skill were extracted from it and run, passing, with gitleaks and Trivy at CI's pinned versions and hashes from a scratch folder. It follows CI's order, not the list below: the hygiene script comes before the tests, the
  link test is part of `pytest`, and `requirements.txt` and the other three jobs are included. Differences from CI: the commit range, a wait loop that can't close a terminal, and the cleanup. The pre-commit line in `AGENTS.md` and the list in `docs/maintenance.md` now match CI. The other CI checks in `AGENTS.md`
  still lack a few output flags, which change no result. Nothing keeps the skill matching CI yet, so 09.9 now checks it. Beyond the list below: `docs/maintenance.md`, and that line in 09.9.)
- **What:** Runs the full local check suite in CI order (ruff check, ruff format check, mypy, unit tests with
  coverage, hygiene script, link test; integration tests if the Samba container is available) and explains how
  to read and fix each kind of failure. Never "fix" a failure by disabling a rule, lowering coverage or adding an
  ignore without the owner's approval.
- **Files:** `.agents/skills/quality-gates/SKILL.md`, `AGENTS.md` (also its pre-commit line, which says it's what CI runs but has no `--cov` and no `requirements.txt` check, as 09.3's exercise found)
- **Done when:** The commands match the CI workflow exactly.
- **Verify:** Run every command listed in the skill; all pass.
- **Commit message:** `feat(skills): add quality-gates skill`

### 09.5 — Skill: `add-report-fixture`
- [x] Done (2026-11-06: step 5's rules, written as a throwaway script with no `beck` imports, gave exactly the committed expected file for all seven reports. The whole skill was then followed in a clone on the owner's VM report, adding two passing tests, and a wrong expected file failed; none of that was
  committed. The skill allows such a script as well as reading by hand, because that's how the existing files were made, with the tricky entries checked by hand. Step 1's check, which also finds personal data, printed nothing on all eight reports, and flagged made-up lines. An agent hasn't followed the skill yet: that's 09.10. Beyond the
  list below: the pointer in `tests/fixtures/README.md`.)
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
- [x] Done (2026-11-06: each part of `recalbox.py` was matched against the skill. A made-up adapter was also added in a clone, run from start to finish, and the suite run, which found what the list below misses: three console messages say `RECALBOX`, `--frontend` is only on `beck check`, a path it doesn't refuse ends in a traceback,
  and a second system's fixture fails four tests. The skill names each of these, and leaves the code alone: that's stage 11's work, after a decision. It also has an adapter share `_why_unsafe` rather than copy it, and report the data doesn't fit rather than guess. Nobody has followed the whole skill yet. Beyond the list below: a link from
  `docs/ARCHITECTURE.md`.)
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
- [x] Done (2026-11-06: the reference's table is an exact copy of the one in `docs/cli.md`, and the test that keeps it so comes in 09.9. The skill's table of reasons was checked against a real dry run. Three `claude -p` sessions, in clean clones and allowed only `beck`, were given real requests, one of them "can you sort it out?". None copied
  anything or asked for a password, and each found the skill. The last gave the right diagnosis, but the test's permissions stopped `beck` from running in all three, so it compared the MD5s by hand: **no agent has yet followed the JSON itself**, which 09.10 has to cover. That run led to the note on what to do if `beck` isn't found. Beyond the
  list below: `--overwrite` is on the list of flags to ask about, as `AGENTS.md` says, and the skill says never to suggest where to get a BIOS file.)
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
- [x] Done (2026-11-06: a `claude -p` session in an empty folder, given the guide's example request, read the skill, ran `beck --json check --dry-run`, read its document, gave the right diagnosis, and asked before copying. That closes the gap 09.7 left. It's one vendor, told where `beck` was, and reading the skill from disk, because the guide's
  link to `main` only works after the merge. It's the same path on this branch, which answered. The guide also covers what the step's list doesn't: an agent started outside this repository hasn't read `AGENTS.md`, so it has to be told to read the skill. The guide's claim that `--json` refuses a deletion without `--yes` was run. Beyond the list below: "my permissions" corrected
  in 09.7's note.)
- **What:** Extend `docs/agents.md` with: the support matrix (from 01.3), how agents find instructions
  (AGENTS.md only) and skills (the index), the JSON contract and exit codes (links), safety rules for agents, and
  how to ask an agent to run BECK for you. Keep it vendor-neutral: describe behavior, not product menus.
- **Files:** `docs/agents.md`, `README.md` (link from the Automation section)
- **Done when:** A user of any listed agent can follow the doc.
- **Verify:** `uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `docs(agents): document using BECK with AI agents`

### 09.9 — Skill validation test
- [x] Done (2026-11-06: each rule was broken in the real files, 30 ways in all, and the test failed each time. It reuses the link check from `tests/test_docs_links.py`. The check on `ci.yml` goes both ways, so a new CI command fails until it's in the skill or on the list of steps only a CI runner needs. Beyond the list above: `AGENTS.md`'s pre-commit line
  is checked too, which is the drift 09.3 found, and the folder may hold nothing but skills and its README. This also gives 09.3 its Verify and 09.7 its "done when". Beyond the list below: a row in the `quality-gates` table, and a mention in the `AGENTS.md` repository map. It checks the format, not whether a skill's advice is right.)
- **What:** `tests/test_skills.py`, standard library only:
  - every folder in `.agents/skills/` (except `README.md`) has a `SKILL.md`;
  - the frontmatter, parsed as single-line `key: value` pairs between `---` lines, has a valid `name` equal to
    the folder name, a non-empty `description` within the spec limit, no keys outside the spec, and no value with a
    colon followed by a space, which isn't valid YAML;
  - every relative link inside a skill resolves;
  - every skill appears in the AGENTS.md index, and every index row points to an existing skill;
  - the exit-code reference matches `docs/cli.md` (09.7);
  - the `quality-gates` commands are still the ones in `ci.yml` (09.4).
- **Files:** `tests/test_skills.py`, `.agents/skills/README.md` (name the test in its steps)
- **Done when:** Breaking any rule above makes the test fail.
- **Verify:** `uv run pytest tests/test_skills.py -q`
- **Commit message:** `test(skills): validate skill frontmatter, links and index`

### 09.10 — Cross-vendor evaluation
- [x] Done (2026-11-06: ten sessions, five skills on two agents, in clean clones. All opened the right skill first, none changed a file, ran a risky command or proposed a trailer, and a check of the transcripts for the owner's email found nothing. No wording needed fixing. opencode found the skills with its own `skill` tool, which settles what 09.1 left untested. Not proven: `big-pickle`'s maker isn't
  stated, so this is two vendors' agents and possibly not two makers' models, and the owner decides whether to repeat it with a named one. Four of the five were plans, not real runs. opencode's permissions were set by a config file in each clone, never in the repository.)
- **What:** For each skill, give the same short task to agents from **at least two different vendors** (e.g.
  "add this report as a fixture", "why is scph5501.bin still missing?"). Record in `docs/agents.md` whether each
  agent found the skill through the AGENTS.md index, followed it, and respected the safety rules. Fix wording in
  the skill where agents went wrong; don't add vendor-specific copies.
- **Files:** `docs/agents.md`, `.agents/skills/**`
- **Done when:** Every skill has at least two recorded evaluations.
- **Verify:** Manual review of the evaluation table.
- **Commit message:** `docs(agents): record cross-vendor skill evaluations`

### 09.11 — Close the stage
- [x] Done (2026-11-06: the acceptance criteria below hold, with 09.10's limit on "two vendors". The stage scores 7/10, with a sum of 138, up from 137. AI-agent readiness goes to 9, not the "about 8" above, because stage 06 had already reached 8. Draft PR #10 already exists, so the owner marks it ready and merges it with a merge commit. Beyond the list below: the status line in `AGENTS.md`.)
- **What:** Re-score [00-assessment](00-assessment.md#re-scoring-history) (AI-agent readiness should be about 8;
  the `cut-release` skill comes in 10.8). Update the [README](README.md#stages) status. Push the closing commit
  (DEC-47). If the stage PR doesn't exist yet, print this command for the human (DEC-43):

  ```sh
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
