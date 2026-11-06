---
name: add-frontend-adapter
description: Add support for another retro-gaming system to BECK, such as Batocera or RetroBat, with its adapter, fixtures, tests and documents. Use when asked to support a new frontend or device type.
license: GPL-3.0-only
compatibility: Needs git, uv and Python 3.11+. Checking it on a device needs a person with that device.
---

# Add a frontend adapter

[`recalbox.py`](../../../src/beck/frontends/recalbox.py) is the reference implementation, and [the design](../../../docs/ARCHITECTURE.md) says where things go. Follow [`execute-roadmap-step`](../execute-roadmap-step/SKILL.md) if this is a roadmap step.

## When to use

Someone asks BECK to support a system other than Recalbox (DEC-03). For a new version of Recalbox, use [`add-report-fixture`](../add-report-fixture/SKILL.md).

## Inputs you need from the human

- **Real reference data from the system:** its missing-BIOS report or list, and the version it came from. Never BIOS files.
- **The share layout:** the share's name, where the BIOS folder is on it, where the report lands, and whether guests can log in.
- **How to generate the report,** with the exact menu path.
- **Someone who can check it on a device.** Without that, the adapter stays unverified, and the documents must say so.

If you don't have the data, mark the step `BLOCKED`. Don't write an adapter from memory or from a web page.

## Steps

1. **Check that it fits.** `FrontendAdapter` assumes one report file at a fixed path, which names each missing file, where it goes, and its possible MD5 values. If the system has no such file, or lists another kind of hash, stop and describe the gap to the owner. That's a design decision, not a detail of the adapter.
2. **Record the research** in `docs/research/<name>.md`: the facts above, and where each came from. Never bundle a list of hashes in BECK without a decision on its license.
3. **Ask the owner for a decision.** Give the alternatives, then record [a new DEC and an ADR section](../../../docs/adr/README.md#adding-a-decision). Include whether it needs anything from step 8.
4. **Add the fixtures,** as in [`add-report-fixture`](../add-report-fixture/SKILL.md), in `tests/fixtures/reports/<name>-<version>/`. Keep them byte-exact, and write the expected files without the parser. That skill's rules for `path` and `relativePath` use Recalbox's folder, so use this system's.
5. **Make the fixture tests handle more than one system.** A fixture from another system fails these today, because they read every report as Recalbox's. They should choose the adapter from the fixture's folder:
   - `tests/test_fixtures.py`: `test_expected_file_matches_the_report`, which also has Recalbox's folder written in it.
   - `tests/unit/test_recalbox_adapter.py`: `test_parser_matches_the_expected_entries`.
   - `tests/unit/test_json_contract.py`: `test_the_document_matches_its_schema_and_the_guide`, for its `report_on_fixture_` scenarios, and `test_every_error_code_comes_up_with_its_documented_exit_code`.
6. **Write `src/beck/frontends/<name>.py`.** It sets `name` and `report_path`, and has `parse_report` and `rejected_entries`. It stays pure, with no I/O. Cover what Recalbox's needed:

   | Concern | What the adapter must do |
   |---|---|
   | Text | Handle a BOM and CRLF. Invalid UTF-8 arrives as `U+FFFD`, because `cli.py` decodes the report. |
   | Paths | Turn the system's paths into paths relative to its BIOS root, with a constant like `BIOS_ROOT`. Only adapters know about these. |
   | A format it doesn't know | Raise `ReportParseError`, such as for a missing title, an unknown heading or a block with no path or MD5. It must never read as "nothing missing". Name the problem in the message. |
   | A report with nothing missing | Return no entries, if it's still recognizably a report. |
   | Entries | Keep report order, and repeats. Lowercase each MD5. Set `required` and `system` if the report says so, or leave them out. |
   | Wrong files | If the system reports them, set `incorrect` and `current_md5`. That hash must never become a candidate. |
   | Several locations | Choose one, and record which in the decision (DEC-50 is Recalbox's). |
   | Model errors | Turn a `ValueError` from `MissingBios` into `ReportParseError`. Without that, a bad entry ends in a traceback and exit code 1. |

7. **Refuse unsafe entries.** A report can say anything, and over SMB a backslash separates folders too, so `MissingBios`'s own check isn't enough. Move `_why_unsafe` out of `recalbox.py` to a shared module, rather than copy it, and use it for both. A refused entry is an `ItemError` with the code `unsafe_path`, returned by `rejected_entries`, and the other entries carry on. Run the tests in `tests/unit/test_path_safety.py` against both adapters. Its table of unsafe entries is the minimum.
8. **Register it,** in `_ADAPTERS` in `src/beck/frontends/__init__.py`. `--frontend` and the settings file then accept it. These still assume Recalbox, and need a decision:
   - `src/beck/output/console.py`: three messages say `RECALBOX`, so a user of another system would be told the wrong device.
   - `src/beck/cli.py`: `DESCRIPTION`. Also, `--frontend` is only on `beck check`, so `beck report` can only reach another system through the settings file.
   - `src/beck/config.py`: `TEMPLATE`, with its `recalbox.local` and its comment about guests.

   The `frontend` field in `--json` is any string, so the schemas don't change. Ask the owner before changing an existing field.
9. **Write the documents:**
   - `README.md`: what it supports, and how far that's been checked.
   - `docs/user-guide/`: how to generate this system's report.
   - `docs/troubleshooting.md`: an entry for what differs, such as a share's name or a login.
   - `docs/cli.md`: the `--frontend` row says "Only `recalbox`, for now", and the settings section.
   - `docs/threat-model.md`: whatever differs from what it says about Recalbox.
   - `docs/agents.md` and `AGENTS.md`: the support note, and the repository map if needed.
   - `docs/cli-reference.md`, with `uv run python scripts/gen_cli_reference.py`, if any help changed.
10. **Run it from start to finish,** on a fixture, with no device. Check that it copies the right file to the right folder, and that an unsafe entry is refused with exit code 3:

    ```sh
    uv run beck check --frontend <name> --dry-run --source <folder> --target-dir <folder with the report>
    uv run beck check --frontend <name> --source <folder> --target-dir <folder with the report>
    ```

11. **Run [the quality gates](../quality-gates/SKILL.md).** Coverage counts the new module too.
12. **Ask a person with the device to check it,** and record the result in the research file. Until then, it's verified on fixtures only, and the documents say that.

## Verify

- `uv run pytest -q -k <name>` runs the new tests, and they pass.
- Both adapters pass the path-safety tests.
- `grep -rn -i recalbox src/beck` shows nothing a user of the new system would read, except what the decision accepted.

## Never do

- **Add a BIOS file,** or download one or a list of hashes.
- **Change `FrontendAdapter`, or add a plugin system,** without a decision. If the system doesn't fit, say so.
- **Put device paths or report formats outside `frontends/`** (rule 3 in [the design](../../../docs/ARCHITECTURE.md#rules)).
- **Copy `_why_unsafe`,** or leave any path check out.
- **Say it's supported** when nobody has checked it on a device.
- **Connect to a real device** without the human's OK in this session.
