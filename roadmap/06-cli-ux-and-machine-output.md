# Stage 06 — CLI, UX & machine-readable output

**Status:** In progress · **Depends on:** 05 · **Branch:** `stage/06-cli` · **Effort:** M

## Goal
Give BECK a real command-line interface (subcommands, flags, help) that is safe by default and pleasant for
humans. Add a **versioned JSON output with stable exit codes** so that scripts and any AI agent can drive it
reliably (DEC-05, DEC-23).

## Why
- UX/CLI scored 4/10: no arguments, no dry run, no way to choose source or target.
- Machine-readable output is the most vendor-neutral form of AI-agent support: it works with every agent,
  script and CI system, and needs no integration code.
- The opt-in destructive flags promised by DEC-02 live here.

## Decisions applied
DEC-01, DEC-02, DEC-04, DEC-05, DEC-17, DEC-23, DEC-36, DEC-54.

## Command-line design (reference for all steps)

```text
beck [--version] [-v | -q] [--no-color] [--json] <command> [options]

beck check   [--source DIR] [--target URL | --target-dir DIR] [--frontend recalbox]
             [--report-file FILE] [--dry-run] [--move] [--clean-unmatched] [--yes]
             [--fail-if-missing]
beck scan    [--source DIR]                         # hash local files only, no network
beck report  [--target URL | --target-dir DIR | --report-file FILE]
                                                    # parse and list missing BIOS, no upload
beck config  init | show | path                     # added in stage 07
```

- `--target smb://[user@]host[:port]/share[/sub/path]`. A password inside the URL is **rejected** with a
  usage error pointing to `BECK_SMB_PASSWORD` or the prompt (stage 07).
- `--target-dir DIR` uses the local transport: a mounted SD card or USB drive, or running on the device.
- Defaults (until stage 07 adds config precedence): source `./bios`, target from the legacy config file.

### Exit codes (stable contract, DEC-23)

| Code | Meaning |
|---|---|
| 0 | The run completed. BIOS files may still be missing unless `--fail-if-missing` is used. |
| 1 | Unexpected internal error (a bug, please report it). |
| 2 | Usage or configuration error (bad flag, bad URL, invalid config, refused confirmation). |
| 3 | Transport error: couldn't connect or authenticate, or at least one upload failed. |
| 4 | Report error: the missing-BIOS report wasn't found or couldn't be parsed. |
| 5 | `--fail-if-missing` was given and required BIOS files are still missing after the run. |

## Steps

