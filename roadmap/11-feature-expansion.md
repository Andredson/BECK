# Stage 11 — Feature expansion

**Status:** Not started · **Depends on:** 10 · **Branch:** one per feature, `feature/<slug>` · **Effort:** L (total)

## Goal
Grow BECK beyond a polished Recalbox tool: fewer manual steps for users, smarter matching, and, through the
adapter interface built in stage 04, support for other retro-gaming frontends (DEC-03).

## Why
- "Idea & usefulness" is BECK's strongest aspect (8/10); this stage builds on it.
- Every feature here depends on facts that can't be known from this repository (device file formats, other
  frontends' reports, licensing of hash lists). So each feature starts with **research and an owner decision**,
  never with code.

## Decisions applied
DEC-03, DEC-04, DEC-09, DEC-14, DEC-22, DEC-43.

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

### 11.1 — Prioritize with the owner
- [ ] Done
- **What:** Present the features below (11.2–11.9 and 11.12) with a one-line value and a cost estimate. Ask the owner to
  choose which ones to pursue and in what order, and to drop or add items. Record the order in this file and
  mark dropped items as such; don't delete them.
- **Files:** this file
- **Done when:** Each feature is marked *planned (n)*, *later* or *dropped*.
- **Verify:** Owner sign-off.
- **Commit message:** `docs(roadmap): prioritize feature expansion with the owner`

### 11.2 — Report-less Recalbox mode
- [ ] Done
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
- **What:** In `beck report` and the `check` summary, group entries by system or folder, showing counts of
  satisfied, still missing (required) and still missing (optional). Add the same grouping to the JSON output as
  a **new field** (allowed within schema v1; see the 06.7 compatibility promise).
- **Files:** `src/beck/output/*`, `docs/schemas/*.json`, tests
- **Done when:** Both the human and JSON outputs show the grouping, and contract tests pass.
- **Verify:** `uv run pytest -q -k "summary or contract"`
- **Commit message:** `feat(output): group results by system`

### 11.4 — Zip-aware matching
- [ ] Done
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
- **What:** `--source` can be repeated (and `source.dirs` becomes a list in the config). Add `--include` /
  `--exclude` glob filters. Duplicates across sources follow the existing duplicate rule.
- **Files:** `src/beck/cli.py`, `src/beck/config.py`, `src/beck/hashing.py`, tests, docs
- **Done when:** Tests cover two sources with an overlap, and include/exclude filters.
- **Verify:** `uv run pytest -q -k "source or glob"`
- **Commit message:** `feat(scan): support multiple source folders and glob filters`

### 11.6 — Hash cache
- [ ] Done
- **What:** For large collections, cache MD5s keyed by `(absolute path, size, mtime_ns)` in a JSON file under
  `platformdirs.user_cache_path("beck")`. Ignore the cache with `--no-cache`. A corrupt cache is discarded
  with a warning. Measure the speed-up and record it in the PR.
- **Files:** `src/beck/hashing.py`, `src/beck/cache.py`, tests
- **Done when:** A second scan of an unchanged folder reads no file content (asserted by a test).
- **Verify:** `uv run pytest -q -k cache`
- **Commit message:** `perf(scan): cache file hashes between runs`

### 11.7 — Batocera adapter
- [ ] Done
- **Blocked by:** real Batocera reference data (a missing-BIOS listing or report, plus the share layout)
  from the owner or a contributor (use the "new frontend" issue form, 12.4).
- **What:** Follow the `add-frontend-adapter` skill: research how Batocera reports missing BIOS files and
  where its BIOS folder is exposed over SMB; write an ADR; implement `frontends/batocera.py`; add fixtures; add
  documentation.
- **Files:** `docs/research/batocera.md`, `docs/adr/*`, `src/beck/frontends/batocera.py`, fixtures, tests, docs
- **Done when:** `beck check --frontend batocera --dry-run` works on fixtures, and a contributor has verified it
  on a device.
- **Verify:** `uv run pytest -q -k batocera`
- **Commit message:** `feat(frontends): add Batocera adapter`

### 11.8 — RetroBat adapter
- [ ] Done
- **Blocked by:** real RetroBat reference data.
- **What:** Same procedure as 11.7. RetroBat runs on Windows, so the **local transport** is the natural target.
- **Files:** `docs/research/retrobat.md`, `docs/adr/*`, `src/beck/frontends/retrobat.py`, fixtures, tests, docs
- **Done when:** It works on fixtures, and a contributor has verified it on a device.
- **Verify:** `uv run pytest -q -k retrobat`
- **Commit message:** `feat(frontends): add RetroBat adapter`

