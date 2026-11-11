# Command reference

What `beck --help` and each command's `--help` print.
[The guide to the `beck` command](cli.md) explains how to use them.

This file is generated, so don't edit it by hand. After changing a flag or its help, run
`uv run python scripts/gen_cli_reference.py`.

## `beck`

```text
usage: beck [-h] [--version] [-v] [-q] [--no-color] [--config FILE] [--json] <command> ...

Match your BIOS files by MD5 and send them to the right folder on your Recalbox.

options:
  -h, --help     show this help message and exit
  --version      show program's version number and exit
  -v             add debug logs on stderr: steps, timings and the plan, never credentials
  -q             with check, print only errors, deletions and how the run ended
  --no-color     don't use colors, the same as setting NO_COLOR
  --config FILE  read the settings from this file, not the default one (see docs/cli.md)
  --json         print one JSON document on stdout, and never ask anything (see docs/json-
                 output.md)

commands:
  <command>
    check        Copy your matching BIOS files to the device.
    scan         List your local BIOS files with their MD5s.
    report       List the BIOS files the device reports as missing.
    export       Copy the .rom and .bin files on the device to a folder here.
    config       Find, create or show BECK's settings.

examples:
  beck check                  copy the matching files to your device
  beck scan                   list your local files and their MD5s
  beck report                 list what your device is missing
  beck export ~/bios-backup   copy the .rom and .bin files on your device to a folder
  beck config init            create a settings file

See docs/cli.md for every option, the exit codes, and what gets deleted.
```

## `beck check`

```text
usage: beck check [-h] [-v] [-q] [--no-color] [--config FILE] [--json] [--source DIR] [--target URL
                  | --target-dir DIR] [--report-file FILE] [--overwrite] [--dry-run] [--move]
                  [--clean-unmatched] [--yes] [--verify] [--fail-if-missing] [--frontend NAME]

Copy your matching BIOS files to the device.

options:
  -h, --help          show this help message and exit
  -v                  add debug logs on stderr: steps, timings and the plan, never credentials
  -q                  with check, print only errors, deletions and how the run ended
  --no-color          don't use colors, the same as setting NO_COLOR
  --config FILE       read the settings from this file, not the default one (see docs/cli.md)
  --json              print one JSON document on stdout, and never ask anything (see docs/json-
                      output.md)
  --source DIR        your folder of BIOS files (default: ./bios)
  --target URL        an SMB target: smb://[user@]host[:port]/share[/sub/path]
  --target-dir DIR    a folder: a mounted SD card or USB drive, or the device itself
  --report-file FILE  read this local copy of the report, not the one on the target
  --overwrite         replace files already on the device, even ones the report calls INCORRECT
  --dry-run           show the plan, including what would be deleted, and change nothing
  --move              delete a local file once it's uploaded to all its targets and sizes match
  --clean-unmatched   delete local files the current report doesn't ask for (read docs/cli.md)
  --yes               confirm deletions without asking
  --verify            read each upload back and compare its MD5, which is slower
  --fail-if-missing   exit with 5 if required files are still missing or incorrect after the run
  --frontend NAME     the kind of device (default: recalbox)

example:
  beck check
```

## `beck scan`

```text
usage: beck scan [-h] [-v] [-q] [--no-color] [--config FILE] [--json] [--source DIR]

List your local BIOS files with their MD5s.

options:
  -h, --help     show this help message and exit
  -v             add debug logs on stderr: steps, timings and the plan, never credentials
  -q             with check, print only errors, deletions and how the run ended
  --no-color     don't use colors, the same as setting NO_COLOR
  --config FILE  read the settings from this file, not the default one (see docs/cli.md)
  --json         print one JSON document on stdout, and never ask anything (see docs/json-
                 output.md)
  --source DIR   your folder of BIOS files (default: ./bios)

example:
  beck scan
```

## `beck report`

