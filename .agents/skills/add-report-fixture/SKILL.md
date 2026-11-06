---
name: add-report-fixture
description: Add a Recalbox missing-BIOS report as a test fixture, with its expected parser output. Use when someone provides a new missing_bios_report.txt, or a new Recalbox version needs support.
license: GPL-3.0-only
compatibility: Needs git, uv and Python 3.11+. No network access or device is needed.
---

# Add a report fixture

[`tests/fixtures/README.md`](../../../tests/fixtures/README.md) describes the fixtures this adds to. A report holds BIOS file names and MD5 values, which are public, and no BIOS content.

## When to use

Someone gives you a real `missing_bios_report.txt`, or a Recalbox version isn't in [the provenance table](../../../tests/fixtures/README.md#provenance) yet. BECK supports the versions it has fixtures for (DEC-09).

## Inputs you need from the human

- **The report file itself,** copied as a file. Text pasted into a chat, or copied through a terminal, can lose its line endings, so it isn't byte-exact.
- **The Recalbox version,** and the platform, such as x86_64 or a Raspberry Pi model.
- **The exact menu path** they used.
- **The date it was generated,** if it isn't in the file.
- **What state the device was in,** such as a fresh install, and a short name for it, such as `default-install`.

Don't connect to their device to fetch it, unless they ask you to in this session.

## Steps

1. **Look at every line the format doesn't explain.** This prints each line that isn't one of the known kinds. On a report like the existing ones, it prints nothing:

   ```sh
   tr -d '\r' < REPORT | grep -nvE '^\s*$|^=+$|^-+$|^MISSING BIOS REPORT$|^Platform: |^Generated on |^SYSTEM: |^  (MISSING|INCORRECT) (REQUIRED|OPTIONAL) BIOS: |^    (Path: |For: |Notes: |Possible MD5 List:$|Current MD5: )|^      [0-9A-Fa-f]{32}$'
   ```

2. **If the format differs, stop.** That means a line from step 1 that isn't personal data, or this command exits with 4. Describe the difference to the owner: which lines, in which version, and how they differ. Changing the parser is separate work, and it's their decision.

   ```sh
   uv run beck --json report --report-file REPORT
   ```

3. **Anonymize.** Look through the whole file for a host name, a user name, a network name, an IP or MAC address, an email address, a path under a home folder, and anything else that points to a person. Step 1 shows most of these. Replace only those characters, and keep the line endings. Ask the owner whether to keep the `Generated on` line. MD5 values and BIOS file names stay.

4. **Add it, byte-exact.** Copy it to `tests/fixtures/reports/recalbox-<version>/<name>.txt` with `cp`, not an editor. `.gitattributes` keeps it from being converted.

5. **Write `<name>.expected.json` without using the parser,** because that would just copy its bugs. Read the report by hand, or for a long report, write a throwaway script that imports nothing from `beck`, keep it out of the repository, and check the tricky entries by hand. It's a JSON list with two-space indents, and one object per block, in report order. A file listed twice is two objects:

   ```json
   [
     {
       "name": "tos.img",
       "path": "/recalbox/share/bios/atarist/",
       "relativePath": "atarist/",
       "hashes": ["27AC71B59D59F65571B972E0F894054A"]
     }
   ]
   ```

   - `name`: from the `MISSING … BIOS:` or `INCORRECT … BIOS:` line.
   - `path`: the folder of the **first** location on the `Path:` line (DEC-50), with a trailing slash.
   - `relativePath`: the same folder relative to `/recalbox/share/bios/`, which is empty at the top of the share.
   - `hashes`: the `Possible MD5 List`, in first-seen order, with no repeats and in the report's case. A `Current MD5:` value doesn't go here.

   Tricky entries: two locations on one `Path:` line, the same name under several systems, a repeated MD5 in one list, `INCORRECT` blocks, and files at the top of the share.

6. **Add a row to [the provenance table](../../../tests/fixtures/README.md#provenance):** fixture, Recalbox version, date, platform, how it was generated, what you anonymized (or "Nothing", and what you looked for), and the number of entries, counting repeats.

7. **For a new version,** add its menu path and the date to [the guide's table](../../../docs/user-guide/generate-report.md#generating-it), and update [the project status in the README](../../../README.md#project-status).

8. **Run the tests.** New reports are picked up by themselves:

   ```sh
   uv run pytest tests/test_fixtures.py tests/unit/test_recalbox_adapter.py -q
   ```

9. **If a test fails,** either your expected file or the parser is wrong. Go back to the report and work out which by reading it. If it's the parser, stop and tell the owner: it's a bug, and it needs its own fix with a regression test. Don't change the expected file to make the test pass.

10. **Commit only if you've been asked to,** after [the quality gates](../quality-gates/SKILL.md).

## Verify

- `uv run pytest tests/test_fixtures.py tests/unit/test_recalbox_adapter.py -q` passes, and shows more tests than before.
- `git add` the files, and `git ls-files --eol tests/fixtures/reports/recalbox-<version>/` shows `-text` for the `.txt` file.
- The provenance table has the new row.

## Never do

- **Add a BIOS or ROM file,** or ask for one. A report is all this needs.
- **Generate the expected file with BECK's parser,** or edit it to match the parser.
- **Convert line endings,** reformat the report, or trim its trailing spaces.
- **Commit personal data.** If you aren't sure about a value, ask.
- **Change the parser** as part of adding a fixture.
- **Connect to a real Recalbox or SMB server** without the human's OK in this session.
