"""The rules in docs/ARCHITECTURE.md, checked on the source. Also: importing has no side effects."""

import ast
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
PACKAGE = SRC / "beck"
MODULES = sorted(PACKAGE.rglob("*.py"))
CORE = ("models.py", "hashing.py", "matcher.py")


def name_of(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def tree_of(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def imports_of(path: Path) -> Iterator[str]:
    for node in ast.walk(tree_of(path)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def calls_of(path: Path) -> Iterator[str]:
    for node in ast.walk(tree_of(path)):
        if isinstance(node, ast.Call):
            yield ast.unparse(node.func)


def test_the_modules_were_found() -> None:
    assert {"cli.py", "transports/smb.py", *CORE} <= {name_of(path) for path in MODULES}


@pytest.mark.parametrize("path", MODULES, ids=name_of)
def test_only_the_entry_points_exit(path: Path) -> None:
    exits = {"exit", "quit", "sys.exit", "os._exit"} & set(calls_of(path))

    assert not exits, f"{name_of(path)} calls {exits}; only cli.py returns exit codes"


@pytest.mark.parametrize("path", MODULES, ids=name_of)
def test_no_bare_except(path: Path) -> None:
    handlers = [n for n in ast.walk(tree_of(path)) if isinstance(n, ast.ExceptHandler)]

    assert all(handler.type is not None for handler in handlers)


@pytest.mark.parametrize("name", CORE)
def test_the_core_imports_no_adapter(name: str) -> None:
    imported = set(imports_of(PACKAGE / name))

    assert not {i for i in imported if i.startswith(("beck.transports", "beck.frontends", "smb"))}
    assert not {"socket", "urllib", "http", "ftplib"} & imported


@pytest.mark.parametrize("path", MODULES, ids=name_of)
def test_only_the_smb_transport_imports_pysmb(path: Path) -> None:
    uses_pysmb = any(i == "smb" or i.startswith(("smb.", "nmb")) for i in imports_of(path))

    assert uses_pysmb == (name_of(path) == "transports/smb.py")


@pytest.mark.parametrize("path", MODULES, ids=name_of)
def test_only_the_output_layer_prints(path: Path) -> None:
    if not name_of(path).startswith("output/"):
        assert "print" not in set(calls_of(path))


@pytest.mark.parametrize("path", MODULES, ids=name_of)
def test_only_the_executor_deletes_and_nothing_renames(path: Path) -> None:
    # DEC-02: a user's local files are the one thing BECK must not lose.
    destructive = {
        call
        for call in calls_of(path)
        if call.rsplit(".", 1)[-1] in ("unlink", "remove", "rmtree", "rmdir", "rename", "replace")
        and not call.startswith("text.")  # str.replace, on a report's text
    }

    assert destructive == ({"file.path.unlink"} if name_of(path) == "executor.py" else set())


def test_the_matcher_does_no_io() -> None:
    allowed = {"collections.abc", "pathlib", "beck.models"}

    assert set(imports_of(PACKAGE / "matcher.py")) == allowed
    assert not {"open", "print"} & set(calls_of(PACKAGE / "matcher.py"))


def test_importing_every_module_does_no_io() -> None:
    # In a new process, with file access, name lookups and connections blocked during the imports.
    names = [
        ".".join(("beck", *path.relative_to(PACKAGE).with_suffix("").parts))
        for path in MODULES
        if path.name not in ("__init__.py", "__main__.py")
    ]
    script = f"""
import builtins, importlib, socket
def forbidden(*args, **kwargs):
    raise AssertionError("I/O at import time")
builtins.open = forbidden
socket.gethostbyname = socket.gethostname = forbidden
socket.socket.connect = socket.create_connection = forbidden
for name in {names!r}:
    importlib.import_module(name)
"""
    result = subprocess.run(  # noqa: S603 - fixed script, no external input
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
