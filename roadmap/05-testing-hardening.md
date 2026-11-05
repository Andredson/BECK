# Stage 05 — Testing hardening

**Status:** Done (2026-11-05) · **Depends on:** 04 · **Branch:** `stage/05-testing` · **Effort:** M

## Goal
Make the test suite trustworthy enough that any agent or contributor can change BECK and know right away
whether something broke. That means systematic unit tests, real-server integration tests against Samba in a
container (the runtime-testing choice, DEC-33), and an enforced coverage gate.

## Why
- Testing is the weakest area (0/10 at baseline). Stage 03 added regression tests; this stage makes the
  suite systematic.
- Mocked SMB tests can't catch protocol, permission or path problems; a real Samba server can.
- Only pytest + pytest-cov + the Samba container are used (DEC-36): no property-based, snapshot or mutation
  testing tools.

## Decisions applied
DEC-08, DEC-09, DEC-25, DEC-33, DEC-36, DEC-40, DEC-55.

## Steps

### 05.1 — Test layout and shared factories
- [x] Done (2026-11-05: `make_report_text` was checked against the real report: its first block matches word for word except
  the `For` line, which BECK ignores, and all 238 real entries survive rendering and parsing. Used by the matcher, executor
  and console tests; the CLI tests use `md5_of` and `snapshot` so far. Different from the list below:
  - `make_missing(target, *md5s, required=True, system=None)` has no separate `name`, because the model requires the name to
    be the target's last part.
  - Added `make_local_file` for tests with no disk access, plus `md5_of` and `snapshot`, which were copied between files.
  - Repo-wide test files stay in `tests/`, because later steps cite `tests/test_docs_links.py` and add more there. Module tests
    moved to `tests/unit/` in stage 04.)
- **What:**
  - Layout: `tests/unit/`, `tests/integration/`, `tests/fixtures/`, `tests/conftest.py`.
  - Factories in `tests/factories.py`: `make_bios_file(dir, relative, content=None) -> LocalFile`, which writes
    random bytes and returns the real MD5; `make_missing(name, target, md5s, required=True)`; and
    `make_report_text(entries)`, which renders entries in the **real Recalbox report format** learned from the
    03.4 fixtures, for tests that need reports matching generated files.
  - Every test that needs a "BIOS" uses generated random bytes, never real BIOS content.
- **Files:** `tests/factories.py`, `tests/conftest.py`, moved test files
- **Done when:** All tests run from the new layout and the factories are used by at least the matcher and
  executor tests.
- **Verify:** `uv run pytest -q`
- **Commit message:** `test: organize unit and integration suites with shared factories`

### 05.2 — Parser coverage across all fixtures and edge cases
- [x] Done (2026-11-05: **this found a bug.** A UTF-8 BOM right before the first block made that block vanish with no error, so
  a report with one entry would say nothing is missing. `parse_report` now removes the BOM. Real reports start with a `====`
  line, so they weren't affected. The commit message is `fix(parser)`, so that the changelog shows it. A temporary fixture in
  a deeper folder was picked up with no code change. Also tested: the word `or` in a file name. Still open, not changed: a bad
  byte in a *name* becomes `\ufffd`, and BECK would upload under that name.)
- **What:** One parametrized test over **every** fixture in `tests/fixtures/reports/**`, so a new fixture is
  tested automatically. Explicit edge-case tests: hyphens, spaces, parentheses, multiple dots, nested paths,
  shared MD5s, uppercase and lowercase hashes, CRLF, a UTF-8 BOM, non-UTF-8 bytes (decoded with replacement, no
  crash), an empty file, a report with nothing missing, and a malformed block (`ReportParseError` naming the
  block).
- **Files:** `tests/unit/test_recalbox_adapter.py`
- **Done when:** Each edge case has a named test, and adding a fixture plus its `.expected.json` needs no code change.
- **Verify:** `uv run pytest tests/unit/test_recalbox_adapter.py -q`
- **Commit message:** `test(parser): cover every fixture and report edge case`