### 06.1 — CLI design document
- [x] Done (2026-11-05: the document says at the top that it's a design still being built. Beyond the design block above, it records:
  a file valid for an `INCORRECT` target is never deleted; a warning that `--clean-unmatched` deletes good files after a rescan; a
  required `INCORRECT` file counts for `--fail-if-missing`; a transport error beats `--fail-if-missing`; an unreadable local file doesn't
  change the exit code. The owner confirmed these (DEC-59). Step 06.5's premise was corrected.)
- **What:** `docs/cli.md`, the hand-written user reference: the design block and exit-code table above, one
  example per command, and the safety semantics (what each destructive flag deletes and when it asks for
  confirmation). Add `docs/adr/0007-cli-contract.md` describing the exit codes and the JSON compatibility
  promise (06.7).
- **Files:** `docs/cli.md`, `docs/adr/0007-cli-contract.md`
- **Done when:** The document covers every command and flag implemented in this stage.
- **Verify:** `uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `docs(cli): specify commands, flags and exit codes`

### 06.2 — Subcommand skeleton with argparse
- [x] Done (2026-11-05: `check` runs as before, and `scan` and `report` say they aren't available until 06.11, with exit 2. Different
  from the list below: global options go through a helper rather than one parent parser, because argparse would overwrite an option
  given before the command with the command's default. Only `--no-color` exists so far, moved up from 06.10 to prove that this works;
  `--json`, `-v` and `-q` come in their own steps, because accepting a flag that does nothing would mislead. `check_bios.py` runs
  `beck check`, so it shows only its own notice. Checked by breaking each rule on purpose.)
- **What:** Build the parser in `cli.py` with `argparse` subparsers. Global options go on a parent parser so they
  work before or after the subcommand. `--version` prints `beck <version>`. Help text includes examples
  (`epilog` with `RawDescriptionHelpFormatter`). Bare `beck` with no command keeps working as `beck check` for
  one release and prints a hint. A deprecation note goes into `docs/cli.md`.
- **Files:** `src/beck/cli.py`, `tests/unit/test_cli.py`
- **Done when:** `beck --help`, `beck check --help`, `beck scan --help` and `beck report --help` all render, and
  unknown flags exit 2.
- **Verify:** `uv run beck --help && uv run beck check --help && uv run pytest tests/unit/test_cli.py -q`
- **Commit message:** `feat(cli): add check, scan and report subcommands`

### 06.2a — A local file BECK can't read doesn't stop the run
- [x] Done (2026-11-05: `scan` now returns a `ScanResult` with the files and what it couldn't read. Beyond the list below: **a sub-folder
  that can't be read** is reported too, because `os.walk` skipped those silently, so all its files just went missing. A symlink loop is
  reported like a broken symlink. A symlink to a folder still isn't followed, as before. The local files stay as they were. Tested with
  real symlinks, permissions and named pipes, and through a real Samba server. Checked by breaking each rule on purpose.)
- **What:** Today, a broken symlink or an unreadable file in the source folder ends in a traceback and exit 1, before anything
  is uploaded (found in 04.6, and the reason error handling stayed at 7/10). `hashing.scan` records the file and its reason,
  and carries on with the others. Only regular files, or symlinks to them, get hashed, because opening a named pipe would hang
  forever. `check` and `scan` print one line per such file, and it's an item in the JSON `errors[]` (06.7). The exit code stays
  0, unless another rule in the table applies: the run completed, and the file couldn't have been matched anyway.
- **Files:** `src/beck/hashing.py`, `src/beck/models.py`, `src/beck/cli.py`, `src/beck/output/console.py`,
  `tests/unit/test_hashing.py`, `tests/unit/test_cli.py`
- **Done when:** Tests cover a broken symlink, a file with no read permission and a named pipe, each beside a good file that still
  uploads, with no traceback.
- **Verify:** `uv run pytest tests/unit/test_hashing.py tests/unit/test_cli.py -q`
- **Commit message:** `fix(hashing): report unreadable local files and keep going`

### 06.3 — Target selection and frontend flag
- [x] Done (2026-11-05: Beyond the list below: `SmbTransport` takes a root folder, because a target like `smb://recalbox/share/bios` is
  real; checked read-only against the VM. With `--target`, **the password in `config.yml` isn't used**, because it would go to whatever
  host the flag names, so `--target` means guest until 07.4 adds passwords for targets. A query, a fragment, `..` and backslashes are
  refused, in encoded forms too, and errors never repeat the URL. Checked by breaking each rule on purpose.)
- **What:** Parse `--target` URLs into an SMB target (`host`, `port` defaulting to 445, `share`, optional
  sub-path, optional user) and reject passwords inside URLs. `--target-dir` builds a `LocalTransport`; it is
  mutually exclusive with `--target`. `--frontend` chooses from the adapter registry (only `recalbox` for now).
- **Files:** `src/beck/cli.py`, `src/beck/targets.py`, `tests/unit/test_targets.py`
- **Done when:** Tests cover valid URLs (with and without port, user, sub-path), a URL with a password
  (exit 2 and a helpful message), both target flags given together (exit 2), and an unknown frontend (exit 2,
  lists the known ones).
- **Verify:** `uv run pytest tests/unit/test_targets.py -q`
- **Commit message:** `feat(cli): select SMB or local targets and the frontend adapter`

### 06.4 — Source folder and offline report options
- [x] Done (2026-11-05: `beck report` was built here, grouped by folder with required and optional markers, because this step's check
  needs it; 06.11 keeps `scan`. Beyond the list below: a `--source` that doesn't exist exits with 2, because treating a typo as an empty
  folder would say "No BIOS files found" and exit 0; the default `./bios` still works as before. On `report`, `--report-file` can't be
  combined with a target. Checked by breaking each rule on purpose.)
- **What:** `--source DIR` (default `./bios`) for `check` and `scan`. `--report-file FILE` makes `check` and
  `report` parse a local copy of the report instead of reading it through the transport. That's useful offline,
  for bug reports, and for agents.
- **Files:** `src/beck/cli.py`, `tests/unit/test_cli.py`
- **Done when:** `beck report --report-file tests/fixtures/...` lists entries with no network access.
- **Verify:** `uv run beck report --report-file "$(ls tests/fixtures/reports/*/*.txt | head -n1)"`
- **Commit message:** `feat(cli): add --source and offline --report-file options`

