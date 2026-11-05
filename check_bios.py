"""Deprecated: use the ``beck`` command. Kept so that ``python check_bios.py`` still works."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))  # requirements.txt doesn't install BECK itself
    from beck.cli import main

    print("check_bios.py is deprecated: install BECK and use the beck command.", file=sys.stderr)
    sys.exit(main(["check", *sys.argv[1:]], base_dir=ROOT))
