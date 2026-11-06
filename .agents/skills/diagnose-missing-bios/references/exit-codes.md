# Exit codes

This table is a copy of the one in [the guide to the `beck` command](../../../../docs/cli.md#exit-codes), which has the details. Keep both the same: `tests/test_skills.py` checks them.

| Code | Meaning |
|---|---|
| 0 | The run completed. BIOS files may still be missing unless `--fail-if-missing` is used. |
| 1 | Unexpected internal error (a bug, please report it). |
| 2 | Usage or configuration error (bad flag, bad URL, invalid config, refused confirmation). |
| 3 | Transport error: couldn't connect or authenticate, or at least one upload failed or report entry was refused. |
| 4 | Report error: the missing-BIOS report wasn't found or couldn't be parsed. |
| 5 | `--fail-if-missing` was given and required BIOS files are still missing after the run. |
