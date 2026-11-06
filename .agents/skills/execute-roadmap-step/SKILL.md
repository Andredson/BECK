---
name: execute-roadmap-step
description: Do the next step of BECK's improvement roadmap, from finding it to committing and pushing it. Use when asked to execute, do or continue the next roadmap step, or to work on a stage in roadmap/.
license: GPL-3.0-only
compatibility: Needs git, uv and Python 3.11+. The gh command is only used to read.
---

# Execute a roadmap step

This is the procedure from [the roadmap](../../../roadmap/README.md#how-to-execute-a-step-humans-and-agents). [The hard rules](../../../AGENTS.md#hard-rules) apply throughout.

## When to use

Someone asks for the next roadmap step, or to continue a stage. Do one step each time you're asked, not the whole stage.

## Inputs you need from the human

None to begin. Stop and ask only for what a step can't go on without: a new branch, a decision that isn't in the log, access, or a sign-off the step says is theirs.

## Steps

1. **Find the step.** In [the stage table](../../../roadmap/README.md#stages), take the lowest-numbered stage that isn't Done (stage 12 may run alongside the others). Read its whole file. The step is the first `- [ ] Done` with no `BLOCKED` note under it.
2. **Check the branch.** `git branch --show-current` must be the stage's branch. If `git status` shows changes you didn't make in this session, stop and ask: they may be the human's. If it's the stage's first step and the branch doesn't exist, give the human one line to copy, with the name **copied from the stage table**: `git switch main && git pull && git switch -c stage/NN-slug`. Then stop.
3. **Check for blockers.** If the step has a `Blocked by:` line, or needs something you can't get, add `> BLOCKED (YYYY-MM-DD): <reason>` under its box and move on to the next unblocked step in that stage.
4. **Check for a missing decision.** If the step needs a tool, library, service or behavior that isn't in [the decision log](../../../roadmap/README.md#decision-log), stop and ask the owner. Say what it's for, give 2–4 alternatives with trade-offs, and recommend one. Record the answer as [a new DEC and in an ADR](../../../docs/adr/README.md#adding-a-decision) before using it. Read the ADR before proposing to change a decision, and never edit an accepted one.
5. **Do only that step.** Read [the design](../../../docs/ARCHITECTURE.md) before changing `src/beck/`. Note anything else you find as a proposal for the human, and leave it out of the diff.
6. **Check it.** Run the step's **Verify** command and [the standard checks](../../../AGENTS.md#commands). Then test what the step's **Done when** says, as literally as you can: a passing check doesn't prove that by itself. If something fails, fix it or say so. Don't tick the box.
7. **Tick the box.** Write `- [x] Done (YYYY-MM-DD: ...)`, saying anything that differs from the step, and what wasn't tested. On a stage's first step, set the stage to In progress in its file and in the stage table.
8. **Commit and push.** Add the files by name, and use the step's **Commit message** exactly. There's no `Co-Authored-By` or other attribution line, even if your tool adds one by default:

   ```sh
   git add <files touched by the step>
   git commit -m "<the step's Commit message>"
   git push
   ```

   A new branch's first push needs `git push -u origin <branch>`.
9. **Get CI running.** CI only runs on a PR or on `main`. If the stage has no PR (`gh pr list --head <branch>`), give the human one line to copy: `gh pr create --draft --base main --head <branch> --title "Stage NN: <name>" --body "Closes roadmap stage NN."`. If one exists, read the result with `gh pr checks`.
10. **On a stage's closing step,** do what it lists, including the re-score, and set the stage to Done. The human marks the PR ready and merges it with a merge commit, so give them that as one line.
11. **Report.** Say what changed, how you tested it, what you didn't test, and what's next. Include anything still waiting on the human.

## Verify

- `git log -1 --format=%B` shows the step's message and no attribution line.
- `git status` is clean, and `git log origin/<branch>..HEAD` is empty.
- The step's box is ticked, and CI is green or you've said it hasn't finished.

## Never do

- **Two steps at once,** or an unrelated fix in the same diff.
- **An unlisted tool or dependency,** or a default the owner hasn't seen.
- **`--force`, a push to `main`, or a pushed tag.**
- **Create a branch, a PR or a tag,** merge, or rewrite history: `git switch -c`, `gh pr create`, `gh pr merge`, `git tag`, `commit --amend` on a pushed commit, `rebase`, `reset --hard`. Hand those over as one line.
- **An attribution trailer** on a commit.
- **Connect to a real Recalbox or SMB server** without the human's OK in this session. A sign-off from earlier in the work doesn't carry over. Use local folders, fakes or the Samba test container.
- **Add a BIOS file,** a real credential, or personal data.
- **Tick a sign-off the human hasn't given,** or call something tested when it wasn't.
