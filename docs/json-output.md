# JSON output

For scripts and AI agents. With `--json`, BECK prints **one JSON document on stdout** and nothing else there. Logs go to stderr, `-v`
adds more of them, `-q` changes nothing, and it never asks a question. The option works before or after the command.

```sh
beck --json check --dry-run
beck --json report --report-file missing_bios_report.txt
beck --json scan --source ~/my-bios
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
| A command line BECK rejected | [`rejected-command.v1.json`](schemas/rejected-command.v1.json) |

## Fields in every document

| Field | Meaning |
|---|---|
| `schema_version` | `1`. |
| `beck_version` | The BECK that wrote this. |
| `command` | `check`, `report` or `scan`. `null` if the command line was rejected, because no command ran. Running `beck` with no command counts as `check`. |
| `ok` | `true` only when the exit code is 0. |
| `errors[]` | What went wrong: `code`, `message` and `item`. See [Errors](#errors). |

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
    "satisfied": 2,
    "still_missing": 1,
    "files_scanned": 2,
    "uploaded": 2,
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
    },
    {
      "source": "neocd.bin",
      "target": "neocdz.zip",
      "md5": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "status": "uploaded",
      "replaces": false,
      "error": null,
      "warning": "neocd.bin has a different extension from neocdz.zip. The MD5 matches, but an emulator may not be able to read it."
    }
  ],
  "incorrect": [],
  "still_missing": [
    {
      "name": "tos.img",
      "target": "atarist/tos.img",
      "md5s": ["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],
      "required": true
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

An `uploaded` item can still have an `error`: with `--move`, the size on the target may not match, and then the local file stays.

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

## Errors

An error that **stops the run** has `item` set to `null`, and the document has the same shape as a successful one, with empty lists and
zero counts. Nothing was uploaded or deleted, except with `internal`: a bug can stop a run partway, and the empty lists don't prove
that nothing happened.

An error about **one item** doesn't stop the run. `item` names the target, folder or local file.

| `code` | Exit code | Stops the run? | Meaning |
|---|---|---|---|
| `usage` | 2 | Yes | A bad flag, URL or folder, or a deletion that wasn't confirmed. |
| `config` | 2 | Yes | The settings are missing or invalid. |
| `transport` | 3 | Yes, if `item` is `null` | Couldn't connect or log in, or one upload, folder or check failed. |
| `report_not_found` | 4 | Yes | There's no report, so generate one on the device. |
| `report_parse` | 4 | Yes | BECK can't read the report. |
| `size_mismatch` | 3 | No | With `--move`, the size on the target doesn't match, so the local file stays. |
| `delete_failed` | 3 | No | A local file couldn't be deleted. |
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
