# The `beck` command

The reference for using BECK from the command line.

**Status:** this is the design [stage 06](../roadmap/06-cli-ux-and-machine-output.md) is building, so most of it doesn't exist yet.
Today, `beck check` runs with the defaults below and reads its settings from `config/config.yml` in the current folder, and `--version`
and `--no-color` work. `beck scan` and `beck report` only say they aren't available yet.

```text
beck [--version] [-v | -q] [--no-color] [--json] <command> [options]

beck check   [--source DIR] [--target URL | --target-dir DIR] [--frontend recalbox]
             [--report-file FILE] [--dry-run] [--move] [--clean-unmatched] [--yes]
             [--fail-if-missing]
beck scan    [--source DIR]
beck report  [--target URL | --target-dir DIR | --report-file FILE]
```

`beck config` arrives in stage 07, with TOML settings. Passwords never go on the command line.

## Commands

### `beck check`

Reads the report of missing BIOS files, hashes your local files, and copies the matches to the right folders on the device. It
never deletes a local file unless you ask.

```sh
beck check --dry-run                          # show the plan and change nothing
beck check                                    # copy the matching files
beck check --target smb://recalbox.local/bios --source ~/my-bios
beck check --target-dir /media/sdcard/bios    # a mounted SD card or USB drive
```

Running `beck` with no command works as `beck check` for one more release, and prints a hint. Use `beck check` in scripts.

### `beck scan`

Lists your local files with their relative path, size and MD5. It uses no network and writes nothing.

```sh
beck scan --source ~/my-bios
```

### `beck report`

Lists what the report says is missing or incorrect, grouped by folder, with whether each file is required. It writes nothing.

```sh
beck report --target smb://recalbox.local/bios
beck report --report-file missing_bios_report.txt     # a local copy: no network
```

## Options

### Global options

They work before or after the command.

| Option | What it does |
|---|---|
| `--version` | Prints `beck <version>`. |
| `-v` | Adds debug logs on stderr: connection steps, timings and plan details, never credentials. |
| `-q` | Prints only errors and the final summary. |
| `--no-color` | The same as setting `NO_COLOR`. |
| `--json` | Prints one JSON document on stdout, and logs and prompts on stderr. See [JSON output](#json-output). |

Colors follow `NO_COLOR`, then `FORCE_COLOR`, and otherwise appear only on a terminal. An empty value counts as not set.

### Choosing what BECK works on

| Option | Commands | What it does |
|---|---|---|
| `--source DIR` | `check`, `scan` | Your folder of BIOS files. The default is `./bios`. Hidden files and folders are skipped. |
| `--target URL` | `check`, `report` | An SMB target: `smb://[user@]host[:port]/share[/sub/path]`. The port defaults to 445. A URL with a password is refused. |
| `--target-dir DIR` | `check`, `report` | A folder: a mounted SD card or USB drive, or the device itself. It can't be combined with `--target`. |
| `--frontend NAME` | `check` | The kind of device. Only `recalbox`, for now. |
| `--report-file FILE` | `check`, `report` | Reads a local copy of the report, not the one on the target. |

With no target, BECK uses the settings in `config/config.yml`.

### Safety

| Option | What it does |
|---|---|
| `--dry-run` | Shows the full plan, including what would be deleted, and changes nothing, locally or on the device. |
| `--move` | Deletes a local file once it's uploaded to **all** its targets and each remote size matches. If any upload of that file failed, the file stays. |
| `--clean-unmatched` | Deletes local files that matched nothing. Read the warning below first. |
| `--yes` | Confirms deletions without asking. Required when BECK can't ask. |
| `--fail-if-missing` | Exits with 5 if required files are still missing after the run. See [exit codes](#exit-codes). |

## What BECK deletes, and when

Without `--move` or `--clean-unmatched`, BECK never deletes or renames a local file (DEC-02).

With either of them, BECK lists the files and asks `Delete N files? [y/N]` on a terminal. Without a terminal, as in scripts, agents and
CI, deleting requires `--yes`, and otherwise BECK exits with 2. `--json` never prompts, so it requires `--yes` too. A dry run deletes
nothing, even with these flags, and shows what would go. Every deletion is listed in the result.

These are never deleted:

- duplicates: they're kept and reported;
- files whose targets are already filled;
- hidden files, because they aren't scanned;
- a file that's valid for a target listed as `INCORRECT`, because it's the fix for that file.

> [!WARNING]
> "Unmatched" only means that the **current report** doesn't ask for that file. After you upload your files and scan again on the
> device, the report no longer lists them, so a later `--clean-unmatched` treats all your good BIOS files as unmatched and **deletes
> them**. Always run `beck check --dry-run --clean-unmatched` first, and read the list (DEC-56).

## Files already on the device

- **Listed as `INCORRECT` by the report:** the file is on the device with a wrong hash. BECK keeps it and reports it, and never uploads
  to that target, even if you have a valid copy (DEC-54). It tells you which local file would fit, so that you can replace it yourself.
- **Listed as missing, but the file is there:** this can happen if the report is out of date. What BECK does here is the decision in
  [step 06.5](../roadmap/06-cli-ux-and-machine-output.md#065--owner-decision-remote-files-that-already-exist). Today it replaces the file.

## Exit codes

These are a stable contract (DEC-23), and scripts can rely on them.

| Code | Meaning |
|---|---|
| 0 | The run completed. BIOS files may still be missing unless `--fail-if-missing` is used. |
| 1 | Unexpected internal error (a bug, please report it). |
| 2 | Usage or configuration error (bad flag, bad URL, invalid config, refused confirmation). |
| 3 | Transport error: couldn't connect or authenticate, or at least one upload failed. |
| 4 | Report error: the missing-BIOS report wasn't found or couldn't be parsed. |
| 5 | `--fail-if-missing` was given and required BIOS files are still missing after the run. |

Some details:

- A failed upload exits with 3 even though the other uploads finished.
- A local file or folder that can't be read, such as a broken symlink, is reported and skipped, and doesn't change the exit code.
- `--fail-if-missing` counts entries that are required or whose status is unknown. A required file listed as `INCORRECT` counts too,
  because the device still can't use it.
- If several apply, the transport error wins over `--fail-if-missing`, because the run didn't do all it could.

## JSON output

`--json` prints a single JSON document on stdout, for every command and for errors that stop a run, so stdout can always be parsed.
It carries a `schema_version`, and is described by JSON Schema files in `docs/schemas/`. Step 06.7 adds both, with a full guide in
`docs/json-output.md`.

Within `schema_version` 1, fields are only ever added. Renaming or removing a field, or changing its meaning, needs `schema_version` 2.
Ignore fields you don't know.

**Reading the result:** branch on the exit code first, then read the document. `ok` is false when the exit code isn't 0.
