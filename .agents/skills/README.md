# BECK's Agent Skills

A skill is a procedure an agent follows for a task that takes several steps, in the open [Agent Skills format](https://agentskills.io/specification). This is the only place they live (DEC-22): no copies, symlinks or vendor folders such as `.claude/skills/`.

Not every agent looks in this folder by itself, so [the index in AGENTS.md](../../AGENTS.md#skills) is how an agent finds a skill. [Which agents find what](../../docs/agents.md#skills) has the details, with the limits below and when they were checked.

## The format

Each skill is a folder with a `SKILL.md`:

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

- **Fields:** only the ones the format defines, each on one line. `compatibility` is only for a skill that needs something particular.
- **`name`:** at most 64 lowercase letters, digits and hyphens, with no hyphen at either end and no `--`. It must equal the folder's name.
- **`description`:** what the skill does and when to use it, in at most 1024 characters. Agents decide from this line alone, so name the words someone would use. It can't contain a colon followed by a space, because that isn't valid YAML.
- **Body:** plain Markdown, and a procedure rather than documentation. Link to the repository's documents instead of repeating them, so that a skill can't drift from them.
- **Length:** about 150 lines at most. Move reference material to `references/`, next to `SKILL.md`, and link to it by relative path. Scripts go in `scripts/`, and use the standard library only.

## Adding a skill

1. Check that a task really needs one: a single command belongs in [AGENTS.md](../../AGENTS.md#commands) instead.
2. Create `.agents/skills/<name>/SKILL.md` in the format above.
3. Add a row to [the index in AGENTS.md](../../AGENTS.md#skills).
4. Check it with `uv run pytest tests/test_skills.py -q`, which checks the format, its links and the index.
5. Give the same short task to agents from two vendors, and record in [docs/agents.md](../../docs/agents.md) whether they found the skill, followed it and kept to the safety rules. Fix the wording where they went wrong, rather than adding a copy for one vendor.

A skill never overrides [the hard rules in AGENTS.md](../../AGENTS.md#hard-rules).
