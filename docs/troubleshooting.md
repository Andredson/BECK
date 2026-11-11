# Troubleshooting

Find what BECK printed, then see why and what to do. Each entry gives the [exit code](cli.md#exit-codes), and with `--json`, the `code` in [`errors`](json-output.md#errors).

To see each step BECK takes, add `-v`. It never shows your password. In these messages, `<...>` stands for what changes each time.

## Reaching your Recalbox

### It can't find `recalbox.local`

```text
Error: Error connecting to SMB server recalbox.local: <what your system says>
```

**Exit code 3,** `transport`. On Linux, your system says `Name or service not known`. Wording differs on other systems.

- **Cause:** your computer can't turn that name into an address. Names ending in `.local` need a service your computer or network may not have, which is common on Windows.
- **Fix:** use your Recalbox's IP address, which it shows in its network settings. Run `beck config path` to find your settings, and change `url`, as in `smb://192.168.1.20/bios`.

### The connection is refused, or times out

```text
Error: Error connecting to SMB server <address>: [Errno 111] Connection refused
Error: Timed out connecting to SMB server <address>
```

**Exit code 3,** `transport`.

- **Cause:** nothing is answering at that address. Your Recalbox may be off or on another network, the address may have changed, or the SMB shares may be off. A firewall can do this too.
- **Fix:** check that your Recalbox is on, and on the same network as your computer. Check its address, and open the share in a file manager to rule out BECK. On a slow network, raise `timeout` under `[smb]` in your settings.

### The share doesn't exist

```text
Error: The share <share> doesn't exist on SMB server <address>
```

**Exit code 3,** `transport`.

- **Cause:** the first part of the URL's path is the share's name, and the server doesn't have one by that name.
- **Fix:** on a Recalbox, it's `bios`, as in `smb://recalbox.local/bios`.

### The login is refused

```text
Error: SMB server <address> refused the login: check the user and password
```

**Exit code 3,** `transport`.

- **Cause:** the user or the password is wrong, or the server wants a guest.
- **Fix:** a Recalbox allows guests by default, so try with `user = ""` under `[smb]` in your settings. Otherwise, check the user, and `BECK_SMB_PASSWORD` if you set it. `beck config show` says which user BECK is using, where that came from, and whether a password is set.

### There's a user but no password

```text
Error: A user is set, but no password, and BECK can't ask for one here. Set BECK_SMB_PASSWORD, or run BECK on a terminal without --json.
```

**Exit code 2,** `config`.

- **Cause:** BECK only asks on a terminal, and `--json` never asks.
- **Fix:** run it on a terminal, set `BECK_SMB_PASSWORD`, or if you don't need a login, set `user = ""`.

### No password was given

```text
Error: Nothing was changed, because no password was given.
```

**Exit code 2,** `config`. You pressed Ctrl-C or Ctrl-D at the question. Run it again when you're ready.

## The report

### There's no report

```text
Error: missing_bios_report.txt not found on <target>. Generate the report on the device first.
Error: Can't read the report <file>: <what your system says>
```

**Exit code 4,** `report_not_found`.

- **Cause:** the report hasn't been generated, BECK is looking at the wrong device, or the file you named with `--report-file` isn't there.
- **Fix:** [generate the report](user-guide/generate-report.md). `beck config show` says which target BECK is using.

### BECK can't read the report

```text
Error: This doesn't look like a report: it has no MISSING BIOS REPORT title
Error: No MD5 value in report block: <the block's first line>
Error: No Path line in report block: <the block's first line>
Error: Unrecognized heading in the report: <the heading>
```

**Exit code 4,** `report_parse`.

- **Cause:** the file isn't a report, it's been cut short or edited, or a Recalbox version writes it differently. BECK stops rather than guess, so nothing is uploaded.
- **Fix:** generate the report again. If it still happens, your Recalbox version may have changed the format, so please open an issue with the version, and the lines around the one it names.

### An entry in the report is refused

```text
Error: Refused <name>: <why>
```

**Exit code 3,** `unsafe_path`. The other entries still go ahead.

- **Cause:** that entry could write outside the BIOS folder, or it holds a backslash, a control character, or a byte that wasn't valid text. So the report may be damaged, or someone may have crafted it.
- **Fix:** generate the report again. If the same name comes back, please open an issue. `--clean-unmatched` deletes nothing while this happens.

## Your files

### A file doesn't match

```text
<file>: no match, kept
```

**Exit code 0:** it's not an error, and your file stays where it is.

- **Cause:** its MD5 isn't one the report asks for. BECK doesn't look at names, only at what's inside. It may be a different dump or region, or a different version. It may also be inside a `.zip`, because BECK compares the file itself and doesn't look inside. The report may just not want it, because nothing asks for that file.
- **Fix:** see what you have with `beck scan`, and what's wanted in the report's `Possible MD5 List`. Unzip it if the report wants the file inside. Some targets are zips themselves, such as `neogeo.zip`, and there the zip's own MD5 has to match.

### A file is kept for another reason

```text
<file>: duplicate of <other file>, kept
<file>: target already filled, kept
<file>: valid for <target>, which is incorrect on the device, kept
```

**Exit code 0.** BECK needs only one copy of a file, and a target needs only one file. For the last one, see [the next entry](#a-file-is-already-on-your-recalbox).

### A file is already on your Recalbox

```text
<file>: already on the device, kept -> <target>
INCORRECT: <target> is on the device with a wrong MD5, and was kept
```

**Exit code 0.** BECK doesn't replace a file unless you ask.

- **Cause:** the first means the report says it's missing but it's there, so the report is probably out of date. The second means your Recalbox says that file has the wrong content.
- **Fix:** [generate the report again](user-guide/generate-report.md). To replace the file, add `--overwrite`, but BECK keeps no copy of what it replaces.

### A warning about an extension

```text
Warning: <file> has a different extension from <target>. The MD5 matches, but an emulator may not be able to read it.
```

**Exit code 0.** The MD5 is right, so BECK uploads it under the name the report asks for. If the emulator can't use it, find the file in the form the target's name suggests.

### There are no files, or a folder is wrong

```text
No BIOS files found in <folder>
Error: The source folder <folder> doesn't exist
<file>: can't be read, skipped: <why>
```

The first and last are **exit code 0**, and the second is **exit code 2,** `usage`.

- **Cause:** the folder is empty or isn't there, or a file is unreadable or is a broken link. Hidden files and folders are skipped.
- **Fix:** create the folder and put your files there, or change `dir` under `[source]`. `beck scan` shows what BECK finds.

### A name looks odd

BECK shows anything that could act on your terminal in an escaped form, like `bad-\xff.bin`, and a password as `***`. It's only how the name is shown. `--json` keeps the exact name.

## Uploading

### Permission denied, or the device refuses

```text
Error: Error creating folder <folder>: [Errno 13] Permission denied: '<path>'
Error: Error copying <file> to <target>: [Errno 13] Permission denied: '<path>'
Error: Error uploading <file> to <target> on share <share>: Failed to store <target> on <share>: Unable to open file
```

**Exit code 3,** `transport`. Other uploads carry on, and with `--move`, this file stays.

- **Cause:** you can't write there. The share may be read-only, or the login may not allow it, or a mounted SD card may be read-only.
- **Fix:** check the share's settings on your device, or log in as a user who can write. A file listed as `skipped` wasn't tried, because its folder couldn't be created.

### An upload doesn't match on your Recalbox

```text
Error: <target> has <n> bytes on the target, not <n>. To try again, use --overwrite.
Error: <target> has a different MD5 on the target. To try again, use --overwrite.
```

**Exit code 3,** `size_mismatch` or `md5_mismatch`, the second only with `--verify`.

- **Cause:** what arrived isn't what was sent. The connection may have failed, the device may be full, or your file may have changed while BECK was running.
- **Fix:** the damaged file is still on your Recalbox, and a later run would keep it, so run it again with `--overwrite`. Your local file stays.

## Deleting

### It would delete and can't ask

```text
Error: BECK would delete <n> local files, and can't ask here. Nothing was changed. To see them, use --dry-run. To confirm, use --yes.
Error: Nothing was changed, because you didn't confirm the deletion.
```

**Exit code 2,** `usage`.

- **Cause:** without a terminal, or with `--json`, BECK can't ask. Or you answered something other than `y`.
- **Fix:** look at the list with `--dry-run`, and read [what gets deleted](cli.md#what-beck-deletes-and-when). Add `--yes` only if you're sure.

### A file can't be deleted

```text
Error: Couldn't delete <file>: <what your system says>
```

**Exit code 3,** `delete_failed`. The upload worked, and the file stays. Check that you can write to that folder.

## Settings and the command line

### There's no target

```text
Error: BECK has no target. Use --target or --target-dir, set BECK_TARGET or BECK_TARGET_DIR, or name one in the settings file: to create it, run beck config init.
```

**Exit code 2,** `config`. Run `beck config init`, which names the usual Recalbox.

### The settings file has problems

```text
Error: <file> has problems: <each problem, with its setting>
Error: <file> not found
Error: <file> has schema_version <n>, and this BECK reads up to 1. Upgrade BECK.
Error: <file> isn't valid TOML: <where>
```

**Exit code 2,** `config`. Every command stops until it's fixed.

- **Fix:** the message names each setting. `beck config path` finds the file, and works even when it's broken. To start again, run `beck config init --force`, which replaces it. A password can't go in the file: BECK asks for it, or set `BECK_SMB_PASSWORD`.

### Warnings about the settings file

```text
<file>: ignoring the unknown setting <setting>
<file>: other users can read this file. To stop them, run: chmod 600 <file>
<old file> isn't read any more. To keep these settings, put this in <file>, and then delete the old file:
```

**Exit code 0,** so far. The first is probably a typo. The last means you still have the old `config/config.yml`: delete it once you've moved your settings, because it may hold your password in plain text.

### A flag or URL is wrong

```text
beck: error: unrecognized arguments: <what you typed>
beck: error: the following arguments are required: <command>
Error: The target must start with smb://. Use smb://[user@]host[:port]/share[/sub/path]
Error: The target can't contain a password: anyone can read a command line. Use smb://[user@]host[:port]/share[/sub/path], and BECK asks for the password, or set BECK_SMB_PASSWORD.
Error: Unknown frontend '<name>'. Known frontends: recalbox
```

**Exit code 2,** `usage`. Check the spelling, and [the guide to the command](cli.md). The second means you ran `beck` with no command: since 1.0, it needs one, such as `beck check`, which is what plain `beck` used to run. If you typed a password into a command, it may be in your shell's history, so change it.

## Other exit codes

### Exit code 5

```text
MISSING: <target>
Required files still missing or incorrect: <n>. Exit code 5, because of --fail-if-missing.
```

You asked for this with `--fail-if-missing`: required files are still missing, and BECK has done what it could. Find those files, or leave the flag out if a missing file isn't a failure for you.

### Exit code 1

```text
Unexpected error
Traceback (most recent call last):
```

**Exit code 1,** `internal`. It's a bug in BECK, so please open an issue with the traceback, which goes to stderr. Any password it knows is hidden, but read it before you share it. A run can stop partway because of a bug, so check what's on your Recalbox.

## On Windows

BECK isn't tested on Windows or macOS yet, so messages from your system will read differently, and something may simply not work. Please open an issue if it doesn't.

- **Long paths:** Windows can limit a path to 260 characters. Move your BIOS folder somewhere with a short path, such as `C:\beck\bios`.
- **Paths in settings:** in `config.toml`, write a Windows path with forward slashes, as in `dir = "C:/beck/bios"`, or double each backslash.
- **`recalbox.local`:** this is the most likely name not to work, so [use the IP address](#it-cant-find-recalboxlocal).