### 05.3 — Matcher and executor edge cases
- [x] Done (2026-11-05: permission errors use real file modes: a read-only folder, a read-only target file, a folder that
  can't be created, and a local file that can't be read. They're skipped when run as root. "Source unchanged" is built into
  the tests' `run` helper, so every scenario using it checks it, including new ones. The shuffled test uses the real report.
  Checked by breaking each rule on purpose.)
- **What:**
  - Matcher: empty inputs; nothing matches; everything matches; one file to many entries; many files to one
    entry; deterministic output under shuffled input; targets stay relative.
  - Executor on `LocalTransport` (`tmp_path`): dry run makes zero changes; re-running is idempotent; a
    permission error on one target is recorded and the run continues; the source folder is unchanged after
    every scenario (DEC-02).
- **Files:** `tests/unit/test_matcher.py`, `tests/unit/test_executor.py`
- **Done when:** Every listed scenario has a test.
- **Verify:** `uv run pytest tests/unit -q`
- **Commit message:** `test(core): cover matcher and executor edge cases`

### 05.3a — A report BECK can't recognize isn't "nothing missing"
- [x] Done (2026-11-05: Recalbox's public source shows the report is always written, and with nothing missing it's just the
  header, so that stays a success. **This found a data bug, D17:** Recalbox can also write `INCORRECT` blocks, which BECK
  didn't know, and they merged into the entry above. Beyond the list below:
  - `INCORRECT` is its own kind of block; the owner chose to keep such a file and report it (DEC-54).
  - Candidate MD5s come only from below `Possible MD5 List:`, so `Current MD5:` or a hash in a note can't become one.
  - The title is only required when no block is found, so a changed title with known blocks still parses.
  - An empty file is now an error, exit 4, because Recalbox always writes the header.

  The block format comes from Recalbox's source. It was **confirmed on the Recalbox 10.1.1 VM**: with random bytes at two targets,
  it wrote both `INCORRECT` heading forms, and the real `beck` kept both files and exited 0. That report is now the
  `incorrect-files` fixture, which replaces a fixture built by hand. The VM was restored. Checked by breaking each rule on
  purpose.)
- **What:** Today, a report with no recognized block gives "No missing bios were found", even if its format changed in a new
  Recalbox version, which would mislead the user with no error (found in 05.2). `RecalboxAdapter.parse_report` raises
  `ReportParseError` when the text has content but doesn't look like a report: no `MISSING BIOS REPORT` title, or a line with
  `MISSING` that isn't a recognized heading, or a `SYSTEM:` line with no block under it. A truly empty file also needs a
  clear outcome, because it isn't a report that says nothing is missing. First check what Recalbox writes when nothing is
  missing, on the VM if possible, so that this real case stays a success. If it can't be produced, record that the title
  check is an assumption.
- **Files:** `src/beck/frontends/recalbox.py`, `tests/unit/test_recalbox_adapter.py`, `tests/unit/test_cli.py`
- **Done when:** Tests cover a changed heading, a changed title, a system with no blocks, an empty file and a real header with
  nothing missing, and all fixtures still parse.
- **Verify:** `uv run pytest tests/unit/test_recalbox_adapter.py tests/unit/test_cli.py -q`
- **Commit message:** `fix(parser): report an unrecognized report instead of nothing missing`

### 05.4 — Samba test server image (DEC-40)
- [x] Done (2026-11-05: built and run with rootless Podman (DEC-55), on `debian:trixie-20261020-slim`, the newest past the cooldown,
  with Samba 4.22. Different from the list below: the port is published on `127.0.0.1` only, because guests can write to this
  server. `server min protocol = SMB2_02`, like Recalbox, because **`pysmb` can't connect with anything higher**; see
  [the spike](../docs/spikes/smbprotocol.md). `samba` itself isn't pinned by version, so the cooldown doesn't cover it: pinning would
  break whenever Debian replaces it, and this image is test-only. BECK's transport was checked against all three shares.)
- **What:** `tests/integration/samba/Containerfile`: our own minimal image with **no third-party Samba image**.
  - `FROM debian:<release>-slim@sha256:<digest>`, pinned by digest with the tag in a comment.
  - `apt-get install --no-install-recommends samba`; create the user `beck` with password `beck-test-password`
    (clearly fake; allow-listed in `.gitleaks.toml`, 02.12).
  - `smb.conf`: SMB2+ only, no NetBIOS, port 445, and three shares:
    - `bios`: guest-writable, like Recalbox's default (adjust names and flags to what the 04.1 spike found
      on a real device);
    - `private`: password-only, user `beck`;
    - `readonly`: guest, read-only (for error paths).
  - The container runs `smbd` in the foreground with logs on stdout. Check the current `smbd` flags for the
    pinned Samba version.
  - `tests/integration/samba/README.md`: build and run commands for local use, e.g.
    `podman build -t beck-samba tests/integration/samba && podman run -d --rm -p 127.0.0.1:4450:445 --name beck-samba beck-samba`.
