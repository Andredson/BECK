# Stage 03 — Critical fixes & data safety

**Status:** Done (2026-11-04) · **Depends on:** 02 · **Branch:** `stage/03-critical-fixes` · **Effort:** M

## Goal
Stop BECK from losing user data, crashing, or uploading files under the wrong name, **without** redesigning it
yet. Each fix lands with a regression test, so the stage 04 refactor has a safety net that pins down the
corrected behavior.

## Why
- Functionality 4/10, error handling 3/10, security & data safety 3/10 ([assessment](00-assessment.md#scorecard)).
- Defects D1–D14 (and D16 as an interim fix) are fixed here. Today the tool deletes files by default, which
  is the most urgent problem (DEC-02).
- Fixing inside the current single file is deliberate. Small, reviewable diffs are safer than rewriting and
  fixing at the same time.

## Decisions applied
DEC-02, DEC-09, DEC-10, DEC-13, DEC-14, DEC-43, DEC-50, DEC-51.

## How tests work in this stage
The legacy script talks to SMB directly. Step 03.3 introduces a small `SmbSession` class (one connection per
run). Tests replace pysmb's `SMBConnection` with an in-memory fake (`tests/fakes.py`) through
`monkeypatch`. **No test touches a real network or a real Recalbox.** Local files use pytest's `tmp_path`.

## Steps

### 03.1 — Fix README commands and add the legal notice (D13, D15)
- [x] Done (2026-11-03: in a fresh clone, the pip route (venv + `pip install -r requirements.txt`, Python 3.11)
  and `uv sync` both worked; the run itself wasn't tried, because it needs a Recalbox and still deletes files.
  Beyond the list below: a **warning** that this version deletes every file in `bios/` (matches after upload,
  non-matches right away) until 03.10; a short *Configuration* section for `config/config.yml`; the report
  prerequisite (`missing_bios_report.txt` on the `bios` share); and a Debian/Ubuntu hint, because
  `python3 -m venv` fails without the `python3-venv` package, which happened on the owner's machine.
  AGENTS.md's README row was updated to match.)
- **What:** Minimal README corrections (the full rewrite is 08.1):
  - Install: `pip install -r requirements.txt`, or `uv sync` for uv users.
  - Run: `python check_bios.py` from the repository root (the file has no shebang; `./bios_bios.py` doesn't exist).
  - Prerequisite: **Python 3.11 or newer**.
  - Fix the structure tree (`README.md`, not `readme.MD`) and typos ("Minimun").
  - Add a **Legal notice**: BECK doesn't include, download or distribute BIOS files; only use dumps of hardware
    you own; never commit BIOS files to this repository.
  - Add a **License** line: "GPL-3.0-only" (DEC-13).
- **Files:** `README.md`
- **Done when:** Every command in the README works on a fresh clone (except the run itself, which needs a Recalbox).
- **Verify:** `grep -q 'requirements.txt' README.md && ! grep -q 'bios_bios' README.md && uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `docs(readme): fix install and run commands, add legal notice`

### 03.2 — Stop tracking the real config (D14)
- [x] Done (2026-11-03: the owner's local `config/config.yml` is kept and now ignored. Checked that the
  missing-config test fails on the old code (`FileNotFoundError`), and that the hygiene script fails if the file
  is tracked again. The README's *Upgrading* steps were rehearsed in throwaway clones, both for a user who had
  edited the file (the pull is refused, then settings survive and `git status` is clean) and for one who hadn't
  (the pull removes it, then the example is copied). `load_configs` got type hints so the strictly typed test can
  call it. AGENTS.md's repo-map row now describes the example file.)
- **What:**
  - Add `config/config.example.yml` with the same keys and empty credentials, and **without** the meaningless
    `version: "3.8"` key.
  - Add `config/config.yml` to `.gitignore`.
  - Remove `config/config.yml` from the index **while keeping the local file**: `git rm --cached
    config/config.yml`, staged as part of this step's commit (DEC-46).
  - `load_configs`: if `config/config.yml` doesn't exist, print "Copy config/config.example.yml to
    config/config.yml and fill it in" and exit 1. Catch `FileNotFoundError` explicitly, not with a bare except.
  - Remove the allow-list entry for `config/config.yml` from `scripts/check_repo_hygiene.py` (added in 02.8).
  - README **Upgrading** note, because pulling this commit affects existing users. If someone edited the
    tracked file, `git pull` refuses to overwrite it. Steps: back up `config/config.yml`, run
    `git checkout -- config/config.yml`, pull, then copy the backup back. It's ignored from now on.
- **Files:** `config/config.example.yml`, `.gitignore`, `check_bios.py`, `scripts/check_repo_hygiene.py`,
  `README.md`, `tests/test_config.py`
- **Done when:** `git ls-files config/` lists only the example; a missing config produces the friendly message.
- **Verify:** `git ls-files config/` prints `config/config.example.yml` only, and `uv run pytest tests/test_config.py -q` passes
- **Commit message:** `fix(config)!: stop tracking config.yml and ship config.example.yml`
  (`!` marks the breaking change for existing users)

### 03.3 — SMB session seam: one connection, in-memory reads, closed handles (D6, D7, D11, D16)
- [x] Done (2026-11-03: 17 tests in `tests/test_smb_session.py`. Each fix was checked by breaking it on purpose
  (file left open, report written to `./test.txt`, session never closed, no direct TCP); a test failed every time.
  The old code makes 4 connections for one BIOS file, so the full-run test fails on it. Beyond the list below:
  - `connect()`'s result is checked, so a refused login is a clear error instead of a later failure.
  - The new methods' error messages are correct ("listing", the folder name, "doesn't"), so part of D12 is done.
  - The `SIM115` ruff ignore was removed too (mapped to 03.3).
  - `load_configs` and `main` got type hints, so the strictly typed tests can call them.
  - The deletion after upload moved from the SMB code into `validate_bios`, unchanged until 03.10. With D7
    fixed, it now also works on Windows, where the old code stopped with an error after the first upload.
  - The test fixture runs every session test in `tmp_path`. AGENTS.md's `tests/` row and Testing section now
    describe the fake.
  **Correction (2026-11-04):** this step introduced a regression, found with the first real report. Real reports use
  CRLF. The old `test.txt` round trip happened to convert it to LF; `read_text` doesn't, so the report reads as 1
  block instead of 238. Step 03.5 fixes it by normalizing line endings, and tests it on the real fixture.)
- **What:** Replace the `smb_connect(share, folder, operation, file)` string switch with a small class in
  `check_bios.py`:
  ```python
  class SmbSession:  # context manager: connects once, checks the share once, always closes
      def __init__(self, server: str, port: int, user: str, password: str, share: str) -> None: ...
      def __enter__(self) -> "SmbSession": ...
      def __exit__(self, *exc: object) -> None: ...  # conn.close()
      def read_text(self, path: str) -> str: ...  # io.BytesIO, decode("utf-8", errors="replace")
      def upload(self, local: Path, remote: str) -> None: ...  # `with open(local, "rb")`
      def list_dirs(self, path: str) -> list[str]: ...
      def make_dir(self, path: str) -> None: ...
  ```
  - D6: no `test.txt`, no temp file. Read into `BytesIO` and decode.
  - D7: the local file is opened in a `with` block, so it's closed before anything else touches it.
  - D11: `main()` opens **one** session and passes it down. The client name is `socket.gethostname()`, falling
    back to `"BECK"` on `OSError`; never `gethostbyname(...)`.
  - D16 (interim): pass `is_direct_tcp=True` when `port == 445`. Verified on a real device in 03.13; the final
    fix is the smbprotocol transport in 04.9 (`pysmb` since DEC-53).
  - Errors raise a `BeckError(message)`; only `main()` prints and exits. Remove `exit()` from the class.
  - `tests/fakes.py`: `FakeSMBConnection` storing files and directories in a dict; it records calls and
    connection count. Tests monkeypatch `check_bios.SMBConnection`.
- **Files:** `check_bios.py`, `tests/fakes.py`, `tests/test_smb_session.py`
- **Done when:** Tests prove that a full run opens exactly one connection and closes it; that reading the report
  creates no file in the working directory (`monkeypatch.chdir(tmp_path)`, then assert the directory is still
  empty); and that `upload` closes the local file before returning (the fake records the file object it was
  given, and the test asserts `closed` is true; CI doesn't run on Windows, DEC-49). The `return`,
  `return-value`, `no-any-return` and `assignment` entries are removed from the mypy legacy override (added in
  02.4), and `uv run mypy` still passes.
- **Verify:** `uv run pytest tests/test_smb_session.py -q`
- **Commit message:** `fix(smb): use one closed-on-exit SMB session and read reports in memory`

### 03.4 — Real report fixtures harness
- [x] Done (2026-11-04: the real report is from Recalbox 10.1.1 on x86_64, in a QEMU VM: 238 entries, CRLF line
  endings. It's stored byte-exact through a `.gitattributes` rule. Nothing needed anonymizing, and the owner kept the
  date line. Five derived fixtures. The expected files came from a one-off script that shares no code with
  `check_bios.py`; the tricky entries were checked, and the owner looked them over and confirmed the menu path
  (main menu → BIOS CHECKING → REPORT). Beyond the list below: `tests/test_fixtures.py`, which fails if the fixtures
  lose their CRLF; `.gitattributes` and `.editorconfig` rules; DEC-50 for entries with two locations.)
- **Blocked by:** The owner provides at least one real `missing_bios_report.txt` from their Recalbox (DEC-09).
- **What:**
  - Layout: `tests/fixtures/reports/recalbox-<version>/<short-name>.txt`, for example
    `recalbox-9.2/default-install.txt`, plus a hand-checked `…/<short-name>.expected.json` listing every
    entry the parser must produce (`name`, `path`, `relativePath`, `hashes`).
  - `tests/fixtures/README.md` with a provenance table: Recalbox version, date, how it was generated (menu path),
    what was anonymized, number of entries.
  - **Anonymize:** remove hostnames, user names or anything personal found in paths or headers. MD5 values and
    BIOS file names are public and stay.
  - **Derived edge-case fixtures:** copy a real report and edit it to add hyphenated names, names with spaces
    and parentheses, nested paths, two entries sharing an MD5, lowercase hashes, and CRLF line endings. Name
    these `derived-<what>.txt` and say in the README that they were derived from which real report.
  - `tests/conftest.py`: `load_report(name) -> str` and `load_expected(name) -> list[dict]`.
- **Files:** `tests/fixtures/**`, `tests/conftest.py`
- **Done when:** At least one real and four derived fixtures exist, each with an expected-output file the owner
  has looked over.
- **Verify:** `uv run python scripts/check_repo_hygiene.py && ls tests/fixtures/reports/*/`
- **Commit message:** `test(fixtures): add anonymized Recalbox missing-BIOS reports`

### 03.5 — Parser: real match strings and full filenames (D2, D10)
- [x] Done (2026-11-04: `parse_report` matches the expected entries for all six fixtures, and the real report reads
  as 238 entries over the fake SMB session again, which fixes the 03.3 regression (the old code fails that test).
  Each rule was checked by breaking it on purpose. Different from the list below: each block runs from its heading to
  the next heading, so it doesn't depend on blank lines or need `match.group(0)`. Added: a first location outside
  `/recalbox/share/bios/` raises `ReportParseError`, so BECK never uploads to an absolute path on the share. `hashs`
  became `hashes`, and the full-run test's report now uses the real format. Still open: nested folders that already
  exist fail until 03.9, and the report's uppercase hashes are matched as they are until 03.6.)
- **Blocked by:** 03.4
- **What:**
  - Split `get_missing_bios` into a **pure** `parse_report(text: str) -> list[dict]` plus a thin wrapper that
    reads the report through the session.
  - Normalize line endings first (`text.replace("\r\n", "\n")`).
  - Iterate with `re.finditer` and use `match.group(0)`; never call `str()` on a tuple (D10).
  - Take the **file name from the `MISSING … BIOS: <name>` line** instead of the first word that looks like a
    file name (D2). This handles `-`, spaces, parentheses and multiple dots. A `Path:` line can list two locations
    (`<path> or <path>`), so its basename isn't reliable; use the **first** location for the folder (DEC-50).
  - Add word boundaries to the MD5 regex (`\b[a-fA-F0-9]{32}\b`) so longer hex strings aren't split into fake hashes.
  - A block without a path or hash raises `ReportParseError` with the block's first line, instead of crashing
    with `AttributeError`.
  - The `/recalbox/share/bios/` prefix becomes a named constant (`RECALBOX_BIOS_ROOT`).
- **Files:** `check_bios.py`, `tests/test_parser.py`
- **Done when:** `parse_report` matches the `.expected.json` for every fixture, parametrized by fixture file. The
  test compares hashes case-insensitively, so it stays valid after 03.6 lowercases them.
  The `union-attr` entry is removed from the mypy legacy override (added in 02.4), and `uv run mypy` still passes.
- **Verify:** `uv run pytest tests/test_parser.py -q`
- **Commit message:** `fix(parser): extract full file names and parse report blocks robustly`

### 03.6 — Normalize MD5 case (D5)
- [x] Done (2026-11-04: `parse_report` and the new `file_md5` both return lowercase, and a full run with a fake
  server uploads the file whether the report's hash is uppercase, lowercase or mixed. Checked by breaking each side
  on purpose. Files are hashed through `file_digest`, so a large file doesn't have to fit in memory. The `S324`
  ignore is gone.)
- **What:** Store and compare every MD5 in **lowercase**, both from the report and from local files. Hash files
  in chunks with `hashlib.file_digest(f, lambda: hashlib.md5(usedforsecurity=False))` (Python 3.11+). This
  also satisfies ruff's `S324`, because MD5 is used to identify files, not for security.
- **Files:** `check_bios.py`, `tests/test_hashing.py`
- **Done when:** An uppercase-hash report matches a local file, and the `S324` ignore from 02.3 is removed.
- **Verify:** `uv run pytest tests/test_hashing.py -q && uv run ruff check .`
- **Commit message:** `fix(hashing): compare MD5 values case-insensitively and hash in chunks`

### 03.7 — Local scanner: skip dotfiles, recurse, no early exit (D1, D8)
- [x] Done (2026-11-04: `validate_bios` now uses each file's relative path, so a BIOS file in a sub-folder is found,
  renamed and uploaded instead of stopping the run. Results are sorted by path, so runs are repeatable. Checked by
  breaking each rule on purpose, and on the old code. Until 03.8, a matched file in a sub-folder is still moved to
  the top of `bios/` before upload, as the rename did before.)
- **What:** `get_possible_bios(folder)`:
  - Walks recursively and **skips hidden files and folders** (names starting with `.`), so `bios/.keep` is
    never hashed or deleted (D1).
  - Records each file's path **relative to the bios folder** and uses it everywhere later (D8).
  - Prints **one** total count. It exits with "No BIOS files found" only when the total is zero, never because
    one sub-folder is empty (D8).
- **Files:** `check_bios.py`, `tests/test_scanner.py`
- **Done when:** Tests with `tmp_path` cover `.keep` being ignored, an empty sub-folder not stopping the scan,
  and a nested file reported with its relative path.
- **Verify:** `uv run pytest tests/test_scanner.py -q`
- **Commit message:** `fix(scanner): ignore hidden files and scan sub-folders without exiting early`

### 03.8 — One local file can satisfy many report entries (D3)
- [x] Done (2026-11-04: checked on the real report: an MD5 shared by `tos.img` and `st.img` uploads to both, and
  `gexpress.pce`, listed under 3 systems, uploads once. Checked by breaking each rule on purpose. Beyond the list
  below: **a target is filled once**, because `tos.img` accepts 65 MD5s and a second different file would overwrite
  the first; the first file by path wins and the other is reported (remote overwrites are decided in 06.5). Counts
  are of distinct targets: the real report has 238 blocks and 232 targets. Duplicates and already-filled files are
  kept, not deleted. Files that were uploaded are still deleted, after all their uploads, until 03.10.)
- **What:** Rewrite `validate_bios` around an index `md5 -> [report entries]`:
  - A local file whose MD5 matches several entries is uploaded **to each target, under each target's name**,
    straight from the original local path. **No local rename** any more; renaming was only a way to upload
    under the right name.
  - If several local files share an MD5, use the first (sorted by relative path) and list the others as
    "duplicate, skipped". This resolves the comment in `main()` that reads "Create a validation for
    duplicated md5sum of files" (line 235 at `d1ad68d`).
  - Entries with the same target appear in real reports (`gexpress.pce` under three systems): upload to each
    target **once**.
  - Count **distinct report entries satisfied**, not loop iterations. The final summary reads
    `entries satisfied / entries missing` and `files analysed`.
- **Files:** `check_bios.py`, `tests/test_matching.py`
- **Done when:** Tests cover two entries with one MD5 (two uploads from one file, count 2), two identical local
  files (one upload, one duplicate notice), and that local file names never change.
- **Verify:** `uv run pytest tests/test_matching.py -q`
- **Commit message:** `fix(matching): upload one file to every matching target without renaming it`

### 03.9 — Recursive remote directory creation (D4)
- [x] Done (2026-11-04: `validate_bios` uses `ensure_dir`, so a nested target works whether none, some or all of its
  folders already exist, as on the real Recalbox, where most do. On the old code, those full runs fail when none or
  all of the folders exist; only the case with just the parent present worked. Checked by
  breaking each rule on purpose. Tested with the fake server only; 03.13 confirms it on a real device.)
- **What:** `SmbSession.ensure_dir("a/b/")` creates each missing segment in order (`a`, then `a/b`), checking
  existence by listing the **parent** folder rather than the share root. Entries at the share root (empty
  relative path) need no directory. Directory-listing errors are reported with the right message ("Error
  listing …", see D12).
- **Files:** `check_bios.py`, `tests/test_smb_session.py`
- **Done when:** With the fake connection, a nested target creates both levels once, an existing level isn't
  recreated, and a root-level target creates nothing.
- **Verify:** `uv run pytest tests/test_smb_session.py -q -k ensure_dir`
- **Commit message:** `fix(smb): create nested remote BIOS folders one level at a time`

### 03.10 — Non-destructive by default (DEC-02)
- [x] Done (2026-11-04: both deletions are gone. The test compares names, sizes, modification times and content
  before and after a full run with a match, a nested match, a duplicate, a second file for a filled target, a file
  with no match and `.keep`; delete and rename calls are also blocked during that run. The old code fails it.
  Different from the list below: the output uses `->`, not `→`, because `→` can crash Python when output is redirected
  on Windows. Beyond the list: a fourth outcome, `target already filled, kept` (from 03.8); the `PTH104`, `PTH107` and
  `PTH118` ignores were removed because nothing uses them now; AGENTS.md's README row and command warning were
  updated.)
- **What:**
  - Remove **both** deletions: local files after upload, and unmatched local files.
  - At the end, print what happened to each file: `copied → <target>`, `duplicate, kept`, or
    `no match, kept`. `--move` and `--clean-unmatched` come in stage 06.
  - Add a README note: "BECK no longer deletes anything in your bios folder."
- **Files:** `check_bios.py`, `README.md`, `tests/test_non_destructive.py`
- **Done when:** A test snapshots the `tmp_path` bios folder (names + sizes + mtimes) before and after a full run
  with the fake session and asserts they're identical.
- **Verify:** `uv run pytest tests/test_non_destructive.py -q`
- **Commit message:** `fix!: never delete local files; copy matched BIOS files only`

### 03.11 — Consistent path resolution (D9)
- [x] Done (2026-11-04: `BASE_DIR`, `CONFIG_PATH` and `BIOS_DIR` replace the mix of working-directory and script paths.
  A full run works from an unrelated working directory and creates nothing there. Checked by breaking each constant
  on purpose. The config file is now read as UTF-8, and the tests share a `use_folder` helper in `tests/conftest.py`.)
- **What:** Define module-level constants once and use them everywhere:
  `BASE_DIR = Path(__file__).resolve().parent`, `CONFIG_PATH = BASE_DIR / "config" / "config.yml"`,
  `BIOS_DIR = BASE_DIR / "bios"`. Use `pathlib` throughout (this also clears the remaining ruff `PTH`
  ignores). Configurable paths come in stages 06 and 07.
- **Files:** `check_bios.py`, `tests/test_paths.py`
- **Done when:** A full run (fake session; constants monkeypatched to `tmp_path`) works after
  `monkeypatch.chdir` to an unrelated directory.
- **Verify:** `uv run pytest tests/test_paths.py -q && uv run ruff check .`
- **Commit message:** `fix(paths): resolve config and bios folders relative to the script`

### 03.12 — Cleanup: messages, imports, exceptions, typos (D12)
- [x] Done (2026-11-04: no ruff ignores or mypy `disable_error_code` entries remain for `check_bios.py`, and the code
  has no bare `except` and exits only in `main()`, which two small AST tests now enforce. `load_configs`,
  `get_missing_bios` and `get_possible_bios` raise or return instead of exiting. Most of the messages, imports and
  typos were already fixed in 03.3–03.10. A malformed YAML file or a missing key inside `smb` still gives a traceback;
  step 07.1 adds full config validation. AGENTS.md no longer mentions the ruff ignores.)
- **What:**
  - Correct the copy-pasted messages (listing vs creating; print the folder, not `file`).
  - Remove `import json` and the unused color constants.
  - Replace bare `except:` with the specific exceptions (`KeyError`/`TypeError` for config, `OSError` for files).
  - Use `sys.exit()` only in `main()`.
  - Fix typos: credentials, doesn't, hashes, items.
  - Remove every remaining per-file ruff ignore added in 02.3, and every remaining mypy `disable_error_code`
    entry added in 02.4.
- **Files:** `check_bios.py`, `pyproject.toml`
- **Done when:** No per-file ruff ignores and no mypy `disable_error_code` entries remain for `check_bios.py`,
  and the whole test suite passes.
- **Verify:** `uv run ruff check . && uv run mypy && uv run pytest -q`
- **Commit message:** `refactor: clean up messages, exceptions and unused code`

### 03.12a — A file named like the target goes first
- [x] Done (2026-11-04: added at the owner's request after the VM run in 03.13, where `falcon.img` sorted first and
  filled `atarist/tos.img`, so the user's real `tos.img` was skipped. Recalbox's report didn't reveal it, because
  `falcon.img`'s MD5 is on that entry's list. Replaying the owner's files against the real report with the fake server
  fills the same 152 targets, and four now hold the file with the right name: `atarist/tos.img`, `dc/dc_boot.bin`,
  `dc/dc_flash.bin` and `Mupen64plus/IPL.n64`. Checked by breaking each rule on purpose.)
- **What:** Each target goes first to a local file with the target's exact name, if that file's MD5 is on the target's
  list. Remaining targets go to the first file by path, as before. Among identical copies, the one named like a target
  is the one uploaded.
- **Files:** `check_bios.py`, `tests/test_matching.py`
- **Done when:** Tests cover a differently named file sorting first, an identical copy sorting first, a file that
  also fits another file's target, and a name that matches but whose MD5 isn't on that target's list.
- **Verify:** `uv run pytest tests/test_matching.py -q`
- **Commit message:** `fix(matching): give each target to the file already named like it`

### 03.13 — End-to-end check on a real Recalbox (human-run)
- [x] Done (2026-11-04: signed off on a **VM, not a real device**, by owner decision (DEC-51): Recalbox 10.1.1 x86_64
  in QEMU, on a Linux host. BECK ran at `d2f2cef`, over the VM's real Samba server, with the owner's 237 files, and
  filled 152 of 232 targets. All 152 matched by MD5 on the VM right after the upload, and the local files were
  unchanged. After a rescan, the report went from 232 to 80 targets, with no new ones. Results for all eight checks
  are in PR #3. Open points:
  - **Not verified:** real hardware, and BECK choosing direct TCP by itself on port 445 (see DEC-51).
  - **Unexplained:** `neocdz.zip` was at the share root right after the upload, but later was in `geolith/` with the
    same timestamp, and the root entry is reported missing again. BECK didn't write there and hadn't run since, so
    something on the VM probably moved it. The owner chose not to investigate.
  - **The report can clear an entry whose hash isn't on its list:** `geolith/neocdz.zip` did, with
    `hashMatchMandatory="false"`, a flag on 82 of the 357 entries in `es_bios.xml`. A rescan doesn't always prove the
    right file is there.
  - **Fix after the run:** the wrong-file problem it found is fixed in 03.12a, which was replayed against the fake
    server, not the VM. No emulator loaded any file.)
- **What:** The agent writes a checklist into the PR description; **the owner runs it** (agents never touch a
  real device without explicit OK):
  1. Record the Recalbox version and the host OS.
  2. On the Recalbox, generate the missing-BIOS report (record the exact menu path for 08.2).
  3. In `bios/`, put: one known-good BIOS under a **different** file name, one that belongs in a **nested**
     folder, one junk file, and keep `.keep`.
  4. Run `uv run python check_bios.py`.
  5. Check on the share that names and folders are correct and nested folders were created.
  6. Check locally that every file, including `.keep` and the junk file, is still there.
  7. Rescan BIOS on the Recalbox; the copied ones should no longer be reported missing.
  8. Confirm the connection works with `is_direct_tcp=True` on port 445 (D16).
- **Files:** none (results go in the PR description)
- **Done when:** The owner confirms all eight checks in the PR.
- **Verify:** Owner sign-off.
- **Commit message:** none

### 03.14 — Close the stage
- [x] Done (2026-11-04: 161 tests pass, and `check_bios.py` has 99 % coverage. The stage scores 5/10, up from 4, and
  D1–D15 are fixed, with D16 interim. Draft PR #3 already exists, so the owner marks it ready and merges it with a merge
  commit.)
- **What:** Update AGENTS.md (repo map: `tests/fakes.py`, fixtures; "the script no longer deletes files").
  Re-score [00-assessment](00-assessment.md#re-scoring-history) and mark D1–D14 fixed (D16 interim). Update the
  [README](README.md#stages) status. Push the closing commit (DEC-47). If the stage PR doesn't exist yet, print
  this command for the human (DEC-43):

  ```sh
  gh pr create --base main --title "Stage 03: critical fixes and data safety" --body "Closes roadmap stage 03."
  ```

- **Files:** `AGENTS.md`, `roadmap/00-assessment.md`, `roadmap/README.md`, this file
- **Done when:** The PR is merged with a merge commit, and 03.13 is signed off.
- **Verify:** `uv run pytest --cov` passes; coverage of `check_bios.py` is reported.
- **Commit message:** `docs(roadmap): close stage 03 and re-score assessment`

## Stage acceptance criteria
- No code path deletes or renames a user's local file.
- Every D1–D14 defect has a regression test that fails on the old code and passes on the new code.
- A full run opens exactly one SMB connection.
- The owner has verified the result end-to-end on a Recalbox VM, accepted in place of a real device (DEC-51).

## Out of scope
- New CLI flags, config format changes, packaging, and the smbprotocol switch (stages 04–07).

## Agent notes
- Keep each step's diff focused. If a fix needs part of a later step, do the smallest piece now and say so in
  the commit body.
- To check that a regression test is real: temporarily revert the fix locally, confirm the test fails, then
  restore the fix. Never commit the reverted state.
