"""Smoke tests: the legacy script imports cleanly and does nothing at import time."""

import builtins
import importlib
import socket
import sys
from typing import Any, NoReturn

import pytest
import smb.SMBConnection


def _forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("check_bios performed I/O at import time")


def test_import_has_no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    # File access, name lookups, socket or SMB connections during import fail the test.
    monkeypatch.setattr(builtins, "open", _forbidden)
    monkeypatch.setattr(socket, "gethostbyname", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(smb.SMBConnection, "SMBConnection", _forbidden)
    monkeypatch.delitem(sys.modules, "check_bios", raising=False)

    module = importlib.import_module("check_bios")

    assert callable(module.main)
