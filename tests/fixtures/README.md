# Test fixtures

Missing-BIOS reports for the parser tests. They contain BIOS file names and MD5 values, which are public, and **no
BIOS content**. Never add BIOS files here.

## Reports

Each `<name>.txt` in `reports/recalbox-<version>/` has a `<name>.expected.json`: the entries the parser must produce,
in report order, with repeated entries kept. Each entry has:

| Key | Meaning |
|---|---|
| `name` | File name from the `MISSING … BIOS:` or `INCORRECT … BIOS:` line |
| `path` | Folder of the **first** location on the `Path:` line (DEC-50), with a trailing slash |
| `relativePath` | The same folder, relative to the `bios` share (empty at the share root) |
| `hashes` | MD5 values in first-seen order, without repeats, with the case used in the report |

The `.txt` files are byte-exact (see `.gitattributes`): real reports use CRLF line endings. Load them with
`load_report` and `load_expected` from `tests/conftest.py`.

The expected files were written by a one-off line-based script that shares no code with `check_bios.py`, so they
don't copy the parser's bugs. The tricky entries were then checked by hand and looked over by the owner.

## Provenance

| Fixture | Recalbox | Date | Platform | How it was generated | Anonymized | Entries |
|---|---|---|---|---|---|---|
| `recalbox-10.1.1/default-install` | 10.1.1 | 2026-11-04 | x86_64, fresh install in a QEMU VM | Main menu → BIOS CHECKING → REPORT | Nothing: no host names or user names found; the date line was kept by the owner's choice | 238 |

## Derived fixtures

All are cut from `recalbox-10.1.1/default-install`, using its original blocks.

| Fixture | Covers | Changed from the original |
|---|---|---|
| `derived-lf-endings` | LF line endings, and non-ASCII system names (`Odyssey²`, `Pokémon`) | CRLF converted to LF |
| `derived-lowercase-hashes` | Lowercase MD5 values | MD5 values lowercased |
| `derived-unusual-names` | Names with spaces, parentheses, hyphens and several dots | Nothing |
| `derived-nested-paths` | Share root, two-level folders, and one name in three folders (`IPL.bin`) | Nothing |
| `derived-shared-md5` | One MD5 in several entries, repeated targets, two locations on a `Path:` line, a repeated MD5 in one list | Nothing |
| `derived-incorrect` | An `INCORRECT` block between two `MISSING` blocks | The middle block's heading changed and a made-up `Current MD5:` added, following Recalbox's source. No real report with this block has been seen yet |

To add a report from another Recalbox version, keep the file byte-exact, remove anything personal, and add a row above.
