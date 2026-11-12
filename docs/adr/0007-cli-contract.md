# ADR-0007 — The CLI contract

- **Status:** Accepted
- **Date:** 2026-11-05
- **Decisions covered:** DEC-59, DEC-62, DEC-64, DEC-70, DEC-74, DEC-78, DEC-80. The rest of the contract follows from DEC-02, DEC-05, DEC-17, DEC-23 and DEC-54 (rows in the
  [decision log](../../roadmap/README.md#decision-log)).

## Context
BECK is meant to be driven by people, scripts and AI agents. The last two can't read human output reliably, so what they depend on has
to be stable: the exit codes and the JSON output. [docs/cli.md](../cli.md) is the user reference, and this ADR records why.

## Decision

### Exit codes are a contract
Codes 0 to 5 have fixed meanings, listed in [docs/cli.md](../cli.md#exit-codes), and each `BeckError` subclass has a fixed code. A
script can branch on the code without parsing anything. Changing a code's meaning is a breaking change.

Exit 0 means that the run completed, not that nothing is missing. A device can legitimately still miss files the user doesn't own, so
failing on that is opt-in, with `--fail-if-missing`.

### JSON is one document on stdout
With `--json`, stdout has exactly one JSON document, including for errors that stop a run, and everything else goes to stderr. A
consumer can parse stdout without checking anything first.

### The compatibility promise
Within `schema_version` 1, fields are only added. Renaming, removing or changing the meaning of a field means `schema_version` 2.
Consumers must ignore unknown fields. Contract tests enforce this (step 06.8), and agents must ask the owner before changing an
existing field.

### Details settled in step 06.7
The roadmap listed the main fields. Building them raised these details, which the agent settled and reported to the owner:

- **JSON never knows less than the human output.** So it has `uploads[].replaces`, because a dry run's `planned` can't show that an upload
  would overwrite a file, and `already_filled[]` and `unreadable[]`, because otherwise those files would vanish from the result.
- **List items are objects, not strings,** even when one field would do, so that fields can be added within version 1.
- **One item per target,** with its MD5s merged, because a file listed in several systems is one file to find. That's the rule `beck report`
  already uses for people.
- **`target` is a URL with no user name** as well as no password, built by a new `Transport.url()`. `describe()` stays a sentence for
  messages.
- **A command line BECK can't parse still gives a document,** with only the common fields and `command: null`, because no command ran.
  It has its own schema, a fourth one. BECK looks for `--json` before parsing, since parsing is what failed.
- **A bug's message stays on stderr,** because it could hold anything, including a password.
- **The schemas allow extra fields,** so that a newer BECK still validates against them.

### Details settled in step 06.9
Testing the table against the real command raised these details, which the agent settled and reported to the owner:

- **A file already on the device doesn't count for `--fail-if-missing`.** It isn't missing, and an out-of-date report is the usual reason
  for it. Otherwise, running `beck check --fail-if-missing` twice would fail the second time, after a first run that worked. The cost is that
  nothing proves the kept file is good, which a new report would show. The same goes the other way: BECK goes by the report, so a target
  with no local copy counts as missing even if a report out of date is wrong about that.
- **A dry run predicts.** `--dry-run --fail-if-missing` exits with 5 if the real run would, because a dry run's job is to preview it.
- **Exit 5 isn't an item in `errors`.** The run went fine, and an item there would need a new code. So `ok` is `false`, `errors` is empty,
  and the files are in `still_missing` and `incorrect`.
- **Exit 1 means a bug, so a user's mistake never gets it.** A config file that can't be read, or a value of the wrong kind, exits with 2, and
  its message never repeats a value, because that may be a password. A blank `user` or `passwd` means guest, as the example config says.
- **A local target that can't be checked is one failed item,** with exit 3, like any other transport failure, and the run carries on.

### Details settled in step 06.10
The roadmap says `-q` prints only errors and the final summary. Building it raised these details, which the agent settled and reported to
the owner:

- **`-q` never hides a deletion,** because [the docs](../cli.md#what-beck-deletes-and-when) promise that every one is listed, and the prompt
  still appears.
- **`-q` doesn't shorten `beck report`, or `beck scan` since 06.11,** because the list is what the command is for.
- **A run that ends early still says how:** `No missing bios were found`, or `No BIOS files found in …`, because there's no other summary.
- **A run that fails `--fail-if-missing` still says why,** with each file, because otherwise exit 5 would explain nothing. An `INCORRECT` file
  gets a short line here, because its usual line is hidden.
- **`-q` hides warnings too,** such as an extension that changes, and files it can't read, because the roadmap asks for errors and the summary.
  `--json` still has them.
- **`-v` names no user,** as `--json` doesn't, and turns on only BECK's own logs, because pysmb's debug logs show what crosses the network.
- **No counter with `-v`,** because it would break up the log lines, or with `--json`, because a counter is for people.

### Details settled in step 07.2
The roadmap gives the order of the sources. Building it raised these details, which the agent settled and reported to the owner:

- **A target is one setting with two forms,** so a higher source wins even in the other form: `--target-dir` beats `BECK_TARGET`, and
  `BECK_TARGET_DIR` beats a `url` in the file. Two targets in the environment are refused, unless a flag makes them not matter.
- **An empty variable counts as not set,** as it does for `NO_COLOR` and `FORCE_COLOR`, except `BECK_SMB_USER`, where the roadmap says it means
  a guest. So an empty one beats a user in the file.
- **A user in a target URL beats `BECK_SMB_USER`,** because it's the most specific thing anyone said about that target.
- **A broken settings file stops every command,** even one that wouldn't use it, such as `beck scan --source DIR`, because a typo should
  be noticed at once. A default file that doesn't exist is fine, and one that can't be read isn't taken for one that doesn't exist.
- **A source named anywhere must exist,** as `--source` already had to, so that a typo can't read as an empty folder.
- **The default timeout stays 30 seconds,** as it is today. The roadmap's sample file said 10, with no reason given, so the guide's sample says 30.
- **`config/config.yml` stayed until 07.3,** only when no other source named a target, and its password only went to its own server.

### Details settled in step 07.3
The roadmap lists the commands. Building them raised these details, which the agent settled and reported to the owner:

- **`BECK_SMB_PASSWORD` works from this step, not 07.4.** `beck config show` has to say whether it's set, and removing the old file would
  otherwise leave no way to log in. 07.4 adds the prompt, and the error when there's no password and no terminal.
- **A guest sends no password,** even if the variable is set, so that it can't go to a server nobody meant to log in to.
- **The notice isn't literally one-time.** That would need BECK to remember, by writing a marker file somewhere nobody asked for. Instead, it
  appears while the old file is there and the new one isn't, and it stops as soon as there's a new one.
- **`beck config init` writes where BECK would read,** so `--config` and `BECK_CONFIG` decide, not only the default place. It writes real settings,
  not only comments, so that `init` and a BIOS folder are enough for a guest on `recalbox.local`, which is what the stage asks for.
- **`beck config` has `--json`,** with a fifth schema, because stage 06 says every command has it. `settings.smb_user` is the one place a document
  names the user: asking what the settings are is the point of the command.
- **Only `show` reads the file,** so that `path` can find a broken one and `init --force` can replace it.
- **The first line of `beck config path` is only the path,** so that scripts can use it.
- **An old file whose `server` isn't a host name gets the default in the suggestion,** so that what BECK suggests always loads.

### Details settled in step 07.4
The roadmap gives the four cases. Building them raised these details, which the agent settled and reported to the owner:

- **`--json` never asks, even on a terminal,** because that's its promise, so it needs `BECK_SMB_PASSWORD`, or exits with 2.
- **A password that would show isn't asked for.** `getpass` only warns when it can't turn the echo off, and then reads it anyway, for anyone to see.
  That's a refusal here, with exit 2.
- **Ctrl-C or Ctrl-D at the question exits with 2, with no traceback,** because nothing has happened yet, and it's the same as refusing to answer.
- **An empty answer is an empty password,** which BECK sends, because a server may allow one. An empty variable still counts as not set, as every other one does.
- **Only what connects asks.** `beck config show` and `report --report-file` never do, and a dry run does, because it connects.

### Details settled in step 07.5
The roadmap asks for one `redact()` helper. A probe with a sentinel password shaped it, and the agent reported these to the owner:

- **The leak was a URL in the wrong place.** Nothing printed `BECK_SMB_PASSWORD`, but a URL holding a password came back whenever it wasn't given to `--target`: as a stray argument, in
  `--source`, `--report-file`, `--config` or `--frontend`, or in the environment. So `redact` takes credentials out of any URL, with its user too.
- **A value that's going to be a path loses its credentials first.** `Path` turns `smb://` into `smb:/`, and a `file://` URL encodes the rest, so afterwards nothing can tell it was a URL.
- **It masks known passwords as well,** for what can't be predicted: a library's message, or a bug's traceback. This never changes which file BECK reads: it's only on what's shown.
- **`--json` masks only free text, not every field,** because it promises exact file names. So a file named after the password appears in `path`, because it's the user's own file. People see `***`.
- **A short password masks whatever it appears in,** which is ugly, but the other way round isn't safe.
- **A settings-file `frontend` is no longer repeated,** following the rule from 07.1. A setting's *name* still is: nobody types a password as one.
- **The warning for a file others can read is only a warning,** because the file can't hold a password, and it appears when the file is read, so `beck config path` doesn't give it.
- **One limit:** a password with a literal `/` in a URL can't be told apart from a path, so that part stays. It isn't a valid URL, and BECK refuses it as a target.

### Details settled in step 07.6
The roadmap says a rejected entry is an error item. Before this step, some of those stopped the whole run, so building it raised these details, which the agent settled and reported to the owner:

- **One bad entry no longer stops the rest.** A path that climbs, or a name with a slash, used to refuse the whole report with exit 4, so one damaged line blocked every upload. Now it's one failed item, as the roadmap
  says. A report that can be read with one bad line in it isn't a report BECK can't read.
- **A block with no `Path` line or no MD5 still stops everything,** with exit 4, because then BECK can't trust how it's reading the format.
- **It exits with 3,** like every other item that failed while the run carried on, and it has its own code, `unsafe_path`.
- **`--clean-unmatched` deletes nothing if an entry was refused,** because a file that seems to match nothing could be the one that entry asked for.
- **A backslash is refused,** because SMB takes it as a separator. On the Samba test server, a report naming `folder\file.bin` wrote into that folder, while `..\` was refused by Samba itself.
- **The controls for the direction of text are refused too,** along with control characters and U+FFFD, the same set 06.11a escapes, because they'd make a file whose name reads as something else.
- **`a//b` and `./a` stay allowed.** They normalize to something safe, and refusing them would only risk refusing a real report.
- **`SmbTransport` refuses these paths too,** as `LocalTransport` does, whoever calls it. A failure there is one failed item as well.

### Deleting is always explicit
Nothing is deleted without `--move` or `--clean-unmatched`, and off a terminal not without `--yes` too. `--json` never prompts, so that
a consumer can't hang on a question or confirm one by accident.

## Alternatives considered
These were offered to the owner, and are recorded in [ADR-0002](0002-ai-agent-support.md#dec-23--versioned-json-output-and-stable-exit-codes)
and [ADR-0001](0001-product-scope.md#dec-02--non-destructive-by-default):

- *JSON documented only by example*: consumers could break silently when fields change. Not chosen.
- *Exit codes only*: agents would have to parse human-readable text. Not chosen.
- *Keeping move-and-delete, with a prompt*: it keeps a risky default. Not chosen.

The one-document-on-stdout rule and the `--json` no-prompt rule came from the roadmap plan, and weren't offered as a separate choice.

## Consequences
- **Easier:** scripts and agents can drive BECK with no integration code (DEC-05).
- **Harder:** the output can't change freely, and a mistake in schema v1 stays until v2.
- **Roadmap:** steps 06.2–06.12 build this, and stage 09's skills copy the exit-code table, with a test keeping them equal.
- **Revisit if:** the output needs a change that can't be made by adding fields.

## DEC-59 — Four CLI rules
- **Date:** 2026-11-05 (step 06.1).
- **Context:** Writing [docs/cli.md](../cli.md) showed cases the roadmap didn't cover. The agent proposed these rules, and the owner
  confirmed all four.
- **Decision:**
  - `--clean-unmatched` never deletes a file valid for an `INCORRECT` target, because that file is the fix for the one on the device.
  - A required `INCORRECT` file counts for `--fail-if-missing`, because the device still can't use it.
  - A transport error (3) beats `--fail-if-missing` (5), because the run didn't do all it could.
  - A local file that can't be read doesn't change the exit code, because the run completed and that file couldn't have matched.
- **Alternatives considered:** none were offered separately. The owner gave no further reason.
- **Consequences:** Steps 06.2a, 06.6 and 06.9 implement them.

## DEC-62 — A stream that fails can't change the run
- **Date:** 2026-11-05 (step 06.7b).
- **Context:** The end-to-end runs of step 06.7a showed that a run's result depended on how much it had printed when stdout failed. With a
  closed pipe, one run uploaded and exited with 120, another uploaded and exited with 1, and a third uploaded nothing and exited with 1,
  depending on the amount of output. Exit codes 1 and 120 also told a script that a run had failed after it had uploaded and deleted files, so
  a retry could repeat or lose work.
- **Decision:** What BECK does, and its exit code, don't depend on whether its output can be written. The run carries on, and the exit code
  reports the work. A closed pipe is silent, because the reader chose to stop. Any other failure, such as a full disk, prints one line on stderr.
- **Alternatives considered:**
  - *Keep going*: the option above, which the agent recommended.
  - *Stop as soon as the reader is gone*, as most Unix tools do: not chosen. It needs an exit code outside the contract's 0 to 5, and BECK only
    notices when a buffer fills, so what got done would still depend on the amount of output.

  The agent said that running the step as written would accept the recommendation, and the owner ran it. The owner gave no further reason.
- **Consequences:**
  - With `--move --yes | head`, files can be deleted without the user seeing the list, though `--yes` confirmed that.
  - A JSON document saved to a full disk is cut short while the exit code says 0, so the guide says to check that a saved document parses.
  - The deletion prompt is the one exception: a question that can't be shown can't be answered, so BECK can't ask, and deletes nothing.

## DEC-64 — An upload that doesn't match is `failed`
- **Date:** 2026-11-06 (step 07.7).
- **Context:** Until 07.7, only `--move` checked the size on the target, and the JSON guide said such an upload stayed `uploaded`, with an `error`. Step 07.7 checks every
  upload, so that would have counted a damaged file as satisfied, and shown `copied` beside an error. This changes what a public field says, so the agent asked. Nothing is released yet.
- **Decision:** An upload whose size, or with `--verify` whose MD5, doesn't match has the status `failed`, isn't counted in `satisfied` or `uploaded`, and exits with 3.
- **Alternatives considered:** *Keep `uploaded` with an `error`:* no change to the guide's wording, but a damaged file would count as satisfied, and human output would say `copied` next to an error. Not
  chosen. The agent recommended `failed`, and the owner gave no further reason.
- **Consequences:** The damaged file stays on the device, because BECK has no way to delete there. A later run would keep it, so the message says to use `--overwrite`.

## DEC-70 — `beck` needs a command
- **Date:** 2026-11-11 (step 10.11).
- **Context:** Before 1.0, `beck` with no command ran `check` and printed a hint that this was going away. Step 10.11 removes that for 1.0, which left
  open what `beck` alone should do then.
- **Decision:** `beck` with no command is a usage error: argparse says `the following arguments are required: <command>`, the exit code is 2, and
  nothing runs. With `--json`, it prints the rejected-command document, with `command: null`, like any command line BECK can't parse.
- **Alternatives considered:**
  - *Print the help, and exit with 0:* friendlier for someone typing it, but a script that relied on bare `beck` running `check` would do nothing
    and report success. Not chosen.
  - *Print the help, and exit with 2:* shows more, and still fails. Not chosen.

  The agent recommended the usage error, and the owner gave no further reason.
- **Consequences:** A breaking change, in 1.0. A script that still runs bare `beck` fails loudly, and the troubleshooting guide says to use
  `beck check`. No schema changes: the rejected-command document already existed.

## DEC-74 — A file that isn't a zip archive never fills a `.zip` target
- **Date:** 2026-11-11 (a fix released as `1.0.1`, found while researching step 11.2 on the Recalbox 10.1.1 VM).
- **Context:** Recalbox hashes a `.zip` target by the files inside it: its MD5 is that of the members' uncompressed bytes, one after
  the other, and `es_bios.xml` lists those hashes, not the zip's own. On the VM, `geolith/neogeo.zip` has the file MD5 `266c74…` and
  Recalbox's `b2c817…`, the MD5 of its contents, which is the one listed. So a single file can have an MD5 listed for a `.zip` target:
  the real report lists `neocd.bin`'s for `neocdz.zip`. BECK 1.0.0 uploaded it under that name, and its own checks passed, but the file
  isn't a zip archive, so Recalbox's web manager API reported `FileNotFound` for it. That's what the 1.0 end-to-end run did on the VM.
- **Decision:** The matcher never sends a file that isn't a zip archive, by its content and not its name, to a target whose extension
  is `.zip`, in any case. The target stays in `still_missing`, and the file never counts as unmatched, so `--clean-unmatched` keeps it.
  `beck --json check` gets a new list, `not_a_zip`, of `{path, target}`, and the console prints a warning for each. Adding a field is
  allowed within `schema_version` 1.
- **Alternatives considered:**
  - *No JSON change:* a warning on stderr only, with the file in none of the lists. The smallest change, but an agent reading stdout
    couldn't tell why the target is still missing. Not chosen.

  The owner chose to fix it at once as `1.0.1` rather than in step 11.4, and chose the new list, which the agent recommended. The owner
  gave no further reason.
- **Consequences:** BECK still can't match a real zip archive to a `.zip` target, because it compares the zip's own MD5: that's step
  11.4. Uploading a real zip archive whose own MD5 is listed still works. A target the 1.0.0 run filled this way stays on the device
  until the user deletes it, and the troubleshooting guide says so.

## DEC-78 — Zip-aware matching
- **Date:** 2026-11-11 (step 11.4).
- **Context:** Step 11.4 planned to match files inside zip archives. DEC-74 had found that Recalbox hashes a `.zip` target by its members,
  but not in which order. Recalbox's EmulationStation source answers it: `Zip::Md5Composite` in `es-core/src/utils/Zip.cpp` lists the
  members' names, as libzip gives them (UTF-8 if they're valid UTF-8, otherwise CP437 turned into UTF-8), sorts them with `std::sort`, which
  compares them byte by byte, and feeds each member's bytes to one MD5. An archive libzip can't open gives an empty hash, which is the
  `[Bios] Invalid MD5:` line seen in the VM's log. BECK reimplements the order with the standard library's `zipfile`, and copies no code.
- **Decision:**
  - **Scope: both kinds of match.** A zip archive fills a `.zip` target if its contents MD5 is listed, or as before its own MD5, and is
    uploaded whole. A member of a zip fills any other target by its own MD5: it's extracted to a temporary folder and uploaded under the
    target's name. A member never fills a `.zip` target, and a zip doesn't fill another target by its contents.
  - **Fixed limits:** at most 1,000 members and 512 MiB unpacked per archive, counted while reading. An archive over a limit, or damaged,
    is listed as unreadable, and its members aren't used. This differs from the step, which asked for configurable limits.
  - **JSON:** a `member` field, `null` for a plain file, wherever a local file can be a member: `uploads`, `duplicates` (with
    `of_member`), `already_filled`, `not_a_zip`, and `beck scan`'s `files`, which also get `contents_md5`. `path` and `source` stay the
    archive's real path. All are additions, allowed within `schema_version` 1.
- **Alternatives considered:**
  - Scope: *zip targets only*, or *members only*, as the step was first written. Not chosen.
  - Limits: *keys in the settings file*, or *command-line flags*. Not chosen.
  - JSON: *a path through the archive*, such as `bios.zip/scph1001.bin`, with no new field. It would change what `path` means, since it
    would no longer always be a real file. Not chosen.

  The agent recommended each chosen option, and the owner gave no further reason.
- **Consequences:**
  - The 15 `.zip` targets the 10.1.1 VM still lacked can be filled from the user's own archives.
  - A plain file wins over an identical member. Members are never unmatched: `--clean-unmatched` deletes an archive only if neither it nor
    anything in it matched, and `--move` deletes one only if it was itself uploaded and every upload from it worked.
  - Every zip in the BIOS folder is unpacked once per scan, which costs time on a large collection.
  - Not read: archives inside archives, `.7z` and `.rar` (which would need a new dependency, and a DEC), encrypted members, which Recalbox
    skips too, and Info-ZIP's Unicode path field. Two members whose names are the same after libzip's conversion are an edge where Recalbox
    reads one twice; BECK reads each once.

## DEC-80 — Results by system
- **Date:** 2026-11-12 (step 11.3).
- **Context:** `check` gave only totals, and `report` grouped files by folder. A user thinks in systems, as Recalbox's menus show them:
  the real 10.1.1 report names 20 systems for its 80 entries.
- **Decision:**
  - **By system,** as the report or web API names it. Each target counts once in each system that lists it, so `neogeo.zip`, which
    two systems list, counts in both. Within a system, the stronger kind wins: satisfied, then incorrect, then required, unknown and
    optional. Entries with no system are counted together: `null` in JSON, "Other" for people.
  - **For people, a block of lines:** "By system:", then one line per system, before `check`'s final line and hidden by `-q`, and at
    the end of `report`. Existing lines don't change, and `report` still lists its files by folder.
  - **In JSON, every count:** a `systems` list in `check` and `report`, each item with `system`, `missing_required`,
    `missing_optional`, `missing_unknown` and `incorrect`, and in `check` also `satisfied`, which a report can't know. An addition,
    allowed within `schema_version` 1. A run that stops has an empty list.
- **Alternatives considered:**
  - *By folder:* matches how `report` lists files, but folder names are less familiar. Not chosen.
  - *`report` listing its files by system,* with the counts in each heading: changes what `report` prints today. Not chosen.
  - *Only the counts step 11.3 names,* satisfied and missing by required or optional. Not chosen.

  The agent recommended each chosen option, and the owner gave no further reason.
- **Consequences:** The counts by system don't add up to `summary.missing_entries`, because a target can count in several systems. A
  report always says whether a file is required, so `missing_unknown` is 0 for Recalbox today.
