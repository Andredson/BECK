# ADR-0001 — Product scope

- **Status:** Accepted
- **Date:** 2026-11-02
- **Decisions covered:** DEC-01, DEC-02, DEC-03, DEC-04, DEC-09, DEC-10, DEC-12, DEC-13, DEC-15, DEC-50, DEC-54, DEC-56

## Context
At the baseline review ([assessment](../../roadmap/00-assessment.md)), BECK was a 243-line script with an overall
score of 3/10. It deleted user files by default, could only talk SMB to Recalbox, kept credentials in a tracked
file, and had no packaging. Before planning improvements, the owner chose what BECK should become. Options were
presented with trade-offs and a recommendation; the owner's choice is recorded here, including where it
differed from the recommendation.

## DEC-01 — An installable CLI named `beck`
- **Decision:** BECK becomes a Python package installable with pipx, `uv tool` or pip, with a `beck`
  command. It stays terminal-focused.
- **Alternatives considered:**
  - *CLI plus standalone binaries* for users without Python: not chosen; it adds a build-and-release stage
    for every OS.
  - *CLI now, GUI/TUI later*: not chosen; no graphical front-end is planned.
  - *Keep a simple single-file script*: not chosen; lowest maintenance, but no packaging and no room for
    the planned structure.
- **Consequences:** Stage 04 introduces a `src/beck` package; stage 10 publishes it. No stage plans a GUI.

## DEC-02 — Non-destructive by default
- **Decision:** BECK copies matched files and never deletes or renames local files unless asked. `--move`
  (delete after a verified upload) and `--clean-unmatched` are opt-in; `--dry-run` previews everything.
- **Alternatives considered:**
  - *Keep move-and-delete, add `--dry-run` and a confirmation prompt*: not chosen; it keeps today's risky default.
  - *Quarantine folders* (`bios/_sent/`, `bios/_unmatched/`): not chosen; nothing is deleted, but files still get
    moved around without being asked.
- **Consequences:** Step 03.10 removes both deletions right away; step 06.6 adds the opt-in flags with
  confirmation, and requires `--yes` when not on a TTY. AGENTS.md makes this a hard rule.

## DEC-03 — Recalbox first, behind a pluggable frontend interface
- **Decision:** Support Recalbox fully first. Design a frontend-adapter interface now, so Batocera, RetroBat and
  RetroPie/Lakka can be added later.
- **Alternatives considered:**
  - *Recalbox only*: simplest architecture (recommended during planning), but would need rework for any second
    frontend.
  - *Multi-frontend from the start*: much bigger scope before the basics are solid.
- **Consequences:** Step 04.7 defines `FrontendAdapter` with a single Recalbox implementation. Stage 11 adds
  other frontends, each gated on real reference data.

## DEC-04 — Transports: SMB plus a local path
- **Decision:** Keep SMB and add a local-folder transport (mounted SD card or USB drive, or running on the device).
  SSH/SFTP is deferred.
- **Alternatives considered:**
  - *SMB only*: not chosen; there's no local mode, and real-file tests become harder.
  - *SMB + local + SSH/SFTP*: not chosen for now; it adds a dependency such as paramiko. It stays as a
    deferred item (step 11.11).
- **Consequences:** Step 04.8 adds `LocalTransport`, which doubles as the main test double. Step 04.9 rewrites SMB.

## DEC-09 — Real Recalbox reports as fixtures
- **Decision:** The owner supplies anonymized real `missing_bios_report.txt` files, one per Recalbox version.
  Parser work is gated on them, and the supported versions are the versions with fixtures.
- **Alternatives considered:**
  - *Synthetic fixtures written from the current regexes*: not chosen; faster to start, but tests written from the
    parser's own assumptions give false confidence.
- **Consequences:** Steps 03.4 and 03.5 are blocked until a real report exists. Derived edge-case fixtures must
  say which real report they come from.

## DEC-10 — Credentials: env vars, prompt, guest
- **Decision:** The config file is gitignored, with a committed example. Credentials can come from `BECK_*`
  environment variables or a `getpass` prompt, and guest login is supported (the Recalbox default). From stage 07,
  passwords are never stored in the config file at all.
- **Alternatives considered:**
  - *Also the OS keyring* (the `keyring` package): not chosen; an extra dependency for a small gain.
  - *Config file only, gitignored*: not chosen; it keeps plaintext passwords on disk.
- **Consequences:** Step 03.2 untracks the config file; steps 07.1, 07.4 and 07.5 add precedence, prompting and
  redaction.

