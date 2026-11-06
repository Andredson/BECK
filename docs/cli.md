# The `beck` command

The reference for using BECK from the command line.


```text
beck [--version] [-v | -q] [--no-color] [--json] [--config FILE] <command> [options]

beck check   [--source DIR] [--target URL | --target-dir DIR] [--frontend recalbox]
             [--report-file FILE] [--overwrite] [--dry-run] [--move] [--clean-unmatched]
             [--yes] [--fail-if-missing]
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

Lists your local files with their MD5, size in bytes and relative path, the same order as `md5sum`. Then it lists what it couldn't read, and
the totals. It uses no network and writes nothing.

```text
$ beck scan --source ~/my-bios
d41d8cd98f00b204e9800998ecf8427e  524288  ps1/scph1001.bin
900150983cd24fb0d6963f7d28e17f72    1024  tos.img
broken-link.bin: can't be read, skipped: broken symlink
Files: 2, can't be read: 1
```

### `beck report`

Lists what the report says is incorrect, then what's missing, grouped by folder, with whether each file is required. A file listed in several
systems appears once, and counts as required if any of them requires it. It writes nothing.

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
| `-v` | Adds debug logs on stderr: connection steps, timings and plan details, never credentials or user names. Each line starts with the time since BECK started. |
| `-q` | With `beck check`, prints only errors, deletions and how the run ended, including why `--fail-if-missing` failed. The deletion prompt still appears. It doesn't shorten `beck report` or `beck scan`, whose lists are what you asked for. |
| `--no-color` | The same as setting `NO_COLOR`. |
| `--json` | Prints one JSON document on stdout, and logs on stderr. It never asks anything. See [JSON output](#json-output). |
| `--config FILE` | Reads the settings from this file, not the default one. See [Settings](#settings). |

`-v` and `-q` can't be combined, and neither changes a `--json` document.

While hashing, a counter shows on stderr, but only on a terminal, and not with `-v`, `-q` or `--json`.

Colors follow `NO_COLOR`, then `FORCE_COLOR`, and otherwise appear only on a terminal. An empty value counts as not set.

A name can hold anything, so human output and logs show it safely. Bytes that aren't valid UTF-8, characters your terminal can't show,
control characters and the controls for the direction of text all appear escaped, like `x\xff.bin` or `new\x0aline.bin`, so a name can't
act on your terminal, or look like something else. `--json` keeps the exact name.

### Choosing what BECK works on

| Option | Commands | What it does |
|---|---|---|
| `--source DIR` | `check`, `scan` | Your folder of BIOS files. The default is `./bios`. Hidden files and folders are skipped. A folder you name must exist, or BECK exits with 2. |
| `--target URL` | `check`, `report` | An SMB target: `smb://[user@]host[:port]/share[/sub/path]`. The port defaults to 445. A URL with a password is refused, and the password in `config/config.yml` isn't used, so this means guest access until stage 07 adds passwords for targets. |
| `--target-dir DIR` | `check`, `report` | A folder: a mounted SD card or USB drive, or the device itself. It can't be combined with `--target`. |
| `--frontend NAME` | `check` | The kind of device. Only `recalbox`, for now. |
| `--report-file FILE` | `check`, `report` | Reads a local copy of the report, not the one on the target. `beck report` then needs no target, and can't take one. `beck check` still needs a target to upload to. |

