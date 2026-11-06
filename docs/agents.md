# AI agents and BECK

BECK keeps all agent instructions in one vendor-neutral file, [AGENTS.md](../AGENTS.md) (DEC-21). This page
records which agents have been **tested** loading it from this repository with no vendor-specific file
present, and how to test another agent.

## Support matrix

| Agent | Reads AGENTS.md natively | Version tested | Date | How it was tested | Notes |
|---|---|---|---|---|---|
| Claude Code | Yes | 2.1.316 | 2026-11-02 | `claude -p --tools "" --no-session-persistence "<test prompt>"` (all tools disabled, so the answer can only come from instructions loaded at startup) | Named `AGENTS.md` as the loaded file and listed every hard rule. Native support needs ≥ 2.1.277, and **only applies while no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` exists** in the working directory or above. Otherwise set *Project instructions* to `claude-md-and-agents-md` in `/config`. |
| opencode | Yes | 1.18.33 (model `opencode/big-pickle`) | 2026-11-02 | `opencode run --format json "<test prompt>" < /dev/null`; the JSON event stream contained no tool calls | Named `AGENTS.md` and listed every hard rule. Headless `opencode run` waits on stdin when it isn't a terminal, so close stdin (`< /dev/null`). |

Only the agents the owner uses are listed (DEC-44). Other agents (for example Codex, GitHub Copilot, Cursor or
Gemini CLI) haven't been tested. If you use one, test it with the procedure below and add a row in your PR.
Known user-side setup from vendor documentation, untested here: Gemini CLI can be pointed at `AGENTS.md`
through the `context.fileName` setting in the **user's own** settings file. Never add `.gemini/` or any other
vendor folder to this repository.

## How to test an agent

1. Make sure the working tree has no vendor instruction files (`CLAUDE.md`, `GEMINI.md`, `.gemini/`,
   `.cursor/rules`, `.github/copilot-instructions.md`, …).
2. Start the agent in the repository root, headless if it supports that, with file-reading tools disabled
   if possible, and send this test prompt:

   > Do not use any tools and do not read any files. Answer only from instructions already loaded into your
   > context at startup. 1) Was a project instructions/rules file loaded, and what is its file name? 2) List
   > this repository's hard rules in short bullets. If no project instructions were loaded, say exactly:
   > NO PROJECT INSTRUCTIONS LOADED.

3. **Pass** if it names `AGENTS.md` and lists the rules from its *Hard rules* section **without** a file-read
   tool call. If the tool can't disable tools, check its transcript or event log for read calls.
4. Add a row to the matrix with the version, date, exact command and any setup the user needed.

## Skills

BECK's skills live in `.agents/skills/<name>/SKILL.md`, and the index in [AGENTS.md](../AGENTS.md#skills) lists them (DEC-22).

**Checked on 2026-11-06** against [the specification](https://agentskills.io/specification) and [its guide for client authors](https://agentskills.io/client-implementation/adding-skills-support). The specification has no version number or releases, so
this is the date to go by. [Its source](https://github.com/agentskills/agentskills) last changed on 2026-08-04, at commit `217be548739f`.

### Frontmatter

These are the only fields the specification defines:

| Field | Required | Limits |
|---|---|---|
| `name` | Yes | 1–64 characters: `a-z`, `0-9` and hyphens. No hyphen at the start or end, no `--`, and it must equal the folder's name. |
| `description` | Yes | 1–1024 characters. It says what the skill does and when to use it. |
| `license` | No | A license's name, or the name of a bundled file. |
| `compatibility` | No | 1–500 characters. What the skill needs, such as tools or network access. Most skills don't need this. |
| `metadata` | No | A map of strings to strings. |
| `allowed-tools` | No | A space-separated list of pre-approved tools. It's experimental, and support varies. |

The frontmatter is YAML, so an unquoted value can't contain a colon followed by a space: `description: Use this when: ...` is invalid, though some agents accept it.

### Folders

- A skill is a folder with a `SKILL.md`. It may also have `scripts/`, `references/` and `assets/`, linked by relative paths, one level deep from `SKILL.md`.
- The specification recommends keeping `SKILL.md` under 500 lines and 5,000 tokens. BECK's own limit is lower, at about 150 lines ([stage 09](../roadmap/09-agent-skills-and-automation.md#agent-notes)).
- **The specification doesn't say where skills go in a repository.** The client guide calls `.agents/skills/` a "widely-adopted convention" for sharing skills across tools, which is the folder DEC-22 chose.
- Its validator, `skills-ref`, isn't used here: step 09.9 checks skills with the standard library, and using it would need a decision of its own.

### Which agents find which folder

From each vendor's documentation on the same date, for the agents in [the support matrix](#support-matrix). **None of this has been tested yet;** step 09.10 records what really happens.

| Agent | Installed here | Finds in a project | Finds `.agents/skills/` |
|---|---|---|---|
| Claude Code | 2.1.319 | [`.claude/skills/`](https://code.claude.com/docs/en/skills), in the folder it starts in and each parent up to the repository root, and in subfolders once it reads a file there | Not according to its documentation, which doesn't mention it. It gets there through the index in AGENTS.md. |
| opencode | 1.18.33 | [`.opencode/skills/`, and for compatibility `.claude/skills/` and `.agents/skills/`](https://opencode.ai/docs/skills/) | Yes, according to its documentation. That page describes its "V2", so version 1.18.33 may differ. |

So the index in AGENTS.md is still needed. DEC-22's decision stands, but its consequence "No tool auto-discovers `.agents/skills/` natively" no longer holds for opencode, according to that documentation.

## Coming later
- Using BECK itself from an agent (`--json`, exit codes, safety rules): steps 06.12 and 09.8.