- **Files:** `tests/integration/samba/Containerfile`, `tests/integration/samba/smb.conf`,
  `tests/integration/samba/README.md`
- **Done when:** After the run command, `smbclient -L` (or a short Python check) lists the three shares on
  `127.0.0.1:4450`.
- **Verify:** `podman build -t beck-samba tests/integration/samba` succeeds
- **Commit message:** `test(integration): add minimal Samba server image for SMB tests`

### 05.5 — SMB integration tests (DEC-33)
- [x] Done (2026-11-05: 25 tests against the Samba container, skipped cleanly without the variables, except one that needs no
  server. Beyond the list below:
  - **A guard against real devices:** the tests first read the `readonly` share's seeded file, and refuse any other server.
    Checked against the Recalbox VM: refused, with its files unchanged.
  - **Direct TCP on port 445** is tested with real SMB, with only the TCP port number redirected, which also closes that gap in
    CI.
  - End-to-end tests cover an `INCORRECT` file, an unrecognized report, a missing report, and running twice.
  - Tests share the report at the root of the `bios` share, so they run one at a time; each uses its own folder for targets.
  Checked by breaking the code on purpose, and tests leave nothing on the server. Not covered: real hardware (DEC-52).)
- **What:** `tests/integration/test_smb_transport.py`, marked `@pytest.mark.integration`, **skipped** unless
  `BECK_TEST_SMB_HOST` / `BECK_TEST_SMB_PORT` are set. Each test works in a unique sub-folder (uuid) so tests
  don't interfere. Scenarios:
  - guest connect, read a seeded report;
  - password connect; wrong password → `TransportError` (exit code 3) with a readable message;
  - unknown share and unreachable port → readable errors, no traceback;
  - nested `makedirs`, upload, `size` equals the local size;
  - read-only share: the upload error is recorded and the run continues;
  - **end-to-end:** `cli.main([...])` against the container, with generated "BIOS" files and a report built by
    `make_report_text`. Afterwards the files are on the share under the right names and folders, and the local
    folder is unchanged.
- **Files:** `tests/integration/test_smb_transport.py`, `tests/integration/conftest.py`
- **Done when:** All scenarios pass locally against the container, and are skipped cleanly without it.
- **Verify:** `BECK_TEST_SMB_HOST=127.0.0.1 BECK_TEST_SMB_PORT=4450 uv run pytest -m integration -q`
- **Commit message:** `test(integration): exercise the SMB transport against a real Samba server`

