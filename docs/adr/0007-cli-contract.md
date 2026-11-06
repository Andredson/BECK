# ADR-0007 — The CLI contract

- **Status:** Accepted
- **Date:** 2026-11-05
- **Decisions covered:** DEC-59. The rest of the contract follows from DEC-02, DEC-05, DEC-17, DEC-23 and DEC-54 (rows in the
  [decision log](../../roadmap/README.md#decision-log)).

## Context
BECK is meant to be driven by people, scripts and AI agents. The last two can't read human output reliably, so what they depend on has
to be stable: the exit codes and the JSON output. [docs/cli.md](../cli.md) is the user reference, and this ADR records why.

## Decision

### Exit codes are a contract
Codes 0 to 5 have fixed meanings, listed in [docs/cli.md](../cli.md#exit-codes), and each `BeckError` subclass has a fixed code. A
script can branch on the code without parsing anything. Changing a code's meaning is a breaking change.

Exit 0 means that the run completed, not that nothing is missing. A device can legitimately still miss files the user doesn't own, so
failing on that is opt-in, with `--fail-if-missing`.

### JSON is one document on stdout
With `--json`, stdout has exactly one JSON document, including for errors that stop a run, and everything else goes to stderr. A
consumer can parse stdout without checking anything first.

### The compatibility promise
Within `schema_version` 1, fields are only added. Renaming, removing or changing the meaning of a field means `schema_version` 2.
Consumers must ignore unknown fields. Contract tests enforce this (step 06.8), and agents must ask the owner before changing an
existing field.

### Details settled in step 06.7
The roadmap listed the main fields. Building them raised these details, which the agent settled and reported to the owner:

- **JSON never knows less than the human output.** So it has `uploads[].replaces`, because a dry run's `planned` can't show that an upload
  would overwrite a file, and `already_filled[]` and `unreadable[]`, because otherwise those files would vanish from the result.
- **List items are objects, not strings,** even when one field would do, so that fields can be added within version 1.
- **One item per target,** with its MD5s merged, because a file listed in several systems is one file to find. That's the rule `beck report`
  already uses for people.
- **`target` is a URL with no user name** as well as no password, built by a new `Transport.url()`. `describe()` stays a sentence for
  messages.
- **A command line BECK can't parse still gives a document,** with only the common fields and `command: null`, because no command ran.
  It has its own schema, a fourth one. BECK looks for `--json` before parsing, since parsing is what failed.
- **A bug's message stays on stderr,** because it could hold anything, including a password.
- **The schemas allow extra fields,** so that a newer BECK still validates against them.

### Deleting is always explicit
Nothing is deleted without `--move` or `--clean-unmatched`, and off a terminal not without `--yes` too. `--json` never prompts, so that
a consumer can't hang on a question or confirm one by accident.

## Alternatives considered
These were offered to the owner, and are recorded in [ADR-0002](0002-ai-agent-support.md#dec-23--versioned-json-output-and-stable-exit-codes)
and [ADR-0001](0001-product-scope.md#dec-02--non-destructive-by-default):

- *JSON documented only by example*: consumers could break silently when fields change. Not chosen.
- *Exit codes only*: agents would have to parse human-readable text. Not chosen.
- *Keeping move-and-delete, with a prompt*: it keeps a risky default. Not chosen.

The one-document-on-stdout rule and the `--json` no-prompt rule came from the roadmap plan, and weren't offered as a separate choice.

## Consequences
- **Easier:** scripts and agents can drive BECK with no integration code (DEC-05).
- **Harder:** the output can't change freely, and a mistake in schema v1 stays until v2.
- **Roadmap:** steps 06.2–06.12 build this, and stage 09's skills copy the exit-code table, with a test keeping them equal.
- **Revisit if:** the output needs a change that can't be made by adding fields.

## DEC-59 — Four CLI rules
- **Date:** 2026-11-05 (step 06.1).
- **Context:** Writing [docs/cli.md](../cli.md) showed cases the roadmap didn't cover. The agent proposed these rules, and the owner
  confirmed all four.
- **Decision:**
  - `--clean-unmatched` never deletes a file valid for an `INCORRECT` target, because that file is the fix for the one on the device.
  - A required `INCORRECT` file counts for `--fail-if-missing`, because the device still can't use it.
  - A transport error (3) beats `--fail-if-missing` (5), because the run didn't do all it could.
  - A local file that can't be read doesn't change the exit code, because the run completed and that file couldn't have matched.
- **Alternatives considered:** none were offered separately. The owner gave no further reason.
- **Consequences:** Steps 06.2a, 06.6 and 06.9 implement them.
