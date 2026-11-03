# BECK - BIOS CHECKER for RECALBOX!

A simple script that checks your BIOS files against the list of BIOS files your Recalbox is missing, and sends the
matching ones over SMB to the right folders on the Recalbox.

> [!WARNING]
> **Back up your BIOS files first.** This version **deletes every file in the `bios` folder** when it runs: files
> that match are uploaded to the Recalbox and then deleted, and files that match nothing are deleted too. Keep a
> copy somewhere else. A non-destructive version is on the way.

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

Edit `config/config.yml`. `server` is your Recalbox's address (`recalbox.local` by default, or its IP address), and
`port` is `445`. `user` and `passwd` can stay empty if your Recalbox allows guest access.

## Usage

1. Put your possible BIOS files in the **bios** folder.
2. From the repository folder, run:

   ```sh
   python check_bios.py              # with uv: uv run python check_bios.py
   ```

3. When BECK reports BIOS files found, scan the BIOS files again on your Recalbox.

## Structure

```
┌BECK
├── check_bios.py
├─┬─bios
│ └── *
├─┬─config
│ └── config.yml
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
