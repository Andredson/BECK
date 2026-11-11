# ADR-0001 — Product scope

- **Status:** Accepted
- **Date:** 2026-11-02
- **Decisions covered:** DEC-01, DEC-02, DEC-03, DEC-04, DEC-09, DEC-10, DEC-12, DEC-13, DEC-15, DEC-50, DEC-54, DEC-56, DEC-57, DEC-58, DEC-60, DEC-61, DEC-75, DEC-76, DEC-77

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
- **Status:** Accepted. Its deferral of SSH/SFTP is superseded by [DEC-75](#dec-75--the-hash-cache-and-sshsftp-are-dropped): SSH/SFTP is dropped.
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
- **Status:** Accepted. [DEC-61](#dec-61--files-on-the-device-are-kept-unless---overwrite-is-passed) adds the flag that can replace these files.
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

## DEC-57 — Exporting BIOS files from the target
- **Date:** 2026-11-05 (step 11.12).
- **Status:** Accepted. [DEC-58](#dec-58--export-copies-every-file) replaced its definition of a BIOS file, and [DEC-60](#dec-60--export-copies-only-rom-and-bin-files) restored it.
- **Context:** The owner asked for a way to copy the BIOS files on a target to the machine running BECK. A report only lists what's
  missing, so it can't say which files on the device are BIOS files. On a Recalbox 10.1.1 VM, the `bios` share has 3,108 files (317 MB),
  mostly `.ini`, `.png` and shaders.
- **Decision:**
  - Every `.rom` or `.bin` file under the target's BIOS root counts as a BIOS file. On the VM, that's 232 files and 41.9 MB. The match
    ignores case, which is the agent's reading, because real targets include names like `ATARIBAS.ROM`.
  - It's a command, `beck export DIR`, not a flag. The owner first asked for a flag, and chose a command once the design showed that
    `check --export` would make one command do opposite things.
  - A file that already exists locally is skipped.
- **Alternatives considered:**
  - *Everything on the share*: simple and complete, but mostly not BIOS files. Not chosen.
  - *Only what Recalbox's `es_bios.xml` lists*: exact, if it can be read, but needs research. Not chosen.
  - *Filters by name*: not chosen.
  - *`beck check --export DIR`*: not chosen, as above.
- **Consequences:** The command leaves out BIOS files of other types: 70 of the 232 targets in the real report, such as `neogeo.zip`,
  `atarist/tos.img` and the Amiga `kick*.A500` files. It also copies `.rom` and `.bin` files that aren't BIOS files. So it isn't a
  complete backup of a device's BIOS files, and its help and output must say so. The owner gave these rules without further reason, after
  seeing the file counts for the whole share. This entry's 70-of-232 figure was measured just afterwards.

## DEC-58 — Export copies every file
- **Date:** 2026-11-05 (step 11.12).
- **Status:** Superseded by [DEC-60](#dec-60--export-copies-only-rom-and-bin-files).
- **Context:** Under DEC-57, only `.rom` and `.bin` files counted. That left out 70 of the 232 targets in the real Recalbox 10.1.1
  report, such as `neogeo.zip` and `atarist/tos.img`. The agent showed the owner those figures.
- **Decision:** Every file under the target's BIOS root counts, whatever its type.
- **Alternatives considered:**
  - *Keep `.rom` and `.bin` only* (DEC-57): small, but not a complete backup. Not chosen.
  - *Add `.zip` and `.img`* (mentioned by the agent): covers more, but still not everything. Not chosen.
  - The owner gave no further reason.
- **Consequences:** Export is a complete copy of the folder: 3,108 files and 317 MB on the VM, most of it emulator settings, images and
  shaders. So the help must say what it copies, and `--dry-run` shows the size first. Hidden files are included, which is the agent's
  reading of "all the files".

## DEC-60 — Export copies only `.rom` and `.bin` files
- **Date:** 2026-11-05 (step 11.12).
- **Status:** Accepted. Supersedes [DEC-58](#dec-58--export-copies-every-file), and restores the definition in
  [DEC-57](#dec-57--exporting-bios-files-from-the-target).
- **Context:** After choosing to copy every file, the owner asked for a breakdown of the VM's `share/bios` folder: 3,108 files of 55
  types, 219.6 MB, with `.ini` and `.png` making up 82 % of the files. **Correction:** the 317 MB in DEC-57 and DEC-58 was disk usage
  from `du`, not the files' size.
- **Decision:** Keep the earlier rule. Every `.rom` or `.bin` file under the target's BIOS root counts as a BIOS file, in any case.
- **Alternatives considered:**
  - *Every file* (DEC-58): complete, but mostly not BIOS files. Not chosen.
  - *Adding `.zip` and `.img`* (mentioned by the agent): covers more, but also picks up files that aren't BIOS files. Not chosen.
  - The owner gave no further reason.
- **Consequences:** 232 files and about 42 MB on the VM. It leaves out 70 of the 232 targets in the real report, such as `neogeo.zip`,
  `atarist/tos.img` and the Amiga `kick*.A500` files, so it isn't a complete backup, and it copies `.rom` and `.bin` files that aren't
  BIOS files. The command's help and output must say so.

## DEC-61 — Files on the device are kept unless `--overwrite` is passed
- **Date:** 2026-11-05 (step 06.5).
- **Context:** BECK overwrote a file on the device with no warning. Recalbox reports a bad dump as `INCORRECT`, and `MISSING` means the
  file wasn't found, so a `MISSING` entry whose file exists usually means the report is out of date, and the file may be fine.
- **Decision:** Keep a file already on the device and report it. `--overwrite` replaces it, and that includes files listed as
  `INCORRECT`, which DEC-54 left open.
- **Alternatives considered:**
  - *Overwrite, as before*: simple, but silently replaces a possibly good file. Not chosen.
  - *Rename the old file to `<name>.beck-backup-<timestamp>`, then upload*: nothing is lost, but backups pile up in the BIOS folder.
    Not chosen.
  - *Skip by default, with `--overwrite` and `--backup`*: more flexible, and more to build. Not chosen.
  - The owner chose the option the agent recommended, and gave no further reason.
- **Consequences:** A re-run with an unchanged report changes nothing. `--overwrite` keeps no backup, and a failed upload can damage the
  old file. Each upload now checks the target first, which adds folder listings. On SMB, names that differ only in case count as the same
  file, as they do for Samba, or the check would miss a file that the upload then overwrites.

## DEC-75 — The hash cache and SSH/SFTP are dropped
- **Status:** Accepted. Keeping the dropped steps in the roadmap is superseded by [DEC-76](#dec-76--translations-are-dropped-and-dropped-steps-leave-the-roadmap): they're removed.
- **Date:** 2026-11-11, before step 11.1.
- **Context:** Stage 11 lists the features after 1.0, and step 11.1 asks the owner to mark each one planned, later or dropped. Before
  that, the agent had suggested *later* for the hash cache (11.6), and 11.11, SSH/SFTP, was deferred by DEC-04.
- **Decision:** **Supersedes DEC-04's deferral of SSH/SFTP.** Both features are dropped: 11.6, which would have cached MD5s between runs,
  and 11.11, which would have added an SSH/SFTP transport. Their steps stay in the roadmap, marked as dropped, as step 11.1 asks.
- **Alternatives considered:** None were offered: the owner asked for both to be cancelled. The owner gave no further reason.
- **Consequences:**
  - BECK hashes every file on every run. A large collection takes as long the second time.
  - SMB and a local folder stay the only transports, and paramiko or asyncssh won't be added.
  - `platformdirs` (DEC-19) is used only for the settings folder.
  - The rest of step 11.1 is still open: the other features have no status yet.

## DEC-76 — Translations are dropped, and dropped steps leave the roadmap
- **Date:** 2026-11-11, before step 11.1.
- **Context:** DEC-75 dropped 11.6 and 11.11, and kept their steps in the stage file marked as dropped, because step 11.1 said not to
  delete dropped items. The owner then dropped 11.10 too, and asked for the dropped features to be removed from the roadmap file.
- **Decision:** **Supersedes the part of DEC-75 that kept dropped steps in the roadmap.**
  - 11.10, translating BECK's messages, is dropped.
  - Dropped features are removed from `roadmap/11-feature-expansion.md`: 11.6, 11.10 and 11.11 are gone. A line under *Steps* names
    them, and the other steps keep their numbers, because decisions and other files refer to them, such as 11.12 in DEC-57 and DEC-60.
  - Step 11.1 now says to remove a dropped feature, not to keep it marked. The decision log and this ADR keep the record.
- **Alternatives considered:** None were offered: the owner asked for both. The owner gave no further reason.
- **Consequences:**
  - BECK's messages stay in English only, so there's no `gettext` or message catalog.
  - Older references to the removed steps stay as they were, because accepted decisions aren't edited: DEC-04's "deferred item (step
    11.11)", DEC-19's "hash cache (11.6)" and DEC-75.

## DEC-77 — Other systems move from the roadmap to issues
- **Date:** 2026-11-11, before step 11.1.
- **Context:** Stage 11 had three steps for other systems: 11.7, a Batocera adapter, and 11.8, a RetroBat adapter, both blocked by real
  data from those systems, and 11.9, research into RetroPie and Lakka. The owner asked for them to leave stage 11 and become issues, to
  be developed later by the owner or another developer.
- **Decision:** Steps 11.7, 11.8 and 11.9 are removed from `roadmap/11-feature-expansion.md`, and are GitHub issues instead:
  [#21](https://github.com/Andredson/BECK/issues/21) (Support Batocera), [#22](https://github.com/Andredson/BECK/issues/22) (Support RetroBat) and [#23](https://github.com/Andredson/BECK/issues/23) (Research RetroPie and Lakka support). Each issue
  keeps the step's procedure, its blocker and its *Done when*. The stage file lists them under *Other systems*.
- **Alternatives considered:** None were offered: the owner asked for it. The owner gave no further reason.
- **Consequences:**
  - Stage 11 can close without them. They aren't dropped: DEC-03's adapter interface and the `add-frontend-adapter` skill stay.
  - The issues are labelled `type: feature` and `help wanted`. #21 and #22 are `blocked` until someone sends real data, and #21 also has
    `frontend: batocera`. There's no `frontend: retrobat` label yet: the owner adds one when work starts, as the label guide says.
