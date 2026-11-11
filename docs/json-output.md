# JSON output

For scripts and AI agents. With `--json`, BECK prints **one JSON document on stdout** and nothing else there. Logs go to stderr, `-v`
adds more of them, `-q` changes nothing, and it never asks a question. The option works before or after the command.

```sh
beck --json check --dry-run
beck --json report --report-file missing_bios_report.txt
beck --json scan --source ~/my-bios
beck --json config show
```

## How to read the result

1. Parse stdout. This works whatever happened, including a bad flag or a bug in BECK.
2. Branch on the [exit code](cli.md#exit-codes). `ok` is `false` whenever it isn't 0.
3. Read `errors` for what went wrong, and the other fields for what happened.

Exit code 5, from `--fail-if-missing`, has `ok` set to `false` and `errors` empty, because the run itself went fine. The files it's about are
in `still_missing` and `incorrect`, with `required` not `false`.

`--help` and `--version` print text, and a run stopped by Ctrl-C prints no document.

If stdout itself can't be written, the document is lost or cut short, but the run carries on, and the exit code still reports it
(DEC-62). A closed pipe is silent, and any other failure, such as a full disk, prints one line on stderr. So when you save the document to a
file, check that it parses.

## The compatibility promise

Within `schema_version` 1, fields are only ever **added**. Renaming or removing a field, or changing what it means, needs
`schema_version` 2.

- Ignore fields you don't know.
- Check `schema_version` before trusting anything else.
- New `errors[].code` values can appear within version 1, so treat an unknown code as a failure. `uploads[].status` won't get new
  values within version 1.

The [schemas](schemas/) describe each document. They allow extra fields on purpose, so that a newer BECK still validates.

| Document | Schema |
|---|---|
| `beck --json check` | [`check-result.v1.json`](schemas/check-result.v1.json) |
| `beck --json report` | [`report-result.v1.json`](schemas/report-result.v1.json) |
| `beck --json scan` | [`scan-result.v1.json`](schemas/scan-result.v1.json) |
| `beck --json export` | [`export-result.v1.json`](schemas/export-result.v1.json) |
| `beck --json config` | [`config-result.v1.json`](schemas/config-result.v1.json) |
| A command line BECK rejected | [`rejected-command.v1.json`](schemas/rejected-command.v1.json) |

## Fields in every document

| Field | Meaning |
|---|---|
| `schema_version` | `1`. |
| `beck_version` | The BECK that wrote this. |
| `command` | `check`, `report`, `scan` or `config`. `null` if the command line was rejected, because no command ran. That includes running `beck` with no command, which counted as `check` before 1.0. |
| `ok` | `true` only when the exit code is 0. |
| `errors[]` | What went wrong: `code`, `message` and `item`. See [Errors](#errors). A password in a message, which BECK doesn't put there itself, shows as `***`. |

## `beck --json check`

```json
{
  "schema_version": 1,
  "beck_version": "0.1.0",
  "command": "check",
  "ok": true,
  "dry_run": false,
  "frontend": "recalbox",
  "target": "smb://recalbox.local:445/bios",
  "summary": {
    "missing_entries": 3,
    "satisfied": 1,
    "still_missing": 2,
    "files_scanned": 1,
    "uploaded": 1,
    "duplicates": 0,
    "unmatched": 0,
    "deleted": 0,
    "errors": 0
  },
  "uploads": [
    {
      "source": "neocd.bin",
      "target": "neocd/neocd.bin",
      "md5": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "status": "uploaded",
      "replaces": false,
      "error": null,
      "warning": null
    }
  ],
  "incorrect": [],
  "still_missing": [
    {
      "name": "tos.img",
      "target": "atarist/tos.img",
      "md5s": ["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],
      "required": true
    },
    {
      "name": "neocdz.zip",
      "target": "neocdz.zip",
      "md5s": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
      "required": true
    }
  ],
  "not_a_zip": [
    {
      "path": "neocd.bin",
      "target": "neocdz.zip"
    }
  ],
  "duplicates": [],
  "already_filled": [],
  "unmatched": [],
  "unreadable": [],
  "deleted": [],
  "errors": []
}
```

Every field is always there. A run that stops early has empty lists and zero counts. Lists are sorted, so the same run gives the same
document.

| Field | Meaning |
|---|---|
| `dry_run` | Whether this was a dry run, which changes nothing. |
| `frontend` | The kind of device. |
| `target` | The target as a URL: `smb://host:port/share[/path]` or `file:///path`. It never has a user name or a password. `null` if BECK stopped before opening one. |
| `uploads[]` | One item per target with a local file for it. See below. |
| `incorrect[]` | Files on the device with a wrong hash, which stay as they are: `name`, `target`, `md5s`, `required` and `current_md5`, the hash of the file there, or `null` if the report doesn't give it. A local file in `unmatched` with an MD5 from `md5s` would fix one, with `--overwrite`. |
| `still_missing[]` | Targets with no matching local file: `name`, `target`, `md5s` and `required`. A target whose upload failed is in `uploads`, not here. |
| `not_a_zip[]` | Local files with an MD5 listed for a `.zip` target, which BECK didn't copy there because they aren't zip archives: `path`, and the `target`, which stays in `still_missing`. Recalbox hashes a `.zip` target by the files inside it, so a single file can have a listed MD5, but Recalbox can't read it under that name. Added in 1.0.1. |
| `duplicates[]` | Local files identical to one chosen instead, and kept: `path`, `of` and `md5`. |
| `already_filled[]` | Local files that matched, but other files fill all their targets: `path`, `md5` and `size`. |
| `unmatched[]` | Local files the report doesn't ask for: `path`, `md5` and `size`. That doesn't make them junk: read [the warning](cli.md#what-beck-deletes-and-when). |
| `unreadable[]` | Local files and folders BECK couldn't read and skipped: `path` and `reason`. This doesn't change the exit code. |
| `deleted[]` | Local files deleted, or in a dry run the ones that would be: `path`, `md5` and `size`. |

An entry listed in several systems of the report is one item here, with all its MD5s. `required` is `true` if any entry says so,
`false` if all say it's optional, and otherwise `null`, meaning the report doesn't say. Paths in `source` and `path` are relative to the
source folder, and paths in `target` are relative to the target's BIOS folder.

A local file name that isn't valid UTF-8 has its bad bytes as lone surrogates, so `bad-\xff.bin` on disk is `"bad-\udcff.bin"` here. In
Python, `os.fsencode` gets the real name back. Other JSON parsers may replace or refuse them, so check yours if your files have such
names.

### `uploads[]`

| Field | Meaning |
|---|---|
| `source` | The local file. |
| `target` | Where it goes. |
| `md5` | The file's MD5. |
| `status` | What happened. See below. |
| `replaces` | `true` if this overwrites a file on the target, or in a dry run would. |
| `error` | What went wrong with this upload, or `null`. |
| `warning` | Something to tell the user, or `null`. Today, that [the extension changes](cli.md#uploads-that-change-a-files-extension). |

| `status` | Meaning |
|---|---|
| `planned` | A dry run would upload this. |
| `uploaded` | Uploaded. |
| `replaced` | Uploaded over a file already there, which needs `--overwrite`. |
| `kept` | Not uploaded, because a file is already there. See [Files already on the device](cli.md#files-already-on-the-device). |
| `failed` | The upload failed, and `error` says why. |
| `skipped` | Not tried, because its folder couldn't be created. That failure is in `errors`, with the folder as its `item`. |

A `failed` upload may have left a damaged file on the target: `error` says so, and `--overwrite` tries again. A later run would otherwise keep that file.

### `summary`

| Field | Meaning |
|---|---|
| `missing_entries` | Targets the run set out to fill. One listed in several systems counts once, and `INCORRECT` files being kept don't count. |
| `satisfied` | Targets this run filled, or in a dry run would. A file that was already there and kept doesn't count. |
| `still_missing` | The length of `still_missing`. |
| `files_scanned` | Local files read. It's 0 if BECK had no reason to scan them, because nothing is missing. |
| `uploaded` | Uploads done, so always 0 in a dry run. |
| `duplicates`, `unmatched`, `deleted`, `errors` | The lengths of those lists. |

## `beck --json report`

Reads the report and changes nothing. `target` is `null` with `--report-file`.

```json
{
  "schema_version": 1,
  "beck_version": "0.1.0",
  "command": "report",
  "ok": true,
  "frontend": "recalbox",
  "target": null,
  "summary": { "missing": 1, "incorrect": 1 },
  "missing": [
    {
      "name": "tos.img",
      "target": "atarist/tos.img",
      "md5s": ["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],
      "required": true
    }
  ],
  "incorrect": [
    {
      "name": "scph1001.bin",
      "target": "scph1001.bin",
      "md5s": ["cccccccccccccccccccccccccccccccc"],
      "required": true,
      "current_md5": "dddddddddddddddddddddddddddddddd"
    }
  ],
  "errors": []
}
```

## `beck --json scan`

Hashes the local files. It uses no network and changes nothing.

```json
{
  "schema_version": 1,
  "beck_version": "0.1.0",
  "command": "scan",
  "ok": true,
  "summary": { "files": 1, "unreadable": 1 },
  "files": [
    { "path": "ps1/scph1001.bin", "md5": "cccccccccccccccccccccccccccccccc", "size": 524288 }
  ],
  "unreadable": [
    { "path": "broken-link.bin", "reason": "broken symlink" }
  ],
  "errors": []
}
```

## `beck --json export`

Copies the `.rom` and `.bin` files on the target to a local folder. It only reads the target, and never replaces a local file.

```json
{
  "schema_version": 1,
  "beck_version": "0.1.0",
  "command": "export",
  "ok": true,
  "dry_run": false,
  "target": "smb://recalbox.local:445/bios",
  "destination": "bios-backup",
  "summary": {
    "files_on_target": 5,
    "rom_and_bin": 3,
    "copied": 2,
    "planned": 0,
    "existing": 1,
    "failed": 0,
    "left_out": 2
  },
  "files": [
    { "path": "atari800/ATARIBAS.ROM", "size": 8192, "status": "copied", "error": null },
    { "path": "neocd/neocd.bin", "size": 524288, "status": "exists", "error": null },
    { "path": "ps1/scph1001.bin", "size": 524288, "status": "copied", "error": null }
  ],
  "errors": []
}
```

| Field | Meaning |
|---|---|
| `dry_run` | Whether this was a dry run, which writes nothing. |
| `target` | The target as a URL, as in `check`. `null` if BECK stopped before opening one. |
| `destination` | The local folder, as given. `null` if BECK stopped before reading the command line's folder. |
| `files[]` | Each `.rom` and `.bin` file on the target, in any case: `path`, relative to the target's BIOS folder and to `destination`, `size`, `status` and `error`. |
| `files[].status` | `planned` in a dry run; `copied`; `exists`, when a file is already at that path in `destination`, and was kept; or `failed`, with the reason in `error`, and in `errors`. |
| `summary.files_on_target` | Every file on the target. |
| `summary.rom_and_bin` | The length of `files`. |
| `summary.copied`, `planned`, `existing`, `failed` | How many `files` have each status. |
| `summary.left_out` | The files on the target that aren't `.rom` or `.bin`, so weren't exported. Some are BIOS files, such as `.zip` and `.img` ones, so an export isn't a complete backup. |

## `beck --json config`

`config path`, `config init` and `config show` all give this document. It connects to nothing.

```json
{
  "schema_version": 1,
  "beck_version": "0.1.0",
  "command": "config",
  "ok": true,
  "action": "show",
  "file": { "path": "/home/you/.config/beck/config.toml", "source": "default", "exists": true },
  "created": false,
  "settings": {
    "target": { "value": "smb://recalbox.local:445/bios", "source": "file" },
    "source": { "value": "/home/you/beck/bios", "source": "file" },
    "frontend": { "value": "recalbox", "source": "file" },
    "smb_user": { "value": "", "source": "file" },
    "smb_password": { "value": "not set", "source": "default" },
    "smb_timeout": { "value": 30, "source": "file" }
  },
  "errors": []
}
```

| Field | Meaning |
|---|---|
| `action` | `path`, `init` or `show`. |
| `file` | The settings file: its `path`, `exists`, and `source`, which says why this one: `flag`, `environment` or `default`. It's `null` only if a bug stopped BECK before it knew. |
| `created` | `true` if this run wrote the file, which only `init` does. |
| `settings` | What a run would use, each with its `value` and its `source`: `flag`, `environment`, `file` or `default`. It's `null` unless the action is `show` and the file could be read. |
| `settings.target` | The target as a URL, with no user name or password, or `null` if nothing names one. |
| `settings.smb_user` | The SMB user, which is empty for a guest. This is the one place a document names the user. |
| `settings.smb_password` | Only `set` or `not set`, never the password. |

## Errors

An error that **stops the run** has `item` set to `null`, and the document has the same shape as a successful one, with empty lists and
zero counts. Nothing was uploaded or deleted, except with `internal`: a bug can stop a run partway, and the empty lists don't prove
that nothing happened.

An error about **one item** doesn't stop the run. `item` names the target, folder or local file.

| `code` | Exit code | Stops the run? | Meaning |
|---|---|---|---|
| `usage` | 2 | Yes | A bad flag, URL or folder, or a deletion that wasn't confirmed. |
| `config` | 2 | Yes | The settings are missing or invalid, there's no target, or a user has no password. `--json` never asks for one, so set `BECK_SMB_PASSWORD`. |
| `transport` | 3 | Yes, if `item` is `null` | Couldn't connect or log in, or one upload, folder or check failed. |
| `report_not_found` | 4 | Yes | There's no report, so generate one on the device. |
| `report_parse` | 4 | Yes | BECK can't read the report. |
| `size_mismatch` | 3 | No | The size of an upload on the target doesn't match, so the upload is `failed`, and with `--move` the local file stays. With `export`, a file read from the target didn't have the size it was listed with, and nothing was written. |
| `md5_mismatch` | 3 | No | With `--verify`, the MD5 of an upload on the target doesn't match. It's handled the same way. |
| `delete_failed` | 3 | No | A local file couldn't be deleted. |
| `unsafe_path` | 3 | No | A report entry isn't safe to act on, so it was refused. `item` is its name. `beck --json report` can have it too. With `export`, a folder in the destination is a link, which export doesn't follow. |
| `write_failed` | 3 | No | With `export`, a local file or folder couldn't be written. `item` is the file's path. |
| `internal` | 1 | Yes | A bug in BECK. The details are on stderr, and they aren't in the document because they could hold anything. Please report it. |

A rejected command line is the one case with fewer fields, because no command ran:

```json
{
  "schema_version": 1,
  "beck_version": "0.1.0",
  "command": null,
  "ok": false,
  "errors": [
    { "code": "usage", "message": "unrecognized arguments: --no-such-flag", "item": null }
  ]
}
```

## Deleting

`--json` never asks. If the run would delete anything, `--move` and `--clean-unmatched` need `--yes`, or BECK exits with 2 and changes
nothing. Run with `--dry-run` first, and read `deleted`.