## DEC-12 — Open to contributors
- **Decision:** BECK welcomes outside contributors and gets the usual governance files.
- **Alternatives considered:** *Personal project with minimal governance*: not chosen.
- **Consequences:** Stage 12 adds CONTRIBUTING, issue forms and labels; step 07.8 adds `SECURITY.md`.

## DEC-13 — License metadata: `GPL-3.0-only`
- **Decision:** Package metadata and SPDX headers use `GPL-3.0-only`. The `LICENSE` file (GPLv3 text) is unchanged.
- **Alternatives considered:** *`GPL-3.0-or-later`* (the FSF's recommended wording, which lets the project adopt
  future GPL versions; recommended during planning): not chosen by the owner.
- **Consequences:** Steps 08.7 and 10.2 use this exact identifier. Moving to a later GPL version would need
  every copyright holder's agreement once outside contributions exist.

## DEC-15 — PyPI name `beck-bios`
- **Decision:** Publish as `beck-bios`; the command stays `beck` and the import name is `beck`.
- **Alternatives considered:**
  - *Try `beck`, fall back to `beck-bios`* (recommended during planning): not chosen; the owner preferred the
    specific name from the start.
  - *`recalbox-beck`*: not chosen; it becomes misleading once other frontends are supported (DEC-03).
- **Consequences:** Step 10.1 checks that the name is free. If it's taken, a new DEC supersedes this one. Step 04.3
  sets `module-name = "beck"`.

## DEC-50 — Two locations in a report entry: use the first
- **Date:** 2026-11-04 (step 03.4).
- **Context:** The first real report (Recalbox 10.1.1) has two entries of the form `Path: <path> or <path>`:
  `tos.img` and one `neogeo.zip`. The second `neogeo.zip` location is outside the `bios` share.
- **Decision:** Use the first location. In this report, every first location is inside `/recalbox/share/bios/`.
- **Alternatives considered:**
  - *Check each location first, then upload only if none has the file*: more thorough, but more work, and better
    suited to a later stage. Not chosen. The owner gave no further reason.
- **Consequences:** Step 03.5 keeps only the first location. A file already at the second location could still be
  uploaded to the first.

## DEC-54 — A file that's INCORRECT on the device is kept and reported
- **Date:** 2026-11-05 (step 05.3a).
- **Context:** Recalbox's source and its 10.1.1 binary show a second kind of report block, `INCORRECT REQUIRED|OPTIONAL BIOS`,
  for a file that exists with a hash that isn't on the list, when `hashMatchMandatory` is true. It has a `Current MD5:` line.
  BECK didn't know it: the block merged into the entry above, so valid files, and even the rejected file itself, uploaded
  under the wrong name. Stopping that merge was a plain fix. What to do with the target itself was the owner's decision.
- **Decision:** Keep the device's file, show it in the output and exit normally. Never upload to that target, even with a
  valid local file, and even if another entry lists the same target as missing.
- **Alternatives considered:**
  - *Replace the wrong file with a valid one*: fixes it automatically, but loses the device's file with no backup, ahead of
    step 06.5's policy. Not chosen.
  - *Stop with an error*: impossible to miss, but one bad file blocks every other upload. Not chosen.
  - The owner chose the option the agent recommended, and gave no further reason.
- **Consequences:** The user replaces such a file by hand for now, and BECK names a local file that would fit. Step 06.5
  decides whether a flag can replace these files. Step 06.7 adds them to the JSON output.

## DEC-56 — `--clean-unmatched` stays, with a warning
- **Date:** 2026-11-05 (step 06.1).
- **Context:** Writing the CLI design showed a risk in DEC-02's `--clean-unmatched`. "Unmatched" only means that the current report
  doesn't ask for a file. After an upload and a rescan, the report no longer lists the user's good files, so a later run with this
  flag treats them as unmatched and deletes them, unless the user reads the confirmation list closely.
- **Decision:** Keep the flag as planned, with its confirmation, and a prominent warning in the documentation that recommends a dry run first.
- **Alternatives considered:**
  - *Remove the flag* (recommended by the agent): the safest, because a wrong delete can't be undone, and users can delete files
    themselves. Not chosen. The owner gave no further reason.
  - *Delete only files BECK can recognize as junk*: safer, but BECK has no such list, and building one is real work. Not chosen.
- **Consequences:** Step 06.6 implements the flag, and its plan output must make the risk plain. The risk stays for a user who confirms
  without reading.