### 05.6 — CI integration job
- [x] Done (2026-11-05: green on the PR with 25 tests and none skipped, and the owner made `integration` a required check.
  Different from the list below: it runs on `ubuntu-26.04`, not `ubuntu-latest`, because that's the owner's Ubuntu and Podman
  version, and `ubuntu-latest` is migrating until 2026-11-19. The job fails if any test is skipped, because these tests skip
  themselves without their variables. It pulls the base image from Docker Hub with no login, so a rate limit could fail a run;
  that hasn't happened. The base image refresh is now in `docs/maintenance.md`.)
- **What:** Add an `integration` job to `ci.yml` on Linux only (GitHub's macOS and Windows runners
  don't run Linux containers), using Podman (DEC-55). It builds the image, starts the container, waits until port 4450 accepts
  connections (bounded retry loop), and runs `uv run pytest -m integration`. On failure it dumps `podman logs`.
  Add `integration` to the required checks (human step, as in 02.16).
- **Files:** `.github/workflows/ci.yml`
- **Done when:** The job is green on the PR and required for merging.
- **Verify:** The PR checks show `integration` passing.
- **Commit message:** `ci: run SMB integration tests against the Samba container`

### 05.7 — CLI tests
- [x] Done (2026-11-05: every exit code, 0 to 4, has named tests. The real entry points run as new processes, in a folder with
  no config, so they can't reach a device. **This found a test problem:** 14 tests failed for a developer with `FORCE_COLOR=1`
  in their shell. A fixture in `tests/conftest.py` now sets `NO_COLOR` for every test. Checked by breaking each rule on purpose.)
- **What:** Tests that call `cli.main([...])` with `capsys` and `monkeypatch.setenv("NO_COLOR", "1")`. They
  check exit codes for success, usage error, config error, transport error and report error, and that the key
  output lines are present (summary, per-file status). They use plain assertions on substrings, no snapshot files
  (DEC-36). Also run `python -m beck --help` through `subprocess` once to check the entry point.
- **Files:** `tests/unit/test_cli.py`
- **Done when:** Every exit path of `cli.main` is covered.
- **Verify:** `uv run pytest tests/unit/test_cli.py -q`
- **Commit message:** `test(cli): cover exit codes and key output lines`

### 05.8 — Coverage gate
- [x] Done (2026-11-05: the package is at 99.86 %. Checked with real untested code: 66 % fails with exit 1, also with `# pragma: no
  cover` on that code, because `exclude_lines` replaces coverage's defaults; 95 % passes. That also stopped coverage ignoring
  `...` bodies, so the Protocol classes' placeholder bodies were removed, as their docstrings are enough. The gate only applies
  to `uv run pytest --cov`, which CI runs on every Python version; a plain `uv run pytest` has none.)
- **What:** Add `fail_under = 90` (branch coverage) in `[tool.coverage.report]` for the unit run, and
  `show_missing = true`. Exclude only `if TYPE_CHECKING:` and `raise NotImplementedError` lines. The
  integration job doesn't count towards the gate; it covers behavior, not lines.
- **Files:** `pyproject.toml`
- **Done when:** `uv run pytest --cov` fails below 90 % and passes now.
- **Verify:** `uv run pytest --cov -q`
- **Commit message:** `test: enforce 90% branch coverage on the beck package`

### 05.9 — Close the stage
- [x] Done (2026-11-05: the acceptance criteria below hold; "all OS" means Linux only, per DEC-49. The stage scores 6/10, with a sum
  of 122, up from 118. The tests found three real bugs, in 05.2 and 05.3a. Draft PR #5 already exists, so the owner marks it ready and
  merges it with a merge commit.)
- **What:** Update AGENTS.md: testing section (unit vs integration, how to start the Samba container, the "never
  real BIOS bytes" rule). Re-score [00-assessment](00-assessment.md#re-scoring-history). Update the
  [README](README.md#stages) status. Push the closing commit (DEC-47). If the stage PR doesn't exist yet, print
  this command for the human (DEC-43):

  ```sh
  gh pr create --base main --title "Stage 05: testing hardening" --body "Closes roadmap stage 05."
  ```

- **Files:** `AGENTS.md`, `roadmap/00-assessment.md`, `roadmap/README.md`, this file
- **Done when:** The PR is merged with a merge commit.
- **Verify:** The full check suite in AGENTS.md passes, including the integration tests with the container running.
- **Commit message:** `docs(roadmap): close stage 05 and re-score assessment`

## Stage acceptance criteria
- Unit suite ≥ 90 % branch coverage and green on all Python versions, on Linux (DEC-49).
- Integration suite green against the Samba container in CI, and required for merging.
- No test uses the network other than the local container, and no test uses real BIOS data.

## Out of scope
- Hypothesis, snapshot libraries, mutation testing (DEC-36). Atheris fuzzing was offered and not chosen.

## Agent notes
- If you can't run Podman in your environment, say so and skip the integration tests locally with
  `-m "not integration"`. Never point integration tests at a real Recalbox.
