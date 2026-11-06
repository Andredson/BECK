# Stage 07 — Configuration & security

**Status:** Not started · **Depends on:** 06 · **Branch:** `stage/07-config-security` · **Effort:** M

## Goal
Make configuration predictable and safe: one TOML file in the OS-correct folder, environment-variable
overrides, an interactive password prompt, guest access, and no secret ever printed or committed. Close the
remaining security gaps (path safety, upload integrity, documented threat model and reporting process).

## Why
- Configuration 3/10, security & data safety 3/10 at baseline.
- An installed CLI can't keep reading `./config/config.yml` from a repository checkout (DEC-19).
- PyYAML is only used for a 4-key config file; Python 3.11+ reads TOML with the standard library (DEC-24).

## Decisions applied
DEC-10, DEC-19, DEC-24, DEC-35, DEC-43, DEC-53.

## Configuration design (reference for all steps)

```toml
# <user config dir>/beck/config.toml, e.g. ~/.config/beck/config.toml on Linux
schema_version = 1

[target]
frontend = "recalbox"
url = "smb://recalbox.local/bios"   # or: dir = "/media/user/RECALBOX/bios"

[smb]
user = ""            # empty = guest (Recalbox default)
# The password is never stored here: use BECK_SMB_PASSWORD or the interactive prompt.
timeout = 10         # seconds

[source]
dir = "~/beck/bios"
```

**Precedence** (highest first): command-line flags → environment variables → config file → built-in defaults.

| Variable | Meaning |
|---|---|
| `BECK_CONFIG` | Path to the config file. |
| `BECK_TARGET` | Same as `--target`. |
| `BECK_TARGET_DIR` | Same as `--target-dir`. |
| `BECK_SOURCE` | Same as `--source`. |
| `BECK_SMB_USER` | SMB user (empty = guest). |
| `BECK_SMB_PASSWORD` | SMB password. The only way, besides the prompt, to supply a password. |

**Config file discovery:** `--config` → `$BECK_CONFIG` → `platformdirs.user_config_path("beck") / "config.toml"`.
A legacy `./config/config.yml` triggers a migration message (07.3).

## Steps

### 07.1 — TOML loader, schema and validation
- [ ] Done
- **What:** `src/beck/config.py`:
  - A frozen `Config` dataclass.
  - `load(path) -> Config` using `tomllib`.
  - Validation that reports **every** problem with its key path (e.g. `smb.timeout: expected a positive
    integer, got "ten"`); unknown keys produce a warning, not an error.
  - A `schema_version` check (an unknown future version gives a clear error).
  - **Reject a `password` key** with a message pointing to `BECK_SMB_PASSWORD`.
- **Files:** `src/beck/config.py`, `tests/unit/test_config.py`
- **Done when:** Tests cover a valid file, each validation error, unknown keys, a password key, and a future schema version.
- **Verify:** `uv run pytest tests/unit/test_config.py -q`
- **Commit message:** `feat(config): load and validate a TOML configuration file`

### 07.2 — Discovery and precedence
- [ ] Done
- **What:** `uv add platformdirs` (DEC-19). Implement discovery and the precedence order above as a pure function
  `resolve(flags, env, file_config) -> Settings`, so it can be tested without touching the real environment.
  Tests monkeypatch `platformdirs` and the environment.
- **Files:** `src/beck/config.py`, `src/beck/cli.py`, `pyproject.toml`, `uv.lock`, `tests/unit/test_settings.py`
- **Done when:** A test table covers every source winning over the ones below it, for each setting.
- **Verify:** `uv run pytest tests/unit/test_settings.py -q`
- **Commit message:** `feat(config): resolve settings from flags, environment, file and defaults`

### 07.3 — `beck config` commands and the legacy migration
- [ ] Done
- **What:**
  - `beck config path` prints the file that would be used and why (flag, env or default).
  - `beck config init` writes a commented template like the one above to the default location. It refuses to
    overwrite an existing file unless `--force` is given, and creates the file with owner-only permissions on POSIX.
  - `beck config show` prints the effective settings and their source; the password is shown only as
    `set` / `not set`.
  - **Migration:** if `./config/config.yml` exists, print a one-time notice with the equivalent TOML. Read its
    simple `key: value` lines with a small parser written for this purpose; **no YAML dependency**.
  - Remove PyYAML and `types-PyYAML` (`uv remove PyYAML && uv remove --dev types-PyYAML`) and regenerate
    `requirements.txt`. Remove `config/config.example.yml` and the legacy loader.
- **Files:** `src/beck/cli.py`, `src/beck/config.py`, `src/beck/legacy_config.py`, `pyproject.toml`, `uv.lock`,
  `requirements.txt`, `config/`, `tests/unit/test_config_cli.py`
- **Done when:** A legacy file produces the right TOML suggestion, and PyYAML is gone from the lockfile.
- **Verify:** `uv run pytest tests/unit/test_config_cli.py -q && ! grep -qi pyyaml uv.lock`
- **Commit message:** `feat(config)!: switch to TOML config with migration from config.yml`

### 07.4 — Credentials: environment, prompt, guest (DEC-10)
- [ ] Done
- **What:**
  - Empty user → guest login.
  - User set and `BECK_SMB_PASSWORD` set → use it.
  - User set, no password, stdin is a TTY → `getpass.getpass()`.
  - User set, no password, no TTY → exit 2: "set BECK_SMB_PASSWORD or run interactively".

  The password lives only in memory and is passed straight to the transport.
- **Files:** `src/beck/credentials.py`, `src/beck/cli.py`, `tests/unit/test_credentials.py`
- **Done when:** All four cases are tested, with `getpass` monkeypatched.
- **Verify:** `uv run pytest tests/unit/test_credentials.py -q`
- **Commit message:** `feat(config): support guest, environment and prompted SMB credentials`

