# BECK - BIOS CHECKER for RECALBOX!

A simple script that checks your BIOS files against the list of BIOS files your Recalbox is missing, and sends the
matching ones over SMB to the right folders on the Recalbox.

> [!NOTE]
> BECK copies the matching files to the Recalbox and leaves your local files as they were, unless you ask it to delete
> them with `--move` or `--clean-unmatched`. Older copies of BECK always deleted them, so run `git pull` first if your copy is old.

## Prerequisites

- **Python 3.11 or newer.**
- A Recalbox on your network with its SMB shares enabled.
- The missing-BIOS report on the Recalbox: BECK reads `missing_bios_report.txt` from the Recalbox's `bios`
  share, so generate that report on the Recalbox first.

## Installation

Run these from the folder you cloned BECK into. With pip, inside a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate              # on Windows: .venv\Scripts\activate
pip install .
```

On Debian or Ubuntu, if `python3 -m venv` says that `ensurepip` isn't available, install the `python3-venv` package
first.

Or, if you use [uv](https://docs.astral.sh/uv/):

```sh
uv sync
```

## Configuration

Create a settings file, which you can then edit:

```sh
uv run beck config init           # with pip: beck config init
uv run beck config path           # where it is: ~/.config/beck/config.toml on Linux
```

`url` is your Recalbox's address (`smb://recalbox.local/bios` by default), and `dir` under `[source]` is your folder of BIOS files. `user` can
stay empty if your Recalbox allows guest access. If you name a user, BECK asks for the password, or you can set it in the `BECK_SMB_PASSWORD`
environment variable. It can't go in the file. [The guide](docs/cli.md#settings) has the rest, including environment variables for every setting.

## Upgrading

BECK doesn't read `config/config.yml` any more. If you still have that file, BECK prints what to put in the new settings file, leaving out the
password, which BECK now asks for. Delete the old file once you've moved your settings, because it may hold your password in plain text.

Older versions tracked that file in git. If you edited it, `git pull` refuses to update, so move it out of the way first:

```sh
cp config/config.yml ../beck-config.yml
git checkout -- config/config.yml
git pull
```

## Usage

1. Put your possible BIOS files in the **bios** folder.
2. From the repository folder, see what BECK would do, which changes nothing, and then do it:

   ```sh
   uv run beck check --dry-run
   uv run beck check
   ```

   With pip, leave out `uv run`. `python check_bios.py` still works in place of `beck check`, with the same options, and prints a
   notice that it's deprecated.

3. BECK lists what happened to each file: copied to the Recalbox, or kept because it's a duplicate, matches nothing,
   or its target was already filled.
4. When BECK reports BIOS files found, scan the BIOS files again on your Recalbox.

BECK doesn't replace files already on the device. It lists them, including any that Recalbox says has the wrong hash (`INCORRECT`).
To replace them, run `beck check --overwrite`. There's no backup of what it replaces.

Other things you can do:

```sh
uv run beck scan                                # list your local files and their MD5s, with no network
uv run beck report                              # list what your Recalbox is missing
uv run beck check --target-dir /media/sdcard/bios   # use a mounted SD card or USB drive
```

[The `beck` command](docs/cli.md) has every option, the exit codes, and what gets deleted. Scripts and AI agents can add `--json`
to get [one JSON document](docs/json-output.md) instead.

## Structure

```
┌BECK
├── check_bios.py          (kept for old usage: use beck)
├─┬─src
│ └── beck                  (the application)
├─┬─bios
│ └── *
├── requirements.txt
├── pyproject.toml
├── uv.lock
├── README.md
└── LICENSE
```

## Support

Recalbox 9.1

## Security

To report a problem, see [the security policy](SECURITY.md). [The threat model](docs/threat-model.md) says what BECK protects, and the risks it accepts.

## Legal notice

BIOS files are copyrighted. BECK doesn't include, download or distribute BIOS files: it only matches files you
already have. Only use BIOS dumps from hardware you own, and never commit BIOS files to this repository.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