### 11.9 — RetroPie / Lakka feasibility
- [ ] Done
- **What:** These frontends may not produce a missing-BIOS report with MD5s. Research what's available on the
  device. If the only option is an external hash list (e.g. a libretro database), **check its license** and
  present the options to the owner **before** bundling or downloading anything. Bundling data changes BECK's
  "no hash database" property (see the assessment strengths), so it needs a DEC.
- **Files:** `docs/research/retropie-lakka.md`
- **Done when:** There's a written recommendation and an owner decision (implement, defer or drop).
- **Verify:** Owner sign-off.
- **Commit message:** `docs(research): assess RetroPie and Lakka support`

### 11.10 — Optional: translations
- [ ] Done
- **What:** If the owner wants it, translate user-facing messages, starting with pt-BR, fr and es. Ask the
  owner to choose the mechanism (e.g. stdlib `gettext` with `.po` files, or a simple message catalog in
  Python), with the trade-offs, and record a DEC. JSON output and log messages stay in English: they're an
  interface, not prose.
- **Files:** depends on the decision
- **Done when:** The owner decides; if implemented, messages switch with the locale and a test covers one
  translated message per language.
- **Verify:** depends on the decision
- **Commit message:** `feat(i18n): translate user-facing messages`

### 11.11 — Deferred: SSH/SFTP transport
- [ ] Done
- **What:** Deferred by DEC-04. Revisit only if the owner asks or users request it. It would need a new
  dependency (e.g. paramiko or asyncssh) and a DEC. Leave this box unchecked until then; it doesn't block
  closing the stage.
- **Files:** none
- **Done when:** The owner decides to implement it (then expand this step) or confirms it stays deferred.
- **Verify:** Owner decision recorded.
- **Commit message:** none

### 11.12 — Export: copy BIOS files from the target to this machine
- [ ] Done
- **Requested by the owner (2026-11-05):** a flag that gets all the BIOS files on the target system and copies them to the machine
  running BECK, for example as a backup or to move to another device. It's the opposite direction to `check`.
- **Research first:**
  - **What counts as a BIOS file?** The report can't tell, because it only lists what's missing. On the Recalbox 10.1.1 VM, the `bios`
    share has 3,108 files (317 MB), mostly `.ini`, `.png` and shaders, with about 230 `.rom` and `.bin` files. Options to present:
    everything on the share, which is simple and complete; only what's listed in Recalbox's `es_bios.xml`, if it can be read (see
    11.2), which is exact; or filters by name.
  - **Which hashes can it verify?** Each copy can at least be compared with the device by size, and by MD5 if it's read back.
- **Decide with the owner, and record a DEC:**
  - **A flag or a command?** The owner asked for a flag. The design in `docs/cli.md` has `check`, which uploads, so `beck check --export DIR`
    would make one command do opposite things; a `beck export` command would fit that design better. Present both.
  - **Where do the files go, and how are they laid out?** Presumably a required `DIR`, keeping the target's folder layout.
  - **What if a local file already exists?** Presumably never overwrite it by default (DEC-02), and report it.
- **What:** New `Transport` operations, on both SMB and local targets, to list files recursively and to download them, with the same
  path checks as uploads. Export only reads from the target, and never changes or deletes anything there. It supports `--dry-run`
  and `--json`. One failed file is recorded and the run continues. **pysmb's timeout covers a whole file** (see 04.9), so check it with
  large files on a slow network.
- **Legal wording:** this is copying from the user's own device, not downloading from the internet, so it's in line with the project's
  rules. But the README's legal notice and AGENTS.md say BECK never downloads BIOS files, so reword them in the same change.
- **Repository safety:** exported files are real BIOS files. If `DIR` is inside a git repository, warn, and don't count on anything
  but `bios/` being ignored. Tests use random bytes only.
- **Files:** `src/beck/transports/`, `src/beck/cli.py`, `src/beck/output/`, `docs/cli.md`, `docs/schemas/`, `README.md`, `AGENTS.md`, tests
- **Done when:** Unit and Samba integration tests cover a full export, nested folders, a dry run, an existing local file and a failed
  file, with the target unchanged afterwards. The owner has run it against a device or the VM.
- **Verify:** `uv run pytest -q`, and the integration tests with the Samba test server.
- **Commit message:** `feat(cli): export BIOS files from the target to this machine`

## Stage acceptance criteria
- Every chosen feature went through research → decision → implementation → docs, with fixtures from real data.
- No dependency, tool or bundled data was added without a DEC.

## Out of scope
- Anything that downloads BIOS files from the internet, or ships or links to them. That will never be in scope. Copying
  files from the user's own device (11.12) is different.

## Agent notes
- A new frontend without real reference data is guesswork. If the data isn't there, mark the step BLOCKED
  and ask for it through the issue form; don't invent formats.