### 07.5 — Secret redaction everywhere
- [ ] Done
- **What:** One `redact()` helper used by logging, `config show`, the JSON output and error messages; URLs
  are always printed without credentials. A **sentinel test** sets a unique password value, runs every command
  with `-v` and `--json` (success and failure paths), and asserts the sentinel never appears in stdout, stderr or
  log records. On POSIX, warn if the config file is readable by group or others.
- **Files:** `src/beck/redact.py`, `src/beck/**`, `tests/unit/test_redaction.py`
- **Done when:** The sentinel test covers every command and the integration E2E path.
- **Verify:** `uv run pytest tests/unit/test_redaction.py -q`
- **Commit message:** `fix(security): redact credentials in logs, errors and JSON output`

### 07.6 — Path safety for report-derived targets
- [ ] Done
- **What:** Every target path built from the report must be relative and normalized. Reject absolute paths,
  `..` segments, empty names, and names with path separators *after* stripping the device BIOS root. Also reject a name or
  folder containing `\ufffd`: a byte that wasn't valid UTF-8 was replaced there, and uploading would leave a useless file on
  the device (found in 05.2). Also reject a name or folder containing a control character, which today creates a file with that
  name on the device (found in 06.11, and [06.11a](06-cli-ux-and-machine-output.md#0611a--control-characters-in-names-cant-reach-the-terminal-d24)
  only stops it reaching the terminal). A rejected entry is reported as an error item and isn't uploaded. This is defense in depth against a crafted or
  corrupted report. `LocalTransport` already refuses escapes (04.8); add the same check in `SmbTransport`.
- **Files:** `src/beck/frontends/recalbox.py`, `src/beck/transports/smb.py`, `tests/unit/test_path_safety.py`
- **Done when:** Tests with malicious entries (`../../etc/x`, `/abs/path`, `a/../../b`), a name with `\ufffd` and a name with a control
  character produce errors and no uploads.
- **Verify:** `uv run pytest tests/unit/test_path_safety.py -q`
- **Commit message:** `fix(security): reject unsafe target paths from reports`

### 07.7 — Upload integrity and SMB options
- [ ] Done
- **What:**
  - After each upload, compare the remote size with the local size; a mismatch is an item error.
  - `--verify` additionally reads the remote file back and compares its MD5. It's slower, so it's off by default.
  - Expose `smb.timeout`. Document why there's no `smb.encrypt`: `pysmb` has no SMB encryption (DEC-53).
- **Files:** `src/beck/executor.py`, `src/beck/transports/smb.py`, `src/beck/config.py`, tests
- **Done when:** Unit tests cover size and MD5 mismatches; the integration test checks `--verify` against Samba.
- **Verify:** `uv run pytest -q -k "verify or integrity"`
- **Commit message:** `feat(transfer): verify uploads by size and optionally by MD5`

### 07.8 — `SECURITY.md` and threat model
- [ ] Done
- **What:**
  - `SECURITY.md`: supported versions (latest minor), how to report a vulnerability (GitHub **private
    vulnerability reporting**, which the owner enables in 12.6), response expectations, and what is out of scope
    (e.g. Recalbox's own Samba configuration).
  - `docs/threat-model.md` (one page): the assets (the user's BIOS files, SMB credentials, the device's BIOS
    folder), the trust boundaries (local disk ↔ BECK ↔ network ↔ device), the main threats and their mitigations
    (credential leakage → redaction and no config password; destructive mistakes → DEC-02 and confirmations;
    crafted reports → 07.6; supply chain → Trivy, gitleaks, pinned actions, attestations; an unencrypted
    LAN protocol → documented limitation).
- **Files:** `SECURITY.md`, `docs/threat-model.md`, `AGENTS.md` (link)
- **Done when:** Both files exist and are linked from the README and AGENTS.md.
- **Verify:** `uv run pytest tests/test_docs_links.py -q`
- **Commit message:** `docs(security): add security policy and threat model`

### 07.9 — Close the stage
- [ ] Done
- **What:** Update AGENTS.md: the config and credentials rules ("never print, log or commit passwords; use
  `BECK_SMB_PASSWORD`"), and the security docs links. Remove the `config/config.yml` check from the hygiene script
  if no longer relevant, or extend it to catch `config.toml` files containing a `password`. Re-score
  [00-assessment](00-assessment.md#re-scoring-history) and mark D9 and D14 fully fixed. Update the
  [README](README.md#stages) status. Push the closing commit (DEC-47). If the stage PR doesn't exist yet, print
  this command for the human (DEC-43):

  ```sh
  gh pr create --base main --title "Stage 07: configuration and security" --body "Closes roadmap stage 07."
  ```

- **Files:** `AGENTS.md`, `scripts/check_repo_hygiene.py`, `roadmap/00-assessment.md`, `roadmap/README.md`, this file
- **Done when:** The PR is merged with a merge commit.
- **Verify:** The full check suite in AGENTS.md passes.
- **Commit message:** `docs(roadmap): close stage 07 and re-score assessment`

## Stage acceptance criteria
- A user can configure BECK entirely through `beck config init` plus env vars, from any working directory.
- No password can be stored in the config file, appear in a URL, or be printed in any output mode.
- PyYAML is removed; the only runtime dependencies are `pysmb` and `platformdirs`.

## Out of scope
- The OS keyring was offered and not chosen (DEC-10). SSH/SFTP (DEC-04).

## Agent notes
- When testing credentials, use obviously fake values such as `beck-test-password`, which is allow-listed for
  gitleaks. Never use a value that looks like a real secret.
