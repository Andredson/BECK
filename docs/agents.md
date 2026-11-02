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

## Coming later
- Agent Skills and how agents discover them: step 09.1.
- Using BECK itself from an agent (`--json`, exit codes, safety rules): steps 06.12 and 09.8.