All of these except `--report-file` can also come from [Settings](#settings). With no target anywhere, BECK uses the older
`config/config.yml`. A blank `user` or `passwd` there means guest access. A value that can't work, such as a `port` that isn't a number from
1 to 65535, exits with 2. Put a password made only of digits in quotes.

### Safety

| Option | What it does |
|---|---|
| `--overwrite` | Replaces files already on the device, including ones the report calls `INCORRECT`. There's no backup of what it replaces. See [Files already on the device](#files-already-on-the-device). |
| `--dry-run` | Shows the full plan, including what would be deleted, and changes nothing, locally or on the device. |
| `--move` | Deletes a local file once it's uploaded to **all** its targets and each remote size matches. If any upload of that file failed, the file stays. |
| `--clean-unmatched` | Deletes local files that matched nothing. Read the warning below first. |
| `--yes` | Confirms deletions without asking. Required when BECK can't ask. |
| `--fail-if-missing` | Exits with 5 if required files are still missing or incorrect after the run, and lists them. See [exit codes](#exit-codes). |

## Settings

Each setting comes from the first of these that has it:

1. a flag on the command line;
2. an environment variable;
3. the settings file;
4. BECK's default.

A target is one setting, whether it's a URL or a folder, so `--target-dir` beats `BECK_TARGET`, and `BECK_TARGET_DIR` beats a `url` in the
file. Two targets in the environment exit with 2, unless a flag decides.

| Variable | What it does |
|---|---|
| `BECK_CONFIG` | The settings file. |
| `BECK_TARGET` | The same as `--target`. |
| `BECK_TARGET_DIR` | The same as `--target-dir`. |
| `BECK_SOURCE` | The same as `--source`. |
| `BECK_SMB_USER` | The SMB user. Empty means a guest, even if the file names a user. A user in the target URL beats this. |

Any other empty variable counts as not set.

### The settings file

BECK reads the file named by `--config`, then the one named by `BECK_CONFIG`, then `config.toml` in the folder your system uses for settings:
`~/.config/beck/` on Linux. A file you name must exist, and the default one doesn't have to. A file that's broken stops every command with
exit code 2, and BECK lists all its problems at once. A setting it doesn't know is only a warning.

```toml
schema_version = 1                 # required

[target]
frontend = "recalbox"
url = "smb://recalbox.local/bios"  # or: dir = "/media/user/RECALBOX/bios", but not both

[smb]
user = ""                          # empty means a guest
timeout = 30                       # seconds

[source]
dir = "~/beck/bios"
```

A `dir` must be an absolute path or start with `~`, so that it means the same folder wherever you run BECK. **Passwords can't go in this
file:** BECK refuses one, in any setting and in a URL.

## What BECK deletes, and when

Without `--move` or `--clean-unmatched`, BECK never deletes or renames a local file (DEC-02).

With either of them, BECK lists the files and asks `Delete N files? [y/N]` on a terminal, on stderr. Without a terminal, as in scripts, agents and
CI, or with stdin or stderr closed, deleting requires `--yes`, and otherwise BECK exits with 2. `--json` never prompts, so it requires `--yes` too. A dry run deletes
nothing, even with these flags, and shows what would go. Every deletion is listed in the result.

These are never deleted:

- duplicates: they're kept and reported;
- files whose targets are already filled;
- hidden files, because they aren't scanned;
- a file that's valid for a target listed as `INCORRECT`, because it's the fix for that file;
- with `--move`, a file with a target that was already on the device and kept, because nothing proves that copy is good, or a file with
  any failed upload or a size that doesn't match;
- with `--clean-unmatched`, anything at all if something failed in the run, or if the report lists nothing missing.

BECK asks before uploading anything, so answering no leaves everything as it was, on both sides. Any answer but `y` or `yes` counts as
no, and BECK exits with 2.

> [!WARNING]
> "Unmatched" only means that the **current report** doesn't ask for that file. After you upload your files and scan again on the
> device, the report no longer lists them, so a later `--clean-unmatched` treats all your good BIOS files as unmatched and **deletes
> them**. Always run `beck check --dry-run --clean-unmatched` first, and read the list (DEC-56).

## Files already on the device

BECK keeps them unless you pass `--overwrite` (DEC-61):

- **Listed as missing, but the file is there:** this usually means the report is out of date, so the file may be fine. BECK reports
  `already on the device, kept`. Generate a new report, or use `--overwrite` to replace it.
- **Listed as `INCORRECT` by the report:** the file is on the device with a wrong hash. BECK reports it and tells you which local file
  would fit (DEC-54). `--overwrite` replaces it with that file, if you have one.

`--overwrite` reports `replaced`, not `copied`, so you can see what it overwrote. BECK keeps no copy of the old file, and a failed
upload can leave the old file damaged. Names that differ only in case count as the same file on SMB, as they do for Samba.

## Uploads that change a file's extension

BECK matches files by MD5, and uploads them under the name the report asks for. Sometimes that changes the extension: the real
Recalbox 10.1.1 report lists the same MD5 for `neocd/neocd.bin` and `neocdz.zip`, so a raw `.bin` can go up as a `.zip`. The MD5 is
valid, but an emulator may not be able to read the file.

BECK uploads the file anyway and prints a warning, in a dry run too. A difference in case alone, like `.BIN` and `.bin`, gets no
warning. Some targets have an unusual extension on purpose, like the Amiga `kick34005.A500`: there, a `.rom` file with the right MD5
gets the warning but is probably fine.

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
  because the device still can't use it. A file listed in several systems counts if any of them requires it.
- A file that was already on the device, and kept, doesn't count for `--fail-if-missing`, because it isn't missing. BECK goes by the report
  it read, and doesn't look on the device for a file it has no local copy of, so a report that's out of date can give 5. Generate a new one.
- With `--dry-run`, `--fail-if-missing` looks at what the same run would leave, so it exits with 5 if the real run would.
- If several apply, the transport error wins over `--fail-if-missing`, because the run didn't do all it could.
- What BECK does, and its exit code, don't depend on whether its output can be written (DEC-62). If you quit `beck check | less` early,
  the uploads still finish, and the exit code reports them. A closed pipe is silent, and any other failure, such as a full disk, prints one
  line on stderr. So with `--move --yes | head`, files can be deleted without you seeing the list.

## JSON output

`--json` prints a single JSON document on stdout, for every command and for errors that stop a run, so stdout can always be parsed.
It carries a `schema_version`, and is described by [JSON Schema files](schemas/). [JSON output](json-output.md) has every field. Only
`--help` and `--version` print text.

Within `schema_version` 1, fields are only ever added. Renaming or removing a field, or changing its meaning, needs `schema_version` 2.
Ignore fields you don't know.

**Reading the result:** branch on the exit code first, then read the document. `ok` is false when the exit code isn't 0.
