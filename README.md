# BECK

Send your BIOS files to the right folders on your Recalbox, by matching them against the list of files it says are missing.

[![CI](https://github.com/Andredson/BECK/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Andredson/BECK/actions/workflows/ci.yml)

## What it does

1. **Report:** your Recalbox writes a list of the BIOS files it's missing, with the MD5 each one should have.
2. **Scan:** BECK works out the MD5 of each file in your BIOS folder.
3. **Match:** the name of your file doesn't matter, only its MD5.
4. **Copy:** BECK sends each match over the network, under the name and into the folder your Recalbox expects.

## Legal notice

BIOS files are copyrighted. BECK doesn't include, download or distribute them: it only matches files you already have. Only use BIOS dumps from
hardware you own, and never commit BIOS files to this repository.

## Install

BECK is on [PyPI](https://pypi.org/project/beck-bios/) as `beck-bios`. With [uv](https://docs.astral.sh/uv/getting-started/installation/), which also gets the right
version of Python for you:

```sh
uv tool install beck-bios
```

Or with [pipx](https://pipx.pypa.io/stable/how-to/install-pipx.html), and Python 3.11 or newer:

```sh
pipx install beck-bios
```

Either way, you get a `beck` command. If your terminal can't find it, run `uv tool update-shell` or `pipx ensurepath`, and open a new terminal. Your Recalbox needs to be on your
network, with its SMB shares on, as they are on a fresh install.

## Quick start

1. **On your Recalbox,** [generate the report](https://github.com/Andredson/BECK/blob/main/docs/user-guide/generate-report.md): main menu → **BIOS CHECKING** → **REPORT**.
2. **On your computer,** create your settings:

   ```sh
   beck config init
   ```

   They're ready for the usual Recalbox: `recalbox.local`, with no password. If yours is different, `beck config path` says where the file is. Change `url` to use your
   Recalbox's IP address, as in `smb://192.168.1.20/bios`, and if it needs a login, set `user`, and BECK asks for the password.
3. **Put your BIOS files in the folder** the settings name:

   ```sh
   mkdir -p ~/beck/bios
   ```

4. **See what BECK would do.** This connects and reads, but changes nothing:

   ```sh
   beck check --dry-run
   ```

5. **Do it:**

   ```sh
   beck check
   ```

6. **On your Recalbox,** scan the BIOS files again, to see the result.

## Safety

- **Nothing is deleted unless you ask.** BECK copies your files and leaves them where they were. Only `--move` and `--clean-unmatched` delete anything, and they ask first. Read
  [what they delete](https://github.com/Andredson/BECK/blob/main/docs/cli.md#what-beck-deletes-and-when) before you use them: `--clean-unmatched` can delete good files.
- **Nothing on your Recalbox is replaced unless you ask.** A file already there is kept and reported, unless you add `--overwrite`.
- **Your password stays out of files.** BECK asks for it, or reads it from `BECK_SMB_PASSWORD`. It can't go in the settings file.
- **SMB isn't encrypted,** so use BECK on a network you trust. [The threat model](https://github.com/Andredson/BECK/blob/main/docs/threat-model.md) says what BECK protects, and what it doesn't.

## Configuration

Flags beat environment variables, which beat the settings file. [The guide to the `beck` command](https://github.com/Andredson/BECK/blob/main/docs/cli.md) has [every setting](https://github.com/Andredson/BECK/blob/main/docs/cli.md#settings) and every option.

## Automation and AI agents

Add `--json` to any command to get [one JSON document](https://github.com/Andredson/BECK/blob/main/docs/json-output.md) on stdout, and branch on [the exit code](https://github.com/Andredson/BECK/blob/main/docs/cli.md#exit-codes). `--json` never asks a question. To have an AI agent do this for you, see [Using BECK with an agent](https://github.com/Andredson/BECK/blob/main/docs/agents.md#using-beck-with-an-agent). For AI
agents, [`AGENTS.md`](https://github.com/Andredson/BECK/blob/main/AGENTS.md#using-beck-as-a-tool) has the rules for using BECK safely.

## Troubleshooting

BECK says what went wrong, and its [exit code](https://github.com/Andredson/BECK/blob/main/docs/cli.md#exit-codes) says what kind of problem it is. [The troubleshooting guide](https://github.com/Andredson/BECK/blob/main/docs/troubleshooting.md) goes through each message, with why it happens and what to do.

The most common one is that your computer can't find `recalbox.local`: use your Recalbox's IP address in `url` instead.

## Project status

BECK is stable since 1.0: a change that could break how you use it, such as a command, a flag, an exit code or the `--json` output, waits for a new major version. It's been tested on Recalbox 10.1.1 in a virtual machine, but not yet on real hardware. Its automatic tests run on Linux only, so Windows and macOS
are untested. [The changelog](https://github.com/Andredson/BECK/blob/main/CHANGELOG.md) lists what has changed.

**If you used an older copy,** note that BECK no longer deletes every file it copies, and no longer reads `config/config.yml`. Since 1.0, `check_bios.py` is gone, and so is
running `beck` with no command: install BECK as above, and run `beck check`. If you still have that file, BECK prints what to put in
the new settings. Delete it afterwards, because it may hold your password in plain text. Older copies tracked it in git, so if you edited it, `git pull` refuses to update until
you move it out of the way.

## Contributing

Help is welcome: [the contributing guide](https://github.com/Andredson/BECK/blob/main/CONTRIBUTING.md) says how to set up, what to work on, how to send a
change, and how to share a report safely.

[`AGENTS.md`](https://github.com/Andredson/BECK/blob/main/AGENTS.md) has the commands and rules for working on BECK, for people and for AI agents. [The roadmap](https://github.com/Andredson/BECK/blob/main/roadmap/README.md) is the plan, and
[the design](https://github.com/Andredson/BECK/blob/main/docs/ARCHITECTURE.md) explains how it fits together.

## Security

To report a problem, see [the security policy](https://github.com/Andredson/BECK/blob/main/SECURITY.md).

## License

GPL-3.0-only. See [LICENSE](https://github.com/Andredson/BECK/blob/main/LICENSE).
