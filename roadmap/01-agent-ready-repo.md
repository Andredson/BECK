# Stage 01 — Agent-ready repository

**Status:** In progress · **Depends on:** — · **Branch:** `stage/01-agent-ready-repo` · **Effort:** S

## Goal
Any AI coding agent, from any vendor, that opens this repository should immediately know what the project is,
which rules are non-negotiable, how to run things, and how to execute the next roadmap step. Humans get the same
information from the same files.

## Why
- AI-agent readiness scores **0/10** ([00-assessment](00-assessment.md#scorecard), aspect 19).
- Most remaining stages will probably be executed by agents, so the rules (non-destructive behavior, no
  real-device access, no silent new tools, no git writes) must be in place **before** stage 02 starts.

## Decisions applied
DEC-05, DEC-06, DEC-16, DEC-21, DEC-22, DEC-43.

## Steps

### 01.1 — Create AGENTS.md
- [x] Done (2026-11-02, created together with the roadmap)
- **What:** One vendor-neutral instructions file at the repository root: overview, repo map, current commands,
  roadmap protocol, hard rules, agent-tooling notes, style, testing, legal, git conventions.
- **Files:** `AGENTS.md`
- **Done when:** The file exists and describes the repository as it is today (single script, no tooling yet).
- **Verify:** `test -f AGENTS.md && ! test -e CLAUDE.md && ! test -e GEMINI.md && ! test -e .gemini`
- **Commit message:** `docs: add vendor-neutral AGENTS.md for AI coding agents`

### 01.2 — Create the roadmap folder
- [x] Done (2026-11-02)
- **What:** `roadmap/README.md` (index, protocol, decision log), `00-assessment.md`, and one file per stage (01–12).
- **Files:** `roadmap/*.md`
- **Done when:** Every stage file follows the step format in [README](README.md#step-format-used-in-every-stage-file).
- **Verify:** `ls roadmap/ | wc -l` prints `14`
- **Commit message:** `docs: add staged improvement roadmap and baseline assessment`

### 01.3 — Agent support matrix
- [x] Done (2026-11-02: Claude Code 2.1.316 and opencode 1.18.33 both pass; other agents left out per DEC-44)
- **What:** Check which agents actually load `AGENTS.md` from this repository **without any extra file in the
  repo** (DEC-21). Cover each agent the owner uses (DEC-44: only those installed and used by the owner, which on
  2026-11-02 meant Claude Code and opencode; contributors add rows for other agents when they test them):
  1. Open the repo with the agent and ask: *"Without reading any file now, list this repository's hard rules."*
  2. Record whether it answered from `AGENTS.md`, plus the tool version and the date.
  3. If an agent needs **user-side** configuration, document that configuration. Example: Gemini CLI's
     `context.fileName` setting in the user's own `~/.gemini/settings.json`, not in the repo.
  4. For Claude Code, document the caveat: a `CLAUDE.md` or `CLAUDE.local.md` anywhere at or above the working
     directory makes it skip `AGENTS.md`. Users who need a private `CLAUDE.local.md` must set *Project
     instructions* to `claude-md-and-agents-md` in `/config`.
- **Files:** `docs/agents.md` (new: support-matrix table + per-tool notes), `AGENTS.md` (link to it)
- **Done when:** The table has a row per tested agent with: reads AGENTS.md natively (yes/no/needs user
  setting), version tested, date, the exact test command, and notes. There is also a written procedure for
  testing another agent.
- **Verify:** `grep -q '^| Claude Code |' docs/agents.md && grep -q '^| opencode |' docs/agents.md && grep -q 'How to test an agent' docs/agents.md`
- **Commit message:** `docs(agents): add agent support matrix for AGENTS.md`

### 01.4 — Architecture Decision Records
- [ ] Done
- **What:** Create `docs/adr/` with:
  - `0000-template.md` (sections: Status, Date, Context, Decision, Alternatives considered, Consequences).
  - One ADR per decision **group** in the [decision log](README.md#decision-log), not one per row, to keep it
    readable: `0001-product-scope.md` (DEC-01–04, 09, 10, 12, 13, 15), `0002-ai-agent-support.md` (DEC-05, 06,
    21, 22, 23, 43, 44), `0003-tooling.md` (DEC-07, 08, 17–19, 24, 26–29, 36, 40, 42),
    `0004-ci-security-release.md` (DEC-11, 25, 32–35, 37, 38, 41), `0005-process-and-docs.md` (DEC-14, 16, 20,
    30, 31, 39).
  - Each ADR records the **alternatives that were rejected and why**, using the trade-offs discussed when the
    decision was made. That gives agents the reasoning behind each rule, not just the rule.
  - `docs/adr/README.md`: index plus how to add an ADR. A new decision gets a new DEC row **and** an ADR;
    superseded ADRs are marked, never deleted.
- **Files:** `docs/adr/*.md`, `roadmap/README.md` (link the ADR index), `AGENTS.md` (link)
- **Done when:** Every DEC-NN appears in exactly one ADR.
- **Verify:** `for n in $(grep -oE '^\| DEC-[0-9]+' roadmap/README.md | grep -oE '[0-9]+'); do grep -lq "DEC-$n" docs/adr/0*.md || echo "missing DEC-$n"; done` prints nothing (covers every DEC in the log, however many there are)
- **Commit message:** `docs(adr): record initial architecture decisions`

### 01.5 — Pull request template
- [ ] Done
- **What:** `.github/pull_request_template.md` with a checklist that works for humans and agents:
  - Stage and step IDs covered (e.g. `03.1–03.4`).
  - For each step: paste the output of its **Verify** command.
  - [ ] Boxes ticked in `roadmap/NN-*.md` and stage **Status** updated.
  - [ ] AGENTS.md still accurate (commands, repo map, rules).
  - [ ] No new tool or dependency without a DEC entry.
  - [ ] No BIOS files, real credentials or unanonymized reports added.
  - [ ] Destructive behavior still opt-in (DEC-02).
  - Note for agents: they **print** the PR command (`gh pr create …`) and the human runs it (DEC-43).
- **Files:** `.github/pull_request_template.md`
- **Done when:** Opening a PR on GitHub pre-fills the template.
- **Verify:** `test -f .github/pull_request_template.md && grep -q 'Verify' .github/pull_request_template.md`
- **Commit message:** `chore(github): add pull request template with roadmap checklist`

### 01.6 — Close the stage
- [ ] Done
- **What:** Re-read AGENTS.md against the repository; add a row to the
  [re-scoring history](00-assessment.md#re-scoring-history) (aspect 19 should move from 0 to about 4, aspect
  18 slightly); set this file's **Status** to Done and update the table in [README](README.md#stages). The
  agent then prints the push and PR commands for the human:

  ```sh
  git push -u origin stage/01-agent-ready-repo
  gh pr create --base main --title "Stage 01: agent-ready repository" --body "Closes roadmap stage 01."
  ```

- **Files:** `roadmap/00-assessment.md`, `roadmap/README.md`, `roadmap/01-agent-ready-repo.md`
- **Done when:** The PR is merged with a merge commit (DEC-39).
- **Verify:** `grep -q '| 01 |' roadmap/00-assessment.md && grep -q '^| 01 .*Done' roadmap/README.md`
- **Commit message:** `docs(roadmap): close stage 01 and re-score assessment`

## Stage acceptance criteria
- `AGENTS.md` is the single source of agent instructions; no vendor-specific instruction files exist.
- The support matrix shows which agents read it, and any user-side setup they need.
- Every decision has an ADR that explains the alternatives.
- PRs carry the roadmap checklist.

## Out of scope
- Agent Skills (stage 09), JSON output (stage 06), and any change to the Python code.

## Agent notes
- Don't create `CLAUDE.md`, `GEMINI.md`, `.cursor/rules`, `.github/copilot-instructions.md` or similar
  "to help" a specific tool. DEC-21 forbids it, and for Claude Code it would actually *stop* AGENTS.md from loading.
- ADRs describe decisions that were already made. Don't re-argue them in the ADR text; record the reasoning
  that was given.
