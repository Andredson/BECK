"""Smoke tests: the legacy script imports cleanly and does nothing at import time."""

import ast
import builtins
import importlib
import socket
import sys
from pathlib import Path
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


def test_only_main_exits_the_program() -> None:
    tree = ast.parse(Path(importlib.import_module("check_bios").__file__ or "").read_text("utf-8"))
    exits = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                called = ast.unparse(node.func)
                if called in {"exit", "quit", "sys.exit"}:
                    exits.append((function.name, called))

    assert exits == [("main", "sys.exit")]


def test_no_bare_except_in_the_script() -> None:
    tree = ast.parse(Path(importlib.import_module("check_bios").__file__ or "").read_text("utf-8"))

    assert not [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and node.type is None
    ]