### 06.5 — Owner decision: remote files that already exist
- [x] Done (2026-11-05: the owner chose option 2, and that `--overwrite` also replaces `INCORRECT` files (DEC-61). The executor checks the
  target, because the matcher does no I/O, and a dry run checks it too, which is read-only. Beyond the list below: `--overwrite` reports
  `replaced`, not `copied`. On SMB, `exists` and `makedirs` ignore case, because Samba treats `A.BIN` and `a.bin` as one file, so the check
  would otherwise miss a file the upload then overwrites. Tested against a real Samba server. Checked by breaking each rule on purpose.)
- **What:** If the target path already exists on the device, BECK overwrites it silently today. **Corrected in 06.1:** Recalbox's
  source shows that a bad dump is reported as `INCORRECT` (DEC-54), or not at all when `hashMatchMandatory` is false, while `MISSING`
  means the file wasn't found. So a `MISSING` entry whose file exists mostly means **the report is out of date**, and the file may be
  fine. Ask the owner, explaining the trade-offs, which default to adopt. Files the report lists as `INCORRECT` are kept for now (DEC-54); include whether a flag can
  replace them:
  1. overwrite (current behavior);
  2. skip and report, with an `--overwrite` flag;
  3. rename the existing file to `<name>.beck-backup-<timestamp>`, then upload;
  4. skip by default and offer `--overwrite` and `--backup` flags.

  Record the answer as the next free `DEC-NN` in the [decision log](README.md#decision-log), then implement it
  in the executor with tests.
- **Files:** `roadmap/README.md`, `src/beck/executor.py`, `src/beck/cli.py`, `tests/unit/test_executor.py`
- **Done when:** The chosen policy is recorded, implemented, tested and documented in `docs/cli.md`.
- **Verify:** `uv run pytest tests/unit/test_executor.py -q -k existing`
- **Commit message:** `feat(executor): apply the agreed policy for existing remote files`

### 06.6 — Safety flags: `--dry-run`, `--move`, `--clean-unmatched`, `--yes`
- [x] Done (2026-11-05: a read-only preview decides what would go, and the prompt or refusal comes **before any upload**, so answering no
  changes nothing on either side. Beyond the list below, all erring towards keeping files: `--move` keeps a file with a target that was
  already on the device, because nothing proves that copy is good; `--clean-unmatched` deletes nothing after any failure in the run, or
  when the report lists nothing missing; a file that can't be deleted is recorded and exits with 3. A test checks on the source that only
  `executor.py` deletes and nothing renames. Prompts go to stderr. The DEC-56 warning appears in the dry run and the prompt. Tested with
  real files, and through a real Samba server. Checked by breaking each rule on purpose.)
- **What:**
  - `--dry-run`: build and show the full plan, including what *would* be deleted, and change nothing.
  - `--move`: after a file has been uploaded to **all** of its targets **and** each remote size matches, delete
    the local source. Nothing is deleted if any upload of that file failed.
  - `--clean-unmatched`: delete local files that matched nothing. Duplicates are kept and reported, and so is a file valid for an
    `INCORRECT` target. After an upload and a rescan, good files no longer match anything, so the plan must make that plain (DEC-56).
  - Confirmation: when `--move` or `--clean-unmatched` would delete files, list them and ask `Delete N files?
    [y/N]` on a TTY. Without a TTY (scripts, agents, CI), deletion requires `--yes`; otherwise exit 2 with a
    message explaining that. `--json` implies no prompt, so it also requires `--yes`.
  - Deletions are recorded in the result (`deleted` list).
- **Files:** `src/beck/executor.py`, `src/beck/cli.py`, `tests/unit/test_safety_flags.py`
- **Done when:** Tests cover a dry run with the move and clean flags (nothing deleted, plan lists them), a file valid for an
  `INCORRECT` target kept, move after success, no move after a partial failure, refusal without `--yes` off-TTY, and acceptance with `--yes`.
- **Verify:** `uv run pytest tests/unit/test_safety_flags.py -q`
- **Commit message:** `feat(cli): add dry-run and opt-in move/clean flags with confirmation`

### 06.6a — Warn when a file's extension differs from its target's
- [x] Done
- **What:** Warn when a file is uploaded to a target with a different extension, without blocking the upload. Reason:
  in the real report from Recalbox 10.1.1, an MD5 on the `neocdz.zip` entry also belongs to `neocd.bin`, so BECK
  uploaded a raw `.bin` under a `.zip` name during the 03.13 VM run. The MD5 is valid, but an emulator may not be able
  to read the file. Show the warning in the normal output and in the file's `uploads[]` item in JSON (06.7).
- **Files:** `src/beck/executor.py`, `src/beck/output/`, `tests/unit/test_executor.py`
- **Done when:** A test covers `neocd.bin` going to `neocdz.zip` (warning, still uploaded) and a renamed file with the
  same extension (no warning).
- **Verify:** `uv run pytest tests/unit/test_executor.py -q -k extension`
- **Commit message:** `feat(executor): warn when an upload changes the file extension`

### 06.7 — JSON output and schema v1 (DEC-23)
- [x] Done
- **What:**
  - `output/json.py` renders a `RunResult` (or an error) as a single JSON document on **stdout**. All logs and
    prompts go to stderr, so stdout is always parseable.
  - Top-level fields: `schema_version` (1), `beck_version`, `command`, `ok` (bool), `dry_run`, `frontend`,
    `target` (URL **without** credentials), `summary` {`missing_entries`, `satisfied`, `still_missing`,
    `files_scanned`, `uploaded`, `duplicates`, `unmatched`, `deleted`, `errors`}, `uploads[]` {`source`,
    `target`, `md5`, `status`: planned|uploaded|replaced|kept|failed|skipped, `error`, `warning`}, `incorrect[]` {`name`, `target`, `current_md5`, `md5s`}, `still_missing[]` {`name`, `target`,
    `md5s`, `required`}, `duplicates[]`, `unmatched[]`, `deleted[]`, `errors[]` {`code`, `message`, `item`}.
  - Errors that stop a run (config, connection, report) still print a valid document with `ok: false` and the
    matching exit code.
  - `docs/schemas/check-result.v1.json` (JSON Schema draft 2020-12) describes `check`, plus small schemas for
    `scan` and `report` (`scan-result.v1.json`, `report-result.v1.json`).
  - **Compatibility promise** (in `docs/json-output.md`): within `schema_version` 1, fields are only *added*;
    renaming, removing or changing the meaning of a field means `schema_version` 2. Consumers must ignore
    unknown fields.
  - Added while building it, so that JSON never knows less than the human output: `uploads[].replaces`, `already_filled[]`,
    `unreadable[]`, and `required` on `incorrect[]`. A command line that can't be parsed gives a smaller document, with its own schema
    (`rejected-command.v1.json`). [ADR-0007](../docs/adr/0007-cli-contract.md#details-settled-in-step-067) has the reasons.
- **Files:** `src/beck/output/json.py`, `docs/schemas/*.json`, `docs/json-output.md`, `src/beck/cli.py`
- **Done when:** `--json` works for `check`, `scan` and `report`, including error cases.
- **Verify:** `uv run beck --json report --report-file "$(ls tests/fixtures/reports/*/*.txt | head -n1)" | python3 -m json.tool`
- **Commit message:** `feat(output): add versioned JSON output for all commands`

### 06.7a — Fix two bugs in the human output (D18, D19)
- [x] Done
- **What:** Step 06.7's end-to-end runs found two bugs from before it. `--json` has neither.
  - **D18, a crash after the work is done:** a local file name that isn't valid UTF-8, common in old ROM sets, makes `print` raise
    `UnicodeEncodeError` while BECK shows the results, because the name holds a character stdout can't encode. Reproduced with
    `--move --yes`: BECK uploaded a file and deleted the local copy, then exited with 1, losing the summary and the reminder to scan. The
    same applies to any name a stdout that isn't UTF-8 can't show. Human output must show such a name escaped, like `x\xff.bin`, and carry
    on, wherever it prints a path: results, unreadable files, errors and the deletion prompt.
  - **D19, a wrong line in a dry run:** when checking a target fails, the output says `a.bin: would copy -> a.bin` right above the error,
    although BECK doesn't know that. It must say `failed`, as the JSON's `status` does.
- **Files:** `src/beck/output/__init__.py`, `src/beck/output/console.py`, `src/beck/output/json.py`, `tests/unit/test_console.py`,
  `tests/unit/test_cli.py`, `tests/integration/test_smb_transport.py`, `docs/cli.md`, `docs/json-output.md`, `docs/ARCHITECTURE.md`,
  `roadmap/00-assessment.md`
- **Done when:** A full run with a name that isn't valid UTF-8 exits with 0, prints the summary and uploads the rest; a stdout that can
  only encode ASCII doesn't crash on a name like `é.bin`; the prompt shows such a name; and a dry run with a failed check prints `failed`,
  not `would copy`. D18 and D19 are marked as fixed.
- **Verify:** `uv run pytest tests/unit/test_console.py tests/unit/test_cli.py -q -k "utf8 or encode or failed_check"`
- **Commit message:** `fix(output): show undecodable file names and failed dry-run checks correctly`

### 06.8 — JSON contract tests
- [ ] Done
- **What:** `uv add --dev jsonschema` (dev-only, DEC-23). Tests run every command in success **and** error
  scenarios with `--json` and validate the output against the schema files. Another test fails if a field
  present in the v1 schema disappears, which guards the compatibility promise.
- **Files:** `pyproject.toml`, `uv.lock`, `tests/unit/test_json_contract.py`
- **Done when:** Every JSON-producing path is validated against its schema.
- **Verify:** `uv run pytest tests/unit/test_json_contract.py -q`
- **Commit message:** `test(output): validate JSON output against the published schemas`

### 06.9 — Exit codes and `--fail-if-missing`
- [ ] Done
- **What:** Implement the exit-code table exactly as documented. `--fail-if-missing` returns 5 when any entry
  with `required` true (or unknown) is still missing after the run. An item-level upload failure returns 3 even
  though the run continued. With `--json`, `ok` must be false for 5 too, since the guide says it's false for any exit code but 0.
- **Files:** `src/beck/cli.py`, `tests/unit/test_cli.py`
- **Done when:** Each code 0–5 is produced by at least one test.
- **Verify:** `uv run pytest tests/unit/test_cli.py -q -k exit`
- **Commit message:** `feat(cli): return documented exit codes and support --fail-if-missing`

### 06.10 — Verbosity, logging and color flags
- [ ] Done
- **What:** `-v` sets debug logs on stderr (connection steps, timings, plan details; **never** credentials).
  `-q` prints only errors and the final summary. `--no-color` already exists (06.2). Hashing many files
  shows a simple progress counter on stderr, on a TTY only.
- **Files:** `src/beck/cli.py`, `src/beck/output/console.py`, `tests/unit/test_console.py`
- **Done when:** Tests check that `-v` output never contains the configured password (use a sentinel value).
- **Verify:** `uv run pytest tests/unit/test_console.py -q`
- **Commit message:** `feat(cli): add verbosity and color controls`

### 06.11 — `beck scan` and `beck report`
- [ ] Done
- **What:** `scan` lists local files with relative path, size and MD5, for people too (06.7 built only `--json`). `report` already lists missing entries, grouped
  by folder, with the `required` / optional marker (06.4). Both support `--json`. Neither ever writes anything.
- **Files:** `src/beck/cli.py`, `tests/unit/test_cli.py`
- **Done when:** Both commands work offline (`scan`, and `report --report-file`) and are covered by tests.
- **Verify:** `uv run beck scan --source tests && uv run beck --json scan --source tests | python3 -m json.tool`
- **Commit message:** `feat(cli): add read-only scan and report commands`

### 06.12 — Agent guidance for driving BECK
- [ ] Done
- **What:** Add a **"Using BECK as a tool"** section to AGENTS.md:
  - always run `beck --json check --dry-run …` first and show the plan to the human;
  - parse stdout as JSON and branch on the exit code;
  - never add `--yes`, `--overwrite`, `--move` or `--clean-unmatched` without the human's explicit approval in this session;
  - never pass passwords on the command line.

  Link `docs/json-output.md` and `docs/cli.md`.
- **Files:** `AGENTS.md`
- **Done when:** The rules are in AGENTS.md and link to the schema docs.
- **Verify:** `uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `docs(agents): explain how agents should drive the beck CLI safely`

### 06.13 — Close the stage
- [ ] Done
- **What:** Update the README usage section briefly (the full rewrite is 08.1). Re-score
  [00-assessment](00-assessment.md#re-scoring-history): UX and AI-readiness should rise. Update the
  [README](README.md#stages) status. Push the closing commit (DEC-47). If the stage PR doesn't exist yet, print
  this command for the human (DEC-43):

  ```sh
  gh pr create --base main --title "Stage 06: CLI, UX and machine-readable output" --body "Closes roadmap stage 06."
  ```

- **Files:** `README.md`, `roadmap/00-assessment.md`, `roadmap/README.md`, this file
- **Done when:** The PR is merged with a merge commit.
- **Verify:** The full check suite in AGENTS.md passes.
- **Commit message:** `docs(roadmap): close stage 06 and re-score assessment`

## Stage acceptance criteria
- Destructive actions are impossible without an explicit flag, and impossible off-TTY without `--yes`.
- Every command has `--json` output validated against a published schema; exit codes match the table.
- A dry run never changes anything, locally or remotely.

## Out of scope
- Config files, env vars and credential prompts (stage 07). Agent Skills (stage 09).

## Agent notes
- The JSON schema is a public contract. Before changing an existing field, stop and ask the owner. The answer
  will usually be a `schema_version` bump.
