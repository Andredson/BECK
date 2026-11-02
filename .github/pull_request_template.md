<!--
Thanks for contributing to BECK! Fill in the sections below and delete what doesn't apply.
Roadmap protocol: roadmap/README.md. Agent rules: AGENTS.md.

AI agents: you never open this PR yourself (DEC-43). Prepare this description and print the
`gh pr create` command for the human to run.
-->

## Summary

<!-- What does this PR change, and why? One short paragraph. -->

## Type

- [ ] Roadmap stage: `stage/NN-…` (fill in the next section)
- [ ] Feature (stage 11 or a request linked below)
- [ ] Bug fix
- [ ] Documentation only
- [ ] Other:

Related issue(s): <!-- e.g. Closes #12 -->

## Roadmap steps covered

<!-- One row per step, in order. Paste the real output of each step's **Verify** command, or explain why it
can't run here (e.g. a human-only step). Shorten long output, but keep the result line. -->

| Step | Title | Verify result |
|---|---|---|
| NN.M | … | PASS / output below |

<details>
<summary>Verify output</summary>

```text
paste here
```

</details>

## Checklist

- [ ] Each step is its own commit with the step's Conventional Commits message.
- [ ] Step boxes are ticked in `roadmap/NN-*.md`, and the stage **Status** (in that file and in `roadmap/README.md`) is up to date.
- [ ] `AGENTS.md` is still accurate: commands, repository map, rules, skills index.
- [ ] No new tool, library, service, GitHub Action or bot without a new `DEC-NN` row **and** an ADR entry.
- [ ] No BIOS/ROM files, no real credentials, and no unanonymized reports anywhere in the diff.
- [ ] Destructive behavior is still opt-in (DEC-02): nothing deletes or renames a user's local file by default.
- [ ] No real Recalbox/SMB device was used unless the owner explicitly asked for it (results noted below).
- [ ] The standard checks from `AGENTS.md` pass locally (once stage 02 has added them) and CI is green.

## Notes for reviewers

<!-- Anything the reviewer should look at closely, human-only steps that were done (e.g. GitHub settings),
device test results, follow-ups proposed instead of done here. -->
