# Stage 11 — Feature expansion

**Status:** In progress · **Depends on:** 10 · **Branch:** one per feature, `feature/<slug>` · **Effort:** L (total)

## Goal
Grow BECK beyond a polished Recalbox tool: fewer manual steps for users, and smarter matching. Support for other retro-gaming
frontends, through the adapter interface built in stage 04 (DEC-03), moved to GitHub issues (DEC-77): see [Other systems](#other-systems).

## Why
- "Idea & usefulness" is BECK's strongest aspect (8/10); this stage builds on it.
- Every feature here depends on facts that can't be known from this repository (device file formats, other
  frontends' reports, licensing of hash lists). So each feature starts with **research and an owner decision**,
  never with code.

## Decisions applied
DEC-03, DEC-04, DEC-09, DEC-14, DEC-22, DEC-43, DEC-75, DEC-76, DEC-77.

## How to run a feature in this stage
Each feature below is independent and goes through the same sub-steps, using the
`add-frontend-adapter` skill (09.6) where it applies:

1. **Research**: collect real data (reports, file lists, screenshots) from the owner or a contributor; write
   down the findings.
2. **Decide**: present the options to the owner, record a DEC and an ADR. If a new dependency or tool is
   needed, explain its purpose and the alternatives first.
3. **Implement** on `feature/<slug>`, with tests and fixtures.
4. **Document** in the README, troubleshooting guide and `docs/cli.md`; add skill or AGENTS.md updates if needed.
5. The owner merges with a merge commit; the release goes through stage 10's checklist.

## Steps

Steps 11.6 (hash cache), 11.10 (translations) and 11.11 (SSH/SFTP transport) were dropped and removed (DEC-75, DEC-76). Steps 11.7–11.9
moved to GitHub issues (DEC-77), listed under [Other systems](#other-systems). The other steps keep their numbers, because decisions and
other files refer to them.

**The order, chosen in step 11.1:**

| Order | Step | Value | Cost |
|---|---|---|---|
| planned (1) | [11.12](#1112--export-copy-bios-files-from-the-target-to-this-machine) Export | Back up the BIOS files on a device, or move them to another one. Its design is decided (DEC-57, DEC-60). | M |
| planned (2) | [11.4](#114--zip-aware-matching) Zip-aware matching | Matches the zip archives users keep. Recalbox hashes a `.zip` target by its contents (DEC-74), which BECK can do too. | M |
| planned (3) | [11.2](#112--report-less-recalbox-mode) Report-less mode | Removes the one manual step on the device. On the 10.1.1 VM (2026-11-11), Recalbox's web manager API gave the same list as the report. | M |
| planned (4) | [11.3](#113--per-system-summary) Per-system summary | Shows what's still missing for each system, for people and in `--json`. | S |
| later | [11.5](#115--multiple-sources-and-filters) Multiple sources and filters | Saves gathering files into one folder first. | S |

### 11.1 — Prioritize with the owner
- [x] Done (2026-11-11: the owner chose the agent's suggested order, above. The owner had already dropped 11.6, 11.10 and 11.11
  (DEC-75, DEC-76), and moved 11.7–11.9 to issues #21–#23 (DEC-77).)
- **What:** Present the features below (11.2–11.5 and 11.12) with a one-line value and a cost estimate. Ask the
  owner to choose which ones to pursue and in what order, and to drop or add items. Record the order in this file, and
  remove dropped items from it: the decision log keeps the record (DEC-76).
- **Files:** this file
- **Done when:** Each feature is marked *planned (n)* or *later*, and dropped ones are removed.
- **Verify:** Owner sign-off.
- **Commit message:** `docs(roadmap): prioritize feature expansion with the owner`

### 11.2 — Report-less Recalbox mode
- [ ] Done
- **Priority:** planned (3)
- **What:** Today the user must first generate `missing_bios_report.txt` on the device. Research whether
  Recalbox keeps its BIOS definitions (names, paths, MD5s) in a file BECK could read directly over SMB or a
  local path, for each supported version, and whether that file is reachable from the shares. If it is, add a
  mode in `RecalboxAdapter` that computes "missing" by checking which expected files are absent or have the
  wrong MD5, with the report as a fallback.
- **Files:** `docs/research/recalbox-bios-definitions.md`, `src/beck/frontends/recalbox.py`, fixtures, tests
- **Done when:** On a real device, `beck check --dry-run` gives the same result with and without a generated report.
- **Verify:** Fixture tests plus an owner-run comparison on the device.
- **Commit message:** `feat(recalbox): detect missing BIOS without a generated report`

### 11.3 — Per-system summary
- [ ] Done
- **Priority:** planned (4)
- **What:** In `beck report` and the `check` summary, group entries by system or folder, showing counts of
  satisfied, still missing (required) and still missing (optional). Add the same grouping to the JSON output as
  a **new field** (allowed within schema v1; see the 06.7 compatibility promise).
- **Files:** `src/beck/output/*`, `docs/schemas/*.json`, tests
- **Done when:** Both the human and JSON outputs show the grouping, and contract tests pass.
- **Verify:** `uv run pytest -q -k "summary or contract"`
- **Commit message:** `feat(output): group results by system`

### 11.4 — Zip-aware matching
- [x] Done (2026-11-11, DEC-78: the owner chose to match both ways. A zip archive fills a `.zip` target by its contents MD5, worked out
  as Recalbox's `Zip::Md5Composite` does: members' bytes in the order of their names, sorted byte by byte. A member fills any other
  target, through a temporary copy. Differences from this step: the limits are fixed, 1,000 members and 512 MiB unpacked per archive,
  not configurable, by the owner's choice; the archive's own MD5 still fills a `.zip` target as before; `--json` gets `member` fields and
  `beck scan` a `contents_md5`; and `cli.py`, `output/`, the schemas and the docs changed too. Tested with unit tests and on the Samba test
  server. Not tested: a real Recalbox scanning an archive BECK uploaded, and names in Info-ZIP's Unicode path field.)
- **Priority:** planned (2)
- **What:** Users often keep BIOS files inside `.zip` archives. When scanning, also hash the members of `.zip`
  files with the standard library `zipfile`.
  - If a **member** matches, extract that member to a temporary file and upload it under the target name.
  - If the **archive itself** matches (e.g. `neogeo.zip`), keep today's behavior.
  - Guard against zip bombs: limits on member count and uncompressed size, configurable, with clear errors.
  - Other archive formats (`.7z`, `.rar`) would need new dependencies: ask the owner first.
- **Files:** `src/beck/hashing.py`, `src/beck/models.py`, `src/beck/executor.py`, tests
- **Done when:** Tests cover a member match, a whole-archive match, nested folders in the archive, and the limits.
- **Verify:** `uv run pytest -q -k zip`
- **Commit message:** `feat(scan): match BIOS files inside zip archives`

### 11.5 — Multiple sources and filters
- [ ] Done
- **Priority:** later
- **What:** `--source` can be repeated (and `source.dirs` becomes a list in the config). Add `--include` /
  `--exclude` glob filters. Duplicates across sources follow the existing duplicate rule.
- **Files:** `src/beck/cli.py`, `src/beck/config.py`, `src/beck/hashing.py`, tests, docs
- **Done when:** Tests cover two sources with an overlap, and include/exclude filters.
- **Verify:** `uv run pytest -q -k "source or glob"`
- **Commit message:** `feat(scan): support multiple source folders and glob filters`

### 11.12 — Export: copy BIOS files from the target to this machine
- [x] Done (2026-11-11: run on the Recalbox 10.1.1 VM, at the owner's request, over its own Samba, as a guest. The dry run planned 232
  of 3,109 files, left out 2,877, and wrote nothing. The export copied all 232 in 2.9 s, about 44 MB, with exit code 0, and each copy
  has the same path and MD5 as on the VM. The VM's BIOS folder was unchanged: all 3,109 files had the same paths and MD5s before and
  after. A second run copied nothing and kept all 232. Differences from this step: downloads use the existing `read_bytes`, so only
  `list_files` is a new `Transport` operation, and a file is read whole, which means a failed read leaves nothing behind; a target
  that can't be listed stops the run, with exit code 3; and the tick is its own commit, after the run. Not tested: real hardware, a slow
  network with large files (the Samba tests copy an 8 MB file over a local one), and Windows or macOS.)
- **Priority:** planned (1)
- **Requested by the owner (2026-11-05):** a way to get the BIOS files on the target system and copy them to the machine running BECK,
  for example as a backup or to move to another device. It's the opposite direction to `check`. The owner decided how it works
  (DEC-57, DEC-60), so this feature's research and decision sub-steps are done.
- **What:** A read-only command, `beck export DIR`:
  - **What it copies:** every `.rom` or `.bin` file, in any case, anywhere under the target's BIOS root (DEC-60). It keeps the target's
    folder layout under `DIR`. On the Recalbox 10.1.1 VM, that's 232 of the 3,108 files, and about 42 MB.
  - **If the local file exists:** skip it and report it. It never overwrites.
  - **What it never does:** change or delete anything on the target.
  - It supports `--target`, `--target-dir`, `--dry-run` and `--json`. One failed file is recorded and the run continues.
  - New `Transport` operations, on both SMB and local targets, to list files recursively and to download them, with the same path
    checks as uploads. A downloaded file's size is compared with the target's.
  - **pysmb's timeout covers a whole file** (see 04.9), so check it with large files on a slow network.
- **Say what's left out.** The rule doesn't cover every BIOS file (DEC-60): in the real Recalbox 10.1.1 report, 70 of 232 targets aren't
  `.rom` or `.bin`, such as `neogeo.zip`, `atarist/tos.img` and the Amiga `kick*.A500` files. It also copies `.rom` and `.bin` files that
  aren't BIOS files. The command's help and `docs/cli.md` must say so, and its output should say how many other files it left.
- **Legal wording:** this is copying from the user's own device, not downloading from the internet, so it's in line with the project's
  rules. But the README's legal notice and AGENTS.md say BECK never downloads BIOS files, so reword them in the same change.
- **Repository safety:** exported files are real BIOS files. If `DIR` is inside a git repository, warn, and don't count on anything
  but `bios/` being ignored. Tests use random bytes only.
- **Files:** `src/beck/transports/`, `src/beck/cli.py`, `src/beck/output/`, `docs/cli.md`, `docs/schemas/`, `README.md`, `AGENTS.md`, tests
- **Done when:** Unit and Samba integration tests cover a full export, mixed-case extensions, nested folders, other file types left
  alone, a dry run, an existing local file and a failed file, with the target unchanged afterwards. The owner has run it against a device or the VM.
- **Verify:** `uv run pytest -q`, and the integration tests with the Samba test server.
- **Commit message:** `feat(cli): add an export command that copies BIOS files from the target`

## Stage acceptance criteria
- Every chosen feature went through research → decision → implementation → docs, with fixtures from real data.
- No dependency, tool or bundled data was added without a DEC.

## Out of scope
- Anything that downloads BIOS files from the internet, or ships or links to them. That will never be in scope. Copying
  files from the user's own device (11.12) is different.

## Other systems

Support for other systems isn't a step of this stage. Each one is a GitHub issue, for the owner or any contributor to pick up (DEC-77):

| Issue | Was step | What |
|---|---|---|
| [#21](https://github.com/Andredson/BECK/issues/21) | 11.7 | Support Batocera. Blocked by real Batocera data. |
| [#22](https://github.com/Andredson/BECK/issues/22) | 11.8 | Support RetroBat, through the local-folder transport. Blocked by real RetroBat data. |
| [#23](https://github.com/Andredson/BECK/issues/23) | 11.9 | Research RetroPie and Lakka support, and whether they give MD5s. |

## Agent notes
- A new frontend without real reference data is guesswork. If the data isn't there, say so on its issue and
  ask for it through the issue form; don't invent formats.
