# ADR-0002 — AI-agent support

- **Status:** Accepted
- **Date:** 2026-11-02
- **Decisions covered:** DEC-05, DEC-06, DEC-21, DEC-22, DEC-23, DEC-43, DEC-44, DEC-46

## Context
The owner asked for AI-agent support that is vendor-agnostic where possible. Two open standards cover most of
it: `AGENTS.md` for repository instructions, and the Agent Skills format (agentskills.io) for reusable
procedures. The Model Context Protocol (MCP) was also considered. The facts that shaped these decisions were
checked against vendor documentation and by testing on 2026-11-02:

- Claude Code (≥ 2.1.277) reads `AGENTS.md` natively, but **only while no `CLAUDE.md`, `.claude/CLAUDE.md` or
  `CLAUDE.local.md`** exists at or above the working directory.
- Claude Code doesn't read `.agents/` on its own, and auto-discovers skills only in `.claude/skills/`.
- Tested in step 01.3: Claude Code 2.1.316 and opencode 1.18.33 both load `AGENTS.md` natively from this repository
  ([support matrix](../agents.md)).

## DEC-05 — What "AI support" means
- **Decision:** AGENTS.md, machine-readable output (`--json` plus stable exit codes), and Agent Skills.
  **No MCP server.**
- **Alternatives considered:** *An optional `beck mcp` command* exposing scan/check/upload as MCP tools, dry-run by
  default: offered, not selected by the owner.
- **Consequences:** Agents drive BECK through its command line and JSON output (stage 06), which works with any
  agent that can run a shell command. If an MCP server is wanted later, it needs a new DEC; it could wrap the same
  JSON contract.

## DEC-06 — Create AGENTS.md together with the roadmap
- **Decision:** AGENTS.md was written in the same session as the roadmap, before any code change.
- **Alternatives considered:** *Only plan it as a roadmap stage*: not chosen; agents executing stages 01–03 would
  have worked without the rules.
- **Consequences:** Every stage's closing step updates AGENTS.md so it stays accurate.

## DEC-21 — AGENTS.md only, no vendor shims
- **Decision:** `AGENTS.md` is the only agent-instructions file. No `CLAUDE.md`, `GEMINI.md`, `.gemini/`,
  `.cursor/rules`, `.github/copilot-instructions.md` or similar.
- **Alternatives considered:**
  - *Two thin pointer files*: `CLAUDE.md` containing `@AGENTS.md`, and `.gemini/settings.json` pointing Gemini CLI
    at AGENTS.md. This was recommended during planning, based on the belief that Claude Code needed `CLAUDE.md`.
    Checking the documentation afterwards showed that belief was out of date, and that adding a `CLAUDE.md` would
    actually stop Claude Code from reading `AGENTS.md` natively.
  - *Symlinks* (`CLAUDE.md`, `GEMINI.md` → `AGENTS.md`): not chosen; they break on Windows checkouts without
    developer mode or `core.symlinks`.
  - *Pointer files plus more shims* (Copilot, Aider, …): not chosen; more files to keep in sync.
- **Consequences:** AGENTS.md tells contributors not to create those files, and explains the per-user setting
  for anyone who needs a private `CLAUDE.local.md`. Agents that need user-side setup (e.g. Gemini CLI's
  `context.fileName`) are configured by each user, never in the repository.

## DEC-22 — Skills in `.agents/skills/`, indexed from AGENTS.md
- **Decision:** Skills live in `.agents/skills/<name>/SKILL.md`, use only the spec's frontmatter fields, and are
  listed in an index table in AGENTS.md. Agents read a skill's `SKILL.md` when a task matches.
- **Alternatives considered:**
  - *`.claude/skills/`*: native auto-discovery and slash commands in Claude Code, but the folder name belongs to one
    vendor.
  - *Vendor folders* (`.claude/skills`, `.github/skills`, …): native in each tool, but needs copies or symlinks.
  - *`docs/skills/` as plain documentation*: not chosen; no tool treats them as skills.
- **Consequences:** No tool auto-discovers `.agents/skills/` natively. Discovery works through AGENTS.md, which
  every agent reads. Stage 09 adds the skills and a validation test; step 09.10 checks them with two vendors' agents.

## DEC-23 — Versioned JSON output and stable exit codes
- **Decision:** `--json` output carries `schema_version`, is described by JSON Schema files, and is guarded by
  contract tests. Exit codes 0–5 are documented. `jsonschema` is a dev-only dependency.
- **Alternatives considered:**
  - *JSON documented only by example*: not chosen; consumers could break silently when fields change.
  - *Exit codes only*: not chosen; agents would have to parse human-readable text.
- **Consequences:** Within schema version 1, fields may only be added (step 06.7). Changing an existing field means
  `schema_version` 2 and an owner decision.

## DEC-43 — Agents never perform git writes
- **Status:** The *commit* part is superseded by [DEC-46](#dec-46--agents-may-commit-locally); the rest stands.
- **Decision:** Agents never commit, push, create branches, push tags, run `git rm --cached`, or open PRs or
  releases. They print the exact commands, and the human runs them.
- **Alternatives considered:** None were offered. This was the owner's instruction when approving the plan.
- **Consequences:** Every step's *Commit message* is something to hand over, not to execute. Human-only steps
  (tags, environment approvals, GitHub settings) stay human-only. The `execute-roadmap-step` and `cut-release`
  skills (09.3, 10.8) encode this.

## DEC-46 — Agents may commit locally
- **Date:** 2026-11-02 (before step 02.8). Supersedes the commit part of DEC-43.
- **Context:** Through stage 01 and steps 02.1–02.7 the owner ran every commit from a handed-over command line.
  The owner then allowed the agent to run the commits, with one condition: no `Co-Authored-By` trailer.
- **Decision:** Agents may stage (`git add`, `git rm --cached`) and `git commit` with the step's Conventional
  Commits message, never adding a `Co-Authored-By` or other attribution line. Everything that leaves the machine
  or changes branch structure stays human-only: push, branch creation or switching, tags, PRs, merges, releases.
  Agents also never rewrite history. They hand human-only commands over as one copy-paste line.
- **Alternatives considered:** None were offered; this was the owner's instruction.
- **Consequences:** Each step ends with a local commit, and the owner reviews what they push. Branches still have
  to exist before a stage's first step, because the agent can't create them.

## DEC-44 — The support matrix covers the owner's agents
- **Decision:** `docs/agents.md` lists only agents the owner actually uses; on 2026-11-02 that meant Claude Code
  and opencode. Contributors add rows when they test another agent, following the documented procedure.
- **Alternatives considered:**
  - *Fill rows for Codex, Copilot, Cursor and Gemini CLI from vendor documentation*, marked "docs only, not
    tested" (recommended at the time): not chosen.
  - *The owner tests each one*: not chosen; those tools aren't installed on the owner's machine, and the step
    would have stayed blocked.
- **Consequences:** Support for other agents is unverified. The matrix says so, and the AGENTS.md design doesn't
  depend on it, because it relies only on the open standard.
