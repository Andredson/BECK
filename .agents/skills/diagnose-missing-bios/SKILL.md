---
name: diagnose-missing-bios
description: Help someone find out why their Recalbox still reports BIOS files as missing, and copy the ones they have, using BECK's dry run and JSON output. Use when a user asks why a BIOS file is missing, or asks you to run BECK on their files.
license: GPL-3.0-only
compatibility: Needs the beck command, and the Recalbox or a copy of its report. Reaching the Recalbox needs the user's network.
---

# Diagnose missing BIOS files

This is for helping someone use BECK, not for changing its code. [Using BECK as a tool](../../../AGENTS.md#using-beck-as-a-tool) has the rules, and [the JSON guide](../../../docs/json-output.md) has every field.

## When to use

A user asks why a BIOS file is missing, or asks you to check or copy their BIOS files.

## Inputs you need from the human

- **Their BIOS folder.**
- **Which device,** as a URL, a mounted folder, or a copy of the report. A dry run connects to the target, so use only one they named. `beck --json config show` says what the settings name.
- **Never a password.** Don't ask for one, and don't put one in a command or in `BECK_SMB_PASSWORD` yourself. If they paste one, don't repeat it, and tell them to change it. They can set the variable in their own terminal, or run BECK themselves so that it asks: [Passwords](../../../docs/cli.md#passwords) says how.

## Steps

1. **Make sure the report is recent.** Ask them to [generate it again](../../../docs/user-guide/generate-report.md) if they've added files since, or aren't sure.
2. **Look first, with a dry run.** It changes nothing. Add `--target` or `--target-dir` if they named one:

   ```sh
   beck --json check --dry-run --source <their folder>
   ```

   If `beck` isn't found, [install it](../../../README.md#install), or inside this repository use `uv run beck`. Don't work out the result some other way and call it BECK's. Stdout holds one JSON document, even for an error. Check that `schema_version` is `1`, and use [the exit code](references/exit-codes.md) to decide what to do. If it isn't 0, read `errors`, explain using [the troubleshooting guide](../../../docs/troubleshooting.md), and stop.
3. **Explain the plan in plain words.** Don't paste the JSON. Say:
   - which files would go where, from `uploads`, and pass on any `warning`;
   - which would replace a file, from `replaces`;
   - what's on the device with the wrong content, from `incorrect`;
   - what's still missing, from `still_missing`, starting with `required: true`. `false` means optional, and `null` means the report doesn't say;
   - which files weren't copied because their `.zip` target needs a zip archive, from `not_a_zip`;
   - which files couldn't be read, from `unreadable`.
4. **For each file still missing, or the one they asked about, find the likely reason:**

   | What you see | Likely reason | What to tell them |
   |---|---|---|
   | In `still_missing`, and a file with the same name in `unmatched` | Right name, wrong content: another dump, region or version. BECK goes by the MD5, not the name. | Compare its `md5` with the entry's `md5s`. Their file isn't the one Recalbox wants. |
   | In `still_missing`, and a `.zip` in `unmatched` | BECK looked inside it too, and nothing in it matched. For a `.zip` target, its `contents_md5` in `beck --json scan` isn't on the list: it holds other files or versions. | Compare `beck --json scan` with the entry's `md5s`. An archive in `unreadable` wasn't opened: damaged, or over the limits. |
   | In `still_missing`, and in `not_a_zip` | The target is a `.zip`, and their file is one of the files inside it, on its own. Recalbox can't read it under the zip's name. | They need that BIOS as a zip archive. |
   | In `still_missing`, and another file in `unmatched` | The name may differ, but so does the content, so it isn't this file. | They don't have a file with this content in that folder. |
   | In `still_missing`, and nothing else fits | There's no copy in that folder. | Check the folder. `beck --json scan --source <folder>` lists what BECK sees, and hidden files are skipped. |
   | In `unreadable` | BECK couldn't read that file or folder. | Give the `reason`, such as a permission or a broken link. |
   | In `incorrect` | The device has that file, with the wrong content. | BECK keeps it. Replacing it takes `--overwrite`, and it's their choice. |
   | In `uploads` with `status: kept` | It's on the device already, so the report is probably out of date. | Generate the report again. |
   | In `uploads` with `status: planned` | They have the file, and it hasn't been copied yet. | The real run would copy it. |
   | In `uploads` with `failed` or `skipped` | The copy failed. | Give its `error`, or the matching item in `errors`. |
   | In no list | The report doesn't ask for it. | Check the name, and generate the report again. |

   These are likely reasons, so say so. `unmatched` doesn't mean junk: a good BIOS file can be there because the report doesn't ask for it right now.
5. **Ask before copying.** Show what the real run would do, and wait for a clear yes to that. "Sort it out" or "fix it" asked you to look, not to copy.
6. **After a yes, run the same command without `--dry-run`.** Report what happened, from each upload's `status` and from `errors`, and check the exit code before running it again.
7. **Ask them to scan the BIOS files on the Recalbox** to see the result. BECK can't do that for them.

## Verify

- You ran a dry run before any real run, and the real run was approved.
- What you said matches the document, and you told them what's still missing.
- No password appears in anything you wrote or ran.

## Never do

- **Say where to get a BIOS file,** download one, or ask them to send you one. They're copyrighted, and BECK only matches files people already have.
- **Run without `--dry-run`** before they've approved it.
- **Add `--move`, `--clean-unmatched`, `--overwrite` or `--yes`** unless they asked for that exact flag, for this run. Do a dry run with it first, and show them `deleted` and `replaces`. `--overwrite` keeps no copy, `--move` deletes local files, and `--clean-unmatched` [can delete good BIOS files](../../../docs/cli.md#what-beck-deletes-and-when). `--json` never asks, so `--yes` would be confirming on their behalf.
- **Answer a refused deletion by adding `--yes`.**
- **Ask for a password in the chat,** or pass one on a command line.
- **Use a target they didn't name.**
