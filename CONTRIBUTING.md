# Contributing to BECK

Thanks for helping. BECK is open to outside contributors (DEC-12), whether you're fixing a typo or adding a new system. This file says
how to set up, what to work on, how to send it, and [how we treat each other](#code-of-conduct). [`AGENTS.md`](AGENTS.md) has the commands and the rules, for people and for AI
agents. Where both cover something, it has the exact commands, so this file links to them rather than copying them.

## Ways to help

- **Report a bug.** [Open an issue](https://github.com/Andredson/BECK/issues/new) with:
  - what `beck --version` prints, your operating system, and your Recalbox version;
  - the command you ran, without any password;
  - its `--json` output, which keeps passwords out, or its output with `-v`;
  - what you expected, and what happened instead.

  Never paste a password or attach a BIOS file. For a security problem, follow [the security policy](SECURITY.md) instead, and don't
  open a public issue.
- **Share a missing-BIOS report** from a Recalbox version, or a device, that BECK hasn't seen. Reports are how BECK learns new versions,
  and [sharing one safely](#sharing-a-report-safely) takes a few minutes.
- **Improve the docs.** If a guide confused you, or [the troubleshooting guide](docs/troubleshooting.md) doesn't have a message you
  saw, an issue or a PR helps the next person.
- **Write code.** [The roadmap](roadmap/README.md#stages) lists the planned work, step by step. For anything that isn't on it, open an
  issue first, so that we can agree on it before you spend time.
- **Help support another system,** such as Batocera or RetroBat. Open an issue saying how that system reports missing BIOS files, with an
  anonymized example of what it produces. [The `add-frontend-adapter` skill](.agents/skills/add-frontend-adapter/SKILL.md) is how the
  code then gets written.

## Setting up

You need [git](https://git-scm.com/) and [uv](https://docs.astral.sh/uv/getting-started/installation/). uv installs the right Python
(3.11, from `.python-version`) and every tool the checks use, at the versions in `uv.lock`.

1. Fork the repository on GitHub, and clone your fork.
2. In the clone, run `uv sync`.
3. Run the check line in [AGENTS.md → Commands](AGENTS.md#commands), the one under "Before committing". If it passes on an unchanged clone,
   you're set up.

That line is the same as the `quality` and `tests` jobs in CI (DEC-25), so if it passes on your machine, those jobs should pass too. The
other commands are in the same section: formatting, building, and the optional checks for commit messages, secrets and dependencies. The
integration tests need [Podman](https://podman.io/) and [the Samba test server](tests/integration/samba/README.md), never Docker
(DEC-55). Without them they're skipped locally, and CI runs them.

`uv run beck check`, and `uv run beck` on its own, connect to whatever your settings name, which may be your real Recalbox, and copy files
to it. For development, use `--dry-run`, a local folder as the target, or the Samba test server.

## How the roadmap works

[The roadmap](roadmap/README.md) is the plan. It's split into **stages**, and each stage is a file of numbered **steps**, such as 12.1.
Each step says what to change, which files, how to verify it, and the commit message. Work goes in order: the first unticked step that
isn't marked `BLOCKED`, in the lowest-numbered stage that isn't done ([how](roadmap/README.md#how-to-execute-a-step-humans-and-agents)).
Progress is tracked only by the step boxes (DEC-16).

**The decision log** at the bottom of [the roadmap](roadmap/README.md#decision-log) records every choice that shapes the project, as
`DEC-NN` rows. [The ADRs](docs/adr/README.md) have the reasons, and the alternatives that were turned down. Read the relevant one before
proposing a change: an accepted decision is never edited, and [a new one replaces it](docs/adr/README.md#changing-a-decision).

**Ask before adding a tool.** A new library, tool, service, GitHub Action or bot needs a decision first. In an issue or a PR, say what
it's for, and give two to four alternatives with their trade-offs and the one you'd pick. The owner decides, and the answer is recorded
as a new DEC and in an ADR ([how](docs/adr/README.md#adding-a-decision)) before it's used. New dependencies also wait out a 14-day
cooldown (DEC-45), which `uv add` respects.

## Branches and pull requests

- **One PR per roadmap stage or per feature.** A stage's branch is `stage/NN-slug`, named in [the stage table](roadmap/README.md#stages).
  A feature from stage 11 uses `feature/<slug>`. For a bug fix or a docs change, any short descriptive name works.
- **One commit per roadmap step,** with the step's commit message. Outside the roadmap, keep each commit to one change.
- **Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):** `type(scope): summary`, such as
  `fix(parser): keep INCORRECT blocks apart`. Types include `feat`, `fix`, `docs`, `test`, `refactor`, `build`, `ci`, `chore` and
  `perf`. Add `!` after the type for a change that breaks something users rely on. CI's `commits` job checks every commit in a PR
  (DEC-38), and the messages become [the changelog](#docs-changelog-and-versions).
- **Open the PR against `main`,** and fill in [the template](.github/pull_request_template.md), including whether
  [AI helped](#ai-assisted-contributions). For a roadmap step, paste its Verify output. Put anything you noticed but didn't change under *Notes for reviewers*, as a proposal, not in the diff.
- **CI must pass.** `main` only takes changes through a PR, once [the required checks](AGENTS.md#commits-and-pull-requests) have
  passed, and nobody can bypass that. On your first PR, CI waits until the maintainer approves the run.
- **PRs are merged with a merge commit** (DEC-39), so your commits stay as they are on `main`. If CI rejects a commit message, fix it
  on your PR branch before it's merged, for example with `git commit --amend` for the last commit, and push it again.

AI agents working in this repository follow [AGENTS.md](AGENTS.md#hard-rules): they commit and push a stage branch, and hand over
branches, PRs and tags to a person.

## Tests and fixtures

- **Every bug fix comes with a test** that fails without the fix. Coverage below 90% fails the run, and `# pragma: no cover` is
  turned off. [AGENTS.md → Testing](AGENTS.md#testing) has the details.
- **Tests never use real BIOS files.** Test files are random bytes, from `tests/factories.py`. MD5 values and file names are fine.
- **Unit tests never touch the network or a device.** They use the in-memory SMB server in `tests/fakes.py`, and temporary folders.
  The integration tests only accept the Samba test server, so that they can't write to a real device. Don't work around that.

### Sharing a report safely

Recalbox's missing-BIOS report (`missing_bios_report.txt`) lists file names, folders and MD5 values. [This guide](docs/user-guide/generate-report.md)
says how to generate it and where it ends up.

1. **Send the file itself,** attached to an issue. Pasting it, or copying it through a terminal, can change its line endings, and the
   tests need it byte for byte.
2. **Read it through first.** Replace anything that points to you or your network: a host name, a user name, a network name, an IP or MAC
   address, an email address, or a path under a home folder. Change only those characters. File names and MD5 values stay, because
   they're public and they're what BECK matches.
3. **Say which Recalbox version and device** it came from, the menu path you used, and what state it was in, such as a fresh install.
   Say whether the `Generated on` date can stay.

A report holds no BIOS content, so it's safe to share once it's anonymized. [The fixtures guide](tests/fixtures/README.md) and
[the `add-report-fixture` skill](.agents/skills/add-report-fixture/SKILL.md) say how it then becomes a test.

## Docs, changelog and versions

- **Docs change with the code.** A new error message needs an entry in [the troubleshooting guide](docs/troubleshooting.md), and a test
  checks for it. After changing a flag or its help, regenerate [the CLI reference](docs/cli-reference.md) with
  `uv run python scripts/gen_cli_reference.py`. A change to the `--json` output follows [its guide](docs/json-output.md): it's a public
  contract, so changing an existing field needs the owner's OK first.
- **Links in Markdown are checked** by `tests/test_docs_links.py`. In `README.md`, use absolute GitHub links, so that they work on PyPI
  too (DEC-68).
- **Never edit `CHANGELOG.md` by hand.** It's generated from the commit messages by git-cliff (DEC-20), when a release is prepared.
- **Versions and tags** are described in [the release guide](docs/releasing.md). Only the owner tags and publishes releases.

## AI-assisted contributions

AI-assisted contributions are welcome, from an editor's suggestions to an agent working through a roadmap step.

- **You're responsible for every change,** however it was written. Understand it, test it, and be able to explain it when a reviewer
  asks.
- **Agents follow [`AGENTS.md`](AGENTS.md)** and [the roadmap protocol](roadmap/README.md#how-to-execute-a-step-humans-and-agents).
  Most agents read `AGENTS.md` by themselves; [docs/agents.md](docs/agents.md) lists the ones tested.
- **Generated code passes the same checks** as any other: the same tests, coverage, lint, type checks and review.
- **Never paste secrets or personal data into an AI tool** while working on BECK: no passwords or tokens, and no report, log or output
  you haven't [anonymized](#sharing-a-report-safely). If an agent runs BECK for you, set `BECK_SMB_PASSWORD` yourself rather than
  giving it the password.
- **Say so in your PR.** [The template](.github/pull_request_template.md) asks whether AI tools helped write it, and which ones if they
  did. Tick one of its two boxes (DEC-69). It doesn't count against the PR; it tells the reviewer where to look.

## Code of conduct

These rules apply wherever BECK is discussed: issues, pull requests, reviews and commit messages (DEC-31).

- **Be respectful and constructive.** Criticize the work, not the person.
- **No harassment or personal attacks.**
- **Keep discussions about the work.**

The maintainer may edit or remove comments, and block people who break these rules.

**To report a problem,** open an issue that says only that you'd like to report a conduct problem, and asks for a private way to do it.
Leave out names and details, because issues are public. The maintainer will reply with a private way to tell them.

## Legal

- **No BIOS files, ever.** BIOS files are copyrighted. Don't add one to the repository, attach one to an issue, or say where to get one.
  BECK only works with files people already own.
- **Your contribution is licensed under [GPL-3.0-only](LICENSE),** the license BECK uses (DEC-13). Every Python file starts with
  `# SPDX-License-Identifier: GPL-3.0-only`, and a test checks for it.
