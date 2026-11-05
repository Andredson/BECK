"""The ``beck`` command. Until step 04.13, it only hands over to the legacy script."""

import argparse
import importlib
import sys
from pathlib import Path

DESCRIPTION = "Match your BIOS files by MD5 and send them to the right folder on your Recalbox."


def run_legacy() -> int:
    """Run the root check_bios.py, which only exists in a clone of the repository."""
    root = Path(__file__).resolve().parents[2]
    if not (root / "check_bios.py").is_file():
        print(
            "This installed copy of BECK can't run yet. Use a clone of the repository.",
            file=sys.stderr,
        )
        return 1
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    importlib.import_module("check_bios").main()
    return 0


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="beck", description=DESCRIPTION).parse_args(argv)
    return run_legacy()
