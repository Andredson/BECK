---
name: quality-gates
description: Run the same checks as BECK's CI on your own machine, and fix what fails without weakening them. Use before committing, when asked to run the checks or tests, or when a CI job or check fails.
license: GPL-3.0-only
compatibility: Needs git and uv. The integration tests need Podman. The secret and dependency scans need gitleaks and Trivy.
---

# Run the quality gates

These are the commands in [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml), in its order. If that file changes, change this one to match.

## When to use

Before every commit, when asked to run the checks, or when CI fails. To see why a CI job failed, run `gh run view <run id> --log-failed`.

## Inputs you need from the human

None. Ask before installing gitleaks or Trivy, or if a failure can only be fixed by weakening a check.

## Steps

1. **Run the `quality` and `tests` jobs.** These must pass before you commit:

   ```sh
   uv sync --locked
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy
   uv run python scripts/check_repo_hygiene.py
   uv export --no-dev --no-hashes --no-emit-project -o requirements.txt && git diff --exit-code -- requirements.txt
   uv run pytest --cov --cov-report=xml
   ```

   `pytest` also runs the link test and the other tests of the repository, so they have no command of their own. If you changed the dependencies, `git add requirements.txt` first, because `git diff` compares with what's staged.

2. **Run the `integration` job,** if Podman is available. Otherwise, say that you didn't. It uses only [the local test server](../../../tests/integration/samba/README.md), and any skipped test counts as a failure:

   ```sh
   podman rm -f beck-samba
   podman build -t beck-samba tests/integration/samba
   podman run -d -p 127.0.0.1:4450:445 --name beck-samba beck-samba
   for attempt in $(seq 1 30); do timeout 1 bash -c '</dev/tcp/127.0.0.1/4450' 2>/dev/null && break; sleep 1; done
   BECK_TEST_SMB_HOST=127.0.0.1 BECK_TEST_SMB_PORT=4450 bash -eo pipefail -c 'uv run pytest -m integration -q -rs | tee pytest-output.txt; ! grep -q "skipped" pytest-output.txt'
   rm -f pytest-output.txt
   podman rm -f beck-samba
   ```

3. **Run the `commits`, `secrets` and `sca` jobs,** if you have the tools. Otherwise, say that you left them to CI. CI checks the PR's own commits, and `origin/main..HEAD` is the same range:

   ```sh
   COMMITIZEN_VERSION=$(sed -n 's/.*COMMITIZEN_VERSION: "\([^"]*\)".*/\1/p' .github/workflows/ci.yml)
   uvx --exclude-newer "14 days" --from "commitizen==${COMMITIZEN_VERSION}" cz check --rev-range "origin/main..HEAD"
   gitleaks git --config .gitleaks.toml --redact --no-banner --verbose --log-opts="origin/main..HEAD" .
   trivy fs --scanners vuln --include-dev-deps --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --show-suppressed --no-progress --skip-dirs .venv --skip-files requirements.txt .
   VIRTUAL_ENV=.venv trivy fs --scanners license --exit-code 0 --no-progress --skip-dirs .venv --skip-files uv.lock .
   ```

   The license scan only reports. CI installs with `uv sync --locked --no-dev` first, so its report has just the runtime dependencies, and a local one also lists the dev ones.

4. **If something fails,** use the table below, fix the cause, and run that check again. Then run everything once more, since a fix can break another check.

5. **Say what you ran.** A local run only covers Python 3.11, so CI is what checks 3.12–3.14. To try one here, use a folder outside the repository: `UV_PROJECT_ENVIRONMENT=<folder> uv run --python 3.14 pytest --cov --cov-report=xml`.

## Reading a failure

| What failed | What it means | What to do |
|---|---|---|
| `uv sync --locked` | `uv.lock` doesn't match `pyproject.toml`. | Run `uv lock`, then regenerate `requirements.txt`. The cooldown stays (DEC-45). |
| `ruff check` | A rule, named by its code. `S` rules are about security, and `E501` means a line is over 100 columns. | Change the code. |
| `ruff format --check` | Layout, including Python blocks in Markdown. | Run `uv run ruff format .`. |
| `mypy` | Types, strict everywhere. | Fix the types. |
| `check_repo_hygiene.py` | A tracked BIOS or ROM file, a file over 1 MiB, a config file, or a TOML file with a password. | Stop tracking it with `git rm --cached`. If it held a real password or a BIOS file, tell the human: it's in the history. |
| `requirements.txt` | It doesn't match `uv.lock`. | Keep what `uv export` wrote, and `git add` it. Never edit it by hand. |
| `pytest`, in `test_cli_reference.py` | A flag or its help changed. | Run `uv run python scripts/gen_cli_reference.py`. |
| `pytest`, in `test_docs_links.py` | A link or an anchor is broken. | Fix the link. |
| `pytest`, in `test_troubleshooting.py` | A new error or exit code has no entry. | Add it to `docs/troubleshooting.md`. |
| `pytest`, in `test_license_headers.py` | A Python file doesn't start with its SPDX line. | Add it. |
| `pytest`, in `test_architecture.py` | The code breaks [a design rule](../../../docs/ARCHITECTURE.md). | Move the code. The rule isn't what's wrong. |
| `pytest`, in `test_json_contract.py` | The `--json` output changed, which is [a public contract](../../../docs/json-output.md). | A new field goes in the output, the schema, the guide and `V1_FIELDS`. To change an existing one, ask the owner. |
| `pytest`, in `test_redaction.py` | A password may reach the output. | Treat it as a security bug: find how it got there. |
| `pytest`, another test | Either the code or the test is wrong. | Work out which from what the test promises. Change a test only if the behavior was meant to change. |
| Coverage under 90 % | New code has no tests. | Write tests. `# pragma: no cover` doesn't work here. |
| A test skipped in `integration` | The two `BECK_TEST_SMB_*` variables aren't set. | Set them, as in step 2. |
| A test fails to reach the test server | It isn't running, or it doesn't have its seeded file. | Start it, as in step 2. The tests refuse any other server, on purpose. |
| `cz check` | A commit message isn't [Conventional Commits](../../../AGENTS.md#commits-and-pull-requests). | Fix it if it isn't pushed. If it is, tell the human: never rewrite history. |
| `gitleaks` | Something like a secret is in a commit. | Stop and tell the human, without repeating the value. It has to be changed, and fake `beck-test-*` values belong under `tests/`. |
| `trivy`, vulnerabilities | A fixable HIGH or CRITICAL finding, or an expired `.trivyignore` entry. | Follow [the maintenance routine](../../../docs/maintenance.md). |

## Verify

Every command you ran passes, and your report names any you didn't run.

## Never do

Without the owner's approval in this session:

- **Disable or relax a rule:** a `noqa`, a `type: ignore`, a per-file ignore, or a change to the settings of ruff, mypy or pytest.
- **Lower coverage:** a lower `fail_under`, or code left out of the measure.
- **Add an ignore or an exception:** a `.trivyignore` entry, a `.gitleaks.toml` allowance, or an exception in the hygiene script.
- **Weaken a test** to make it pass, skip it, or delete it.
- **Shorten the cooldown,** or remove it.
- **Point the integration tests at a real device,** or work around their refusal.
