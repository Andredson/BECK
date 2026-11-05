"""BECK: match BIOS files by MD5 and send them to the right folder on a retro-gaming device."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("beck-bios")
except importlib.metadata.PackageNotFoundError:  # run from a clone by check_bios.py
    __version__ = "0+unknown"
