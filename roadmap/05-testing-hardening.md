# Stage 05 — Testing hardening

**Status:** Not started · **Depends on:** 04 · **Branch:** `stage/05-testing` · **Effort:** M

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
DEC-08, DEC-09, DEC-25, DEC-33, DEC-36, DEC-40.

## Steps

### 05.1 — Test layout and shared factories
- [ ] Done
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
- [ ] Done
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
- [ ] Done
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

### 05.4 — Samba test server image (DEC-40)
- [ ] Done
- **What:** `tests/integration/samba/Dockerfile`: our own minimal image with **no third-party Samba image**.
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
    `docker build -t beck-samba tests/integration/samba && docker run -d --rm -p 4450:445 --name beck-samba beck-samba`.
- **Files:** `tests/integration/samba/Dockerfile`, `tests/integration/samba/smb.conf`,
  `tests/integration/samba/README.md`
- **Done when:** After the run command, `smbclient -L` (or a short Python check) lists the three shares on
  `127.0.0.1:4450`.
- **Verify:** `docker build -t beck-samba tests/integration/samba` succeeds
- **Commit message:** `test(integration): add minimal Samba server image for SMB tests`

### 05.5 — SMB integration tests (DEC-33)
- [ ] Done
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
- [ ] Done
- **What:** Add an `integration` job to `ci.yml` on `ubuntu-latest` only (GitHub's macOS and Windows runners
  don't run Linux containers). It builds the image, starts the container, waits until port 4450 accepts
  connections (bounded retry loop), and runs `uv run pytest -m integration`. On failure it dumps `docker logs`.
  Add `integration` to the required checks (human step, as in 02.16).
- **Files:** `.github/workflows/ci.yml`
- **Done when:** The job is green on the PR and required for merging.
- **Verify:** The PR checks show `integration` passing.
- **Commit message:** `ci: run SMB integration tests against the Samba container`

### 05.7 — CLI tests
- [ ] Done
- **What:** Tests that call `cli.main([...])` with `capsys` and `monkeypatch.setenv("NO_COLOR", "1")`. They
  check exit codes for success, usage error, config error, transport error and report error, and that the key
  output lines are present (summary, per-file status). They use plain assertions on substrings, no snapshot files
  (DEC-36). Also run `python -m beck --help` through `subprocess` once to check the entry point.
- **Files:** `tests/unit/test_cli.py`
- **Done when:** Every exit path of `cli.main` is covered.
- **Verify:** `uv run pytest tests/unit/test_cli.py -q`
- **Commit message:** `test(cli): cover exit codes and key output lines`

### 05.8 — Coverage gate
- [ ] Done
- **What:** Add `fail_under = 90` (branch coverage) in `[tool.coverage.report]` for the unit run, and
  `show_missing = true`. Exclude only `if TYPE_CHECKING:` and `raise NotImplementedError` lines. The
  integration job doesn't count towards the gate; it covers behavior, not lines.
- **Files:** `pyproject.toml`
- **Done when:** `uv run pytest --cov` fails below 90 % and passes now.
- **Verify:** `uv run pytest --cov -q`
- **Commit message:** `test: enforce 90% branch coverage on the beck package`

### 05.9 — Close the stage
- [ ] Done
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
- Unit suite ≥ 90 % branch coverage and green on all OS / Python combinations.
- Integration suite green against the Samba container in CI, and required for merging.
- No test uses the network other than the local container, and no test uses real BIOS data.

## Out of scope
- Hypothesis, snapshot libraries, mutation testing (DEC-36). Atheris fuzzing was offered and not chosen.

## Agent notes
- If you can't run Docker in your environment, say so and skip the integration tests locally with
  `-m "not integration"`. Never point integration tests at a real Recalbox.
