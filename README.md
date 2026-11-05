# BECK - BIOS CHECKER for RECALBOX!

A simple script that checks your BIOS files against the list of BIOS files your Recalbox is missing, and sends the
matching ones over SMB to the right folders on the Recalbox.

> [!NOTE]
> BECK no longer deletes anything in your `bios` folder. It copies the matching files to the Recalbox and leaves
> every local file as it was. Older copies of BECK did delete them, so run `git pull` first if your copy is old.

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
pip install -r requirements.txt
```

On Debian or Ubuntu, if `python3 -m venv` says that `ensurepip` isn't available, install the `python3-venv` package
first.

Or, if you use [uv](https://docs.astral.sh/uv/):

```sh
uv sync
```

## Configuration

Copy the example settings, then edit your copy:

```sh
cp config/config.example.yml config/config.yml
```

`server` is your Recalbox's address (`recalbox.local` by default, or its IP address), and `port` is `445`. `user`
and `passwd` can stay empty if your Recalbox allows guest access. Git ignores `config/config.yml`, so your password
is never committed.

## Upgrading

Older versions tracked `config/config.yml` in git. If you edited that file, `git pull` now refuses to update. Move
your settings out of the way, pull, and put them back:

```sh
cp config/config.yml ../beck-config.yml
git checkout -- config/config.yml
git pull
cp ../beck-config.yml config/config.yml
```

If you never edited it, `git pull` removes it; create it again as described in [Configuration](#configuration).

## Usage

1. Put your possible BIOS files in the **bios** folder.
2. From the repository folder, run:

   ```sh
   uv run beck                       # with pip: python check_bios.py
   ```

   `check_bios.py` still works and prints a notice that it's deprecated.

3. BECK lists what happened to each file: copied to the Recalbox, or kept because it's a duplicate, matches nothing,
   or its target was already filled.
4. When BECK reports BIOS files found, scan the BIOS files again on your Recalbox.

If Recalbox says a file on the device has the wrong hash, BECK lists it as `INCORRECT` and leaves it alone. Replace that
file yourself.

## Structure

```
┌BECK
├── check_bios.py          (kept for old usage: use beck)
├─┬─src
│ └── beck                  (the application)
├─┬─bios
│ └── *
├─┬─config
│ ├── config.example.yml
│ └── config.yml            (your copy, ignored by git)
├── requirements.txt
├── pyproject.toml
├── uv.lock
├── README.md
└── LICENSE
```

## Support

Recalbox 9.1

## Legal notice

BIOS files are copyrighted. BECK doesn't include, download or distribute BIOS files: it only matches files you
already have. Only use BIOS dumps from hardware you own, and never commit BIOS files to this repository.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
