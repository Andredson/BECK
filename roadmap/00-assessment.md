# Stage 00 — Assessment (baseline)

**Status:** Done · **Date:** 2026-11-02 · **Commit reviewed:** `d1ad68d` (main)

This is the baseline review that the rest of the roadmap is built on. Re-score this file at the end of every
stage (see [Re-scoring history](#re-scoring-history)).

## What was reviewed

| File | Notes |
|---|---|
| `check_bios.py` | 243 lines. Everything lives here: SMB access, report parsing, hashing, matching, renaming, upload, console output. |
| `config/config.yml` | SMB settings (`user`, `passwd`, `server`, `port`) plus an unused `version: "3.8"` key. **Tracked by git.** |
| `requirements.txt` | `pysmb==1.2.9.1`, `PyYAML==6.0.1`. No dev dependencies, no lockfile. |
| `README.md` | 35 lines: purpose, prerequisites, structure, usage, "Recalbox 9.1". |
| `LICENSE` | Full GNU GPL v3 text; no notice saying "version 3 only" or "or later". |
| `.gitignore` | Ignores `bios/*` except `bios/.keep`. |
| `bios/.keep` | Placeholder that keeps the input folder in git. |
| Git history | 11 commits (2023-12-31 → 2025-07-21), single author, no tags or releases. |

How it works today: it downloads `missing_bios_report.txt` from the Recalbox `bios` SMB share, extracts
missing BIOS entries with regexes, hashes every file in `./bios`, renames matches to the expected name, uploads
them into the right sub-folder over SMB, **deletes the uploaded file locally**, and **deletes every file that
didn't match**.

## Scoring method

- **0**: absent. **3**: present but fragile or wrong in important ways. **5**: works, with notable gaps.
  **8**: solid and conventional. **10**: exemplary.
- Overall = unweighted mean of the 19 aspects, rounded.
- **Target** is what the roadmap aims for after stage 10 (1.0), and **Raised by** lists the stages that move the score.

## Scorecard

| # | Aspect | Score | Evidence | Target | Raised by |
|---|---|---|---|---|---|
| 1 | Idea & usefulness | **8** | Real pain point for Recalbox users. Matching by MD5 and placing files in the right folder is exactly what users need. | 9 | 11 |
| 2 | Functionality / correctness | **4** | The happy path works, but several real bugs (D1–D5, D8, D10) produce wrong names, crashes, or deleted files. | 9 | 03, 04, 05 |
| 3 | Code quality & readability | **3** | Unused imports and constants, the variable `f` reused for four different things, typos, an `operation` string switch. | 8 | 02, 03, 04 |
| 4 | Architecture & modularity | **2** | One file mixing I/O, parsing, network and UI; `exit()` inside every function; no seams for tests. | 8 | 04 |
| 5 | Error handling & robustness | **3** | Bare `except:` (lines 31, 225); `.group()` on possible `None`; uncaught `socket.gaierror`; a single failure aborts the run. | 8 | 03, 04, 06 |
| 6 | Security & data safety | **3** | Deletes user files without asking; plaintext credentials in a tracked file; overwrites and deletes `./test.txt`. | 8 | 03, 07 |
| 7 | Testing | **0** | No tests of any kind. | 8 | 02, 03, 05 |
| 8 | Documentation | **3** | Wrong install and run commands; doesn't explain how to generate the report; no legal note about BIOS files. | 8 | 03, 08 |
| 9 | UX / CLI | **4** | Colored output and a final summary are nice. No arguments, no dry-run, no `NO_COLOR`, must be run from the repo root. | 8 | 06 |
| 10 | Configuration | **3** | Hard-coded share (`bios`), paths (`/recalbox/share/bios/`), and config location; no validation or env overrides. | 8 | 03, 07 |
| 11 | Performance | **5** | Fine for a handful of files, but opens a new SMB connection (plus `listShares`) for every operation and never closes them. | 7 | 03, 04 |
| 12 | Portability | **4** | Uploading leaves the file handle open before `os.remove`, which fails on Windows; paths mix CWD and `__file__`. | 8 | 02, 03, 04 |
| 13 | Dependency management | **5** | Minimal and pinned, but no lockfile, no dev dependencies, and the PyYAML pin is behind. | 8 | 02, 07 |
| 14 | Packaging & distribution | **1** | No `pyproject.toml`, entry point, shebang or exec bit; the README tells users to run a file that doesn't exist. | 9 | 04, 10 |
| 15 | CI/CD & automation | **0** | None. | 9 | 02, 10 |
| 16 | Git hygiene & versioning | **5** | Clear commit messages and clean history, but no tags, releases or changelog. | 8 | 02, 08, 10 |
| 17 | Licensing & legal | **6** | GPLv3 text present. Missing: version notice, SPDX metadata, and a disclaimer that users must own their BIOS dumps. | 9 | 03, 08, 10 |
| 18 | Community & governance | **1** | No CONTRIBUTING, templates, security policy or code of conduct. | 7 | 01, 07, 12 |
| 19 | AI-agent readiness | **0** | No agent instructions, no machine-readable output, no skills. | 9 | 01, 06, 09 |
| — | **Overall** | **3 / 10** | Sum 60 / 19 = 3.2. A useful idea at prototype-level quality. | **≈ 8 / 10** | all |

## Strengths worth keeping

- Matching by **MD5 against the report Recalbox itself generates** is the right approach: no bundled hash
  database and no licensing questions.
- It puts files in the right **sub-folder** for each system, which many users get wrong by hand.
- The **final summary** (`found / analysed`) and colored output are friendly.
- **Small dependency footprint** and a clear GPL license.
- `.gitignore` already keeps users' BIOS files out of the repository.

## Defects

Line numbers refer to `check_bios.py` at `d1ad68d`.

**Status after stage 03 (2026-11-04):** D1–D15 are fixed. D4 and D11 get their final form in step 04.9. D16 has its
interim fix: BECK sets `is_direct_tcp` on port 445. A Recalbox 10.1.1 VM accepted both NetBIOS and forced direct TCP,
so the suspected failure wasn't seen there; BECK's own choice on port 445 wasn't run against a device (DEC-51), and the
final fix is 04.9.

| ID | Defect | Where | Impact | Fixed in |
|---|---|---|---|---|
| D1 | `bios/.keep` is hashed as a "possible BIOS". It never matches, so it gets **deleted**. | `get_possible_bios`, 221-227 | Deletes a tracked file and shows a wrong file count. | [03.7](03-critical-fixes-and-data-safety.md#037--local-scanner-skip-dotfiles-recurse-no-early-exit-d1-d8) |
| D2 | The filename regex `[a-zA-Z0-9_]+\.[a-zA-Z0-9]+` truncates names containing `-`, spaces or parentheses (`scph-1001.bin` → `1001.bin`). | 141, 154 | Uploads under the **wrong name**, so Recalbox still reports it missing. | [03.5](03-critical-fixes-and-data-safety.md#035--parser-real-match-strings-and-full-filenames-d2-d10) |
| D3 | When two report entries share an MD5, the first match renames, uploads and deletes the local file. The second match then fails on `os.rename`/`open` and calls `exit(1)`. Found files are also counted twice. | 192-219 | Crash mid-run, partial upload, wrong totals. | [03.8](03-critical-fixes-and-data-safety.md#038--one-local-file-can-satisfy-many-report-entries-d3), final in [04.10](04-architecture-refactor.md#0410--pure-matcher) |
| D4 | For nested targets (`a/b/`), the directory check lists only the share root, so it never matches. `createDirectory` isn't recursive, so it raises and calls `exit(1)`. | 206-215 | Can't install BIOS files that live in nested folders. | [03.9](03-critical-fixes-and-data-safety.md#039--recursive-remote-directory-creation-d4), final in [04.9](04-architecture-refactor.md#049--smb-transport-on-pysmb-d4-d11-d16) |
| D5 | Local MD5s are upper-cased, but report MD5s are not normalized. | 157, 180 | Silently matches nothing if a report uses lowercase. | [03.6](03-critical-fixes-and-data-safety.md#036--normalize-md5-case-d5) |
| D6 | Reading the report writes, reads and deletes `./test.txt` in the current directory; the temp file is never closed. | 75-85 | Can destroy a user's own `test.txt`; leaks a file handle. | [03.3](03-critical-fixes-and-data-safety.md#033--smb-session-seam-one-connection-in-memory-reads-closed-handles-d6-d7-d11-d16) |
| D7 | Upload opens the local file without closing it, then calls `os.remove`. | 96-98 | Fails on Windows ("file in use"). | [03.3](03-critical-fixes-and-data-safety.md#033--smb-session-seam-one-connection-in-memory-reads-closed-handles-d6-d7-d11-d16) |
| D8 | `os.walk` calls `exit()` as soon as **any** sub-folder has no files. Files in sub-folders are later addressed without their sub-path. | 172-183, 200, 223 | The run stops before validating anything; rename/delete of nested files fails. | [03.7](03-critical-fixes-and-data-safety.md#037--local-scanner-skip-dotfiles-recurse-no-early-exit-d1-d8) |
| D9 | Paths are inconsistent: config and `./bios` resolve against the CWD, `script_path` against `__file__`, and delete uses `bios/` against the CWD. | 39, 189, 223, 234 | Breaks when run from any other directory. | [03.11](03-critical-fixes-and-data-safety.md#0311--consistent-path-resolution-d9), final in stage 07 |
| D10 | Regexes run on `str(tuple)` returned by `re.findall`; `name` / `path` can be `None` and `.group()` then crashes. | 145-159 | `AttributeError` traceback on any unexpected report block. | [03.5](03-critical-fixes-and-data-safety.md#035--parser-real-match-strings-and-full-filenames-d2-d10) |
| D11 | A new SMB connection (plus `listShares`) is opened for every operation and never closed. `socket.gethostbyname(socket.gethostname())` can raise on misconfigured hosts. | 38-60 | Slow, leaks connections, crashes on some machines. | [03.3](03-critical-fixes-and-data-safety.md#033--smb-session-seam-one-connection-in-memory-reads-closed-handles-d6-d7-d11-d16), final in [04.9](04-architecture-refactor.md#049--smb-transport-on-pysmb-d4-d11-d16) |
| D12 | Copy-pasted error messages: listing says "Error creating directory"; directory creation prints `file` (always `None`). | 111, 127 | Misleading diagnostics. | [03.12](03-critical-fixes-and-data-safety.md#0312--cleanup-messages-imports-exceptions-typos-d12) |
| D13 | README: `pip install -r requirements` (missing `.txt`), `./bios_bios.py` (wrong name, and the file has no shebang or exec bit), `readme.MD`. | README | New users can't install or run it. | [03.1](03-critical-fixes-and-data-safety.md#031--fix-readme-commands-and-add-the-legal-notice-d13-d15), rewritten in [08.1](08-documentation.md#081--rewrite-the-readme) |
| D14 | `config/config.yml` is tracked by git, so users edit a tracked file containing their SMB password. | config | Credentials can be committed and pushed. | [03.2](03-critical-fixes-and-data-safety.md#032--stop-tracking-the-real-config-d14) |
| D15 | The Python floor is 3.10 (needed for `match`), which reached end-of-life in October 2026. | README | Users on an unsupported interpreter. | [02.1](02-foundation-tooling-and-ci.md#021--add-pyprojecttoml-and-uvlock-d15) + [03.1](03-critical-fixes-and-data-safety.md#031--fix-readme-commands-and-add-the-legal-notice-d13-d15) |
| D16 | *(Suspected; verify on a device.)* Port 445 is used without `is_direct_tcp=True` in pysmb's `SMBConnection`, so it relies on Samba accepting a NetBIOS session request on the direct-TCP port. | 48-51 | May fail against stricter SMB servers. | [03.3](03-critical-fixes-and-data-safety.md#033--smb-session-seam-one-connection-in-memory-reads-closed-handles-d6-d7-d11-d16) (interim), [04.9](04-architecture-refactor.md#049--smb-transport-on-pysmb-d4-d11-d16) (final) |

### Hygiene findings (not numbered, fixed in [03.12](03-critical-fixes-and-data-safety.md#0312--cleanup-messages-imports-exceptions-typos-d12))
- `import json` is unused, and so are `ITALIC`, `UNDERLINE`, `BLINK`, `BLACK` and `WHITE`.
- Bare `except:` at lines 31 and 225; `exit()` (the `site` builtin) instead of `sys.exit()` or exceptions.
- Typos in messages and names: `credencials`, `dosent`, `hashs`, `itens`, `Minimun`.
- `version: "3.8"` in `config.yml` has no meaning (it looks copied from a docker-compose file).
- A leftover TODO at line 235 ("Create a validation for duplicated md5sum of files") is covered by D3.

### Risks and assumptions
- The parser depends on the exact format of Recalbox's `missing_bios_report.txt`, which isn't documented
  publicly and may change between Recalbox versions. That's why DEC-09 gates parser work on real fixtures.
- BIOS files are copyrighted. The project must never ship, download or commit them, only match files the user
  already owns. MD5 hashes are fine to store in fixtures.

## Re-scoring history

| Date | After stage | Overall | Notes |
|---|---|---|---|
| 2026-11-02 | baseline | 3 / 10 | Initial review. |
| 2026-11-02 | 01 | 3 / 10 (sum 65 / 19 = 3.4) | **AI-agent readiness 0 → 4:** AGENTS.md verified loading natively in Claude Code and opencode, decision records give agents the reasoning, PR template carries the roadmap checklist; no machine-readable output or skills yet (stages 06, 09). **Community & governance 1 → 2:** ADRs, a documented decision process, PR template; no CONTRIBUTING or security policy yet. Everything else unchanged: no code was touched, and the user-facing README is still wrong (D13). |
| 2026-11-03 | 02 | 4 / 10 (sum 83 / 19 = 4.4) | **CI/CD 0 → 7:** every PR runs lint, format, strict types, tests on Python 3.11–3.14 (Linux only: Windows and macOS were removed before the merge, DEC-49), commit-message, secret and dependency checks, plus a weekly security run; `main` is protected and requires them. No release automation yet (stage 10). **Dependency management 5 → 7:** `uv.lock`, a dev group, a 14-day cooldown, a generated `requirements.txt`, vulnerability and license scanning and a written monthly routine; PyYAML and pysmb are still to go (stages 07, 04), and four pyasn1 CVEs are accepted until 2026-11-11. **Testing 0 → 2:** pytest, coverage and the matrix exist, but only tooling and an import smoke test are covered; no application behavior is tested yet (stage 03). **Code quality 3 → 4:** ruff formatting and lint rules and mypy strict for new code; the legacy script keeps documented exemptions until stage 03. **Security & data safety 3 → 4:** secret scanning, SCA, a hygiene guard against BIOS files and tracked configs, pinned and hash-checked tools; the script still deletes user files and the config file is still tracked (stage 03). **Portability stays 4:** LF line endings are enforced, but CI tests Linux only (DEC-49) and the Windows upload bug (D7) remains. **Packaging 1 → 2:** `pyproject.toml` with SPDX license metadata, not yet installable. **Git hygiene 5 → 6:** Conventional Commits enforced, merge-commit-only and protected `main`; no tags or changelog. **Licensing 6 → 7:** `license = "GPL-3.0-only"` metadata and a license report for dependencies; no BIOS disclaimer yet. **Community 2 → 3:** contributors' PRs get the same automated checks. **AI-agent readiness 4 → 5:** AGENTS.md lists commands agents can run to check their own work, and CI enforces them. Other aspects unchanged: no application code changed beyond formatting. |
| 2026-11-04 | 03 | 5 / 10 (sum 103 / 19 = 5.4) | **Functionality 4 → 7:** D1–D5, D8 and D10 are fixed and a real report parses fully; on a Recalbox 10.1.1 VM, 152 of 232 targets were filled and verified by MD5. No real-device run yet (DEC-51), and no dry-run or stale-report check. **Testing 2 → 6:** 161 tests, 99 % of `check_bios.py` covered, with real report fixtures and a fake SMB server; no integration tests yet (stage 05). **Security & data safety 4 → 7:** BECK no longer deletes or renames local files, and the config file is no longer tracked; the password is still plaintext in a local file (stage 07). **Error handling 3 → 6:** one error type, a bare `except` nowhere, and only `main()` exits; malformed YAML still gives a traceback (07.1), and one failed upload stops the run. **Code quality 4 → 5:** no ruff or mypy `disable_error_code` exemptions for the script; its relaxed mypy override stays until 04.14. **Architecture 2 → 3:** an SMB session class and pure parsing and planning functions, still in one file. **Documentation 3 → 4:** correct install and run commands, configuration and upgrade notes; the full rewrite is 08.1. **UX 4 → 5:** a per-file outcome list, and BECK runs from any folder; no arguments yet. **Configuration 3 → 4:** an example file and a clear error for a missing one; share and paths are still hard-coded. **Performance 5 → 6:** one connection per run, and files are hashed in chunks. **Portability 4 → 5:** D7 and D9 are fixed; CI still tests Linux only (DEC-49). **Licensing 7 → 8:** README legal notice and license line. Other aspects unchanged. |