```text
usage: beck report [-h] [-v] [-q] [--no-color] [--config FILE] [--json] [--target URL | --target-dir
                   DIR | --report-file FILE]

List the BIOS files the device reports as missing.

options:
  -h, --help          show this help message and exit
  -v                  add debug logs on stderr: steps, timings and the plan, never credentials
  -q                  with check, print only errors, deletions and how the run ended
  --no-color          don't use colors, the same as setting NO_COLOR
  --config FILE       read the settings from this file, not the default one (see docs/cli.md)
  --json              print one JSON document on stdout, and never ask anything (see docs/json-
                      output.md)
  --target URL        an SMB target: smb://[user@]host[:port]/share[/sub/path]
  --target-dir DIR    a folder: a mounted SD card or USB drive, or the device itself
  --report-file FILE  read this local copy of the report, not the one on the target

example:
  beck report
```

## `beck export`

```text
usage: beck export [-h] [-v] [-q] [--no-color] [--config FILE] [--json] [--target URL | --target-dir
                   DIR] [--dry-run] DIR

Copy every .rom and .bin file in the device's BIOS folder to DIR, in the same folders. It never
replaces a file in DIR, and changes nothing on the device.

It isn't a complete backup: BIOS files of other kinds, such as .zip, .img or the Amiga kick files,
are left out, and so are .rom and .bin files that aren't BIOS files. The result says how many it
left. These are real BIOS files, so never commit them to a git repository.

positional arguments:
  DIR               the folder to copy them to, created if needed

options:
  -h, --help        show this help message and exit
  -v                add debug logs on stderr: steps, timings and the plan, never credentials
  -q                with check, print only errors, deletions and how the run ended
  --no-color        don't use colors, the same as setting NO_COLOR
  --config FILE     read the settings from this file, not the default one (see docs/cli.md)
  --json            print one JSON document on stdout, and never ask anything (see docs/json-
                    output.md)
  --target URL      an SMB target: smb://[user@]host[:port]/share[/sub/path]
  --target-dir DIR  a folder: a mounted SD card or USB drive, or the device itself
  --dry-run         show what would be copied, and write nothing

example:
  beck export ~/bios-backup --dry-run
```

## `beck config`

```text
usage: beck config [-h] [-v] [-q] [--no-color] [--config FILE] [--json] <action> ...

Find, create or show BECK's settings.

options:
  -h, --help     show this help message and exit
  -v             add debug logs on stderr: steps, timings and the plan, never credentials
  -q             with check, print only errors, deletions and how the run ended
  --no-color     don't use colors, the same as setting NO_COLOR
  --config FILE  read the settings from this file, not the default one (see docs/cli.md)
  --json         print one JSON document on stdout, and never ask anything (see docs/json-
                 output.md)

actions:
  <action>
    path         print which settings file BECK reads, and why
    init         create that settings file
    show         print the settings a run would use, and where each comes from

example:
  beck config show
```

## `beck config path`

```text
usage: beck config path [-h] [-v] [-q] [--no-color] [--config FILE] [--json]

print which settings file BECK reads, and why

options:
  -h, --help     show this help message and exit
  -v             add debug logs on stderr: steps, timings and the plan, never credentials
  -q             with check, print only errors, deletions and how the run ended
  --no-color     don't use colors, the same as setting NO_COLOR
  --config FILE  read the settings from this file, not the default one (see docs/cli.md)
  --json         print one JSON document on stdout, and never ask anything (see docs/json-
                 output.md)
```

## `beck config init`

```text
usage: beck config init [-h] [-v] [-q] [--no-color] [--config FILE] [--json] [--force]

create that settings file

options:
  -h, --help     show this help message and exit
  -v             add debug logs on stderr: steps, timings and the plan, never credentials
  -q             with check, print only errors, deletions and how the run ended
  --no-color     don't use colors, the same as setting NO_COLOR
  --config FILE  read the settings from this file, not the default one (see docs/cli.md)
  --json         print one JSON document on stdout, and never ask anything (see docs/json-
                 output.md)
  --force        replace a file that's already there
```

## `beck config show`

```text
usage: beck config show [-h] [-v] [-q] [--no-color] [--config FILE] [--json]

print the settings a run would use, and where each comes from

options:
  -h, --help     show this help message and exit
  -v             add debug logs on stderr: steps, timings and the plan, never credentials
  -q             with check, print only errors, deletions and how the run ended
  --no-color     don't use colors, the same as setting NO_COLOR
  --config FILE  read the settings from this file, not the default one (see docs/cli.md)
  --json         print one JSON document on stdout, and never ask anything (see docs/json-
                 output.md)
```
