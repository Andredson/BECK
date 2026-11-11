# SPDX-License-Identifier: GPL-3.0-only
"""The --json contract: what each run writes, checked against docs/schemas/ (DEC-23).

Each scenario below is a way a run can end. Between them they must write every kind of document, and
every field, status and error code, so a path that stops being checked fails a test here.

V1_FIELDS guards the compatibility promise. A field in it can't leave the schema, and a field in the
schema can't leave the documents, because the schemas require every field.
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

import pytest
from jsonschema import Draft202012Validator

from beck import cli
from beck.errors import BeckError, TransportError
from beck.frontends.recalbox import RecalboxAdapter
from beck.models import MissingBios
from beck.transports.local import LocalTransport
from tests.conftest import REAL_REPORT, REPORT_NAMES, REPORTS, isolate_settings
from tests.factories import (
    contents_md5,
    make_bios_file,
    make_missing,
    make_report_text,
    make_zip,
    md5_of,
    settings_text,
)
from tests.fakes import FakeSMBServer, install_fake_smb

ROOT = Path(__file__).resolve().parents[2]
SOURCE_CODE = ROOT / "src" / "beck"
SCHEMAS = ROOT / "docs" / "schemas"
GUIDE = ROOT / "docs" / "json-output.md"

CHECK, REPORT, SCAN, REJECTED = "check-result", "report-result", "scan-result", "rejected-command"
CONFIG, EXPORT = "config-result", "export-result"
SCHEMA_OF_COMMAND = {
    "check": CHECK,
    "report": REPORT,
    "scan": SCAN,
    "config": CONFIG,
    "export": EXPORT,
    None: REJECTED,
}

A, B = "a" * 32, "b" * 32
ACCOUNT = settings_text("smb://beck-test-server/bios", "beck-test-user")

UNSAFE_REPORT = (
    "MISSING BIOS REPORT\n  MISSING REQUIRED BIOS: ../evil.bin\n"
    f"    Path: /recalbox/share/bios/evil.bin\n    Possible MD5 List:\n      {A}\n"
)

Json = dict[str, Any]
Rules = dict[str, Json]
Arrange = Callable[["World"], list[str]]


# What schema_version 1 promises


TEXT: Json = {"type": "string"}
TEXT_OR_NULL: Json = {"type": ["string", "null"]}
FLAG: Json = {"type": "boolean"}
FLAG_OR_NULL: Json = {"type": ["boolean", "null"]}
COUNT: Json = {"type": "integer", "minimum": 0}
MD5: Json = {"type": "string", "pattern": "^[0-9a-f]{32}$"}
MD5_OR_NULL: Json = {"anyOf": [MD5, {"type": "null"}]}
UPLOAD_STATUS: Json = {"enum": ["planned", "uploaded", "replaced", "kept", "failed", "skipped"]}

ERROR: Rules = {"code": TEXT, "message": TEXT, "item": TEXT_OR_NULL}
FILE: Rules = {"path": TEXT, "md5": MD5, "size": COUNT}
UNREADABLE: Rules = {"path": TEXT, "reason": TEXT}
EXPORTED: Rules = {
    "path": TEXT,
    "size": COUNT,
    "status": {"enum": ["planned", "copied", "exists", "failed"]},
    "error": TEXT_OR_NULL,
}
MATCHED: Rules = {**FILE, "member": TEXT_OR_NULL}  # member: added in 1.1.0
SCANNED: Rules = {**MATCHED, "contents_md5": MD5_OR_NULL}  # contents_md5: added in 1.1.0
DUPLICATE: Rules = {
    "path": TEXT,
    "member": TEXT_OR_NULL,  # added in 1.1.0
    "of": TEXT,
    "of_member": TEXT_OR_NULL,  # added in 1.1.0
    "md5": MD5,
}
NOT_A_ZIP: Rules = {"path": TEXT, "member": TEXT_OR_NULL, "target": TEXT}  # member: in 1.1.0
UPLOAD: Rules = {
    "source": TEXT,
    "member": TEXT_OR_NULL,  # added in 1.1.0
    "target": TEXT,
    "md5": MD5,
    "status": UPLOAD_STATUS,
    "replaces": FLAG,
    "error": TEXT_OR_NULL,
    "warning": TEXT_OR_NULL,
}
MISSING: Rules = {
    "name": TEXT,
    "target": TEXT,
    "md5s": {"type": "array", "minItems": 1},
    "md5s[]": MD5,
    "required": FLAG_OR_NULL,
}
INCORRECT: Rules = {**MISSING, "current_md5": MD5_OR_NULL}


def listing(name: str, item: Rules) -> Rules:
    """The fields of a list of objects, named the way ``schema_fields`` names them."""
    fields = {f"{name}[].{field}": rule for field, rule in item.items()}
    return {name: {"type": "array"}, f"{name}[]": {"type": "object"}, **fields}


def summary(*names: str) -> Rules:
    return {"summary": {"type": "object"}, **{f"summary.{name}": COUNT for name in names}}


def setting(name: str, value: Json) -> Rules:
    """A setting ``beck config show`` shows, with where it came from."""
    place = f"settings.{name}"
    return {place: {"type": "object"}, f"{place}.value": value, f"{place}.source": TEXT}


COMMON: Rules = {
    "schema_version": {"const": 1},
    "beck_version": TEXT,
    "ok": FLAG,
    **listing("errors", ERROR),
}

# Fields are only added within a schema_version, so nothing here may change, or leave. A new field
# goes here too, because it's a promise from then on. Anything else needs schema_version 2, and the
# owner's OK (DEC-23).
V1_FIELDS: dict[str, Rules] = {
    CHECK: {
        **COMMON,
        "command": {"const": "check"},
        "dry_run": FLAG,
        "frontend": TEXT,
        "target": TEXT_OR_NULL,
        **summary(
            "missing_entries",
            "satisfied",
            "still_missing",
            "files_scanned",
            "uploaded",
            "duplicates",
            "unmatched",
            "deleted",
            "errors",
        ),
        **listing("uploads", UPLOAD),
        **listing("incorrect", INCORRECT),
        **listing("still_missing", MISSING),
        **listing("not_a_zip", NOT_A_ZIP),  # added in 1.0.1
        **listing("duplicates", DUPLICATE),
        **listing("already_filled", MATCHED),
        **listing("unmatched", FILE),
        **listing("unreadable", UNREADABLE),
        **listing("deleted", FILE),
    },
    REPORT: {
        **COMMON,
        "command": {"const": "report"},
        "frontend": TEXT,
        "target": TEXT_OR_NULL,
        **summary("missing", "incorrect"),
        **listing("missing", MISSING),
        **listing("incorrect", INCORRECT),
    },
    SCAN: {
        **COMMON,
        "command": {"const": "scan"},
        **summary("files", "unreadable"),
        **listing("files", SCANNED),
        **listing("unreadable", UNREADABLE),
    },
    EXPORT: {  # added in 1.1.0
        **COMMON,
        "command": {"const": "export"},
        "dry_run": FLAG,
        "target": TEXT_OR_NULL,
        "destination": TEXT_OR_NULL,
        **summary(
            "files_on_target", "rom_and_bin", "copied", "planned", "existing", "failed", "left_out"
        ),
        **listing("files", EXPORTED),
    },
    REJECTED: {
        **COMMON,
        "command": {"const": None},
        "ok": {"const": False},
    },
    CONFIG: {
        **COMMON,
        "command": {"const": "config"},
        "action": {"enum": ["path", "init", "show"]},
        "file": {"type": ["object", "null"]},
        "file.path": TEXT,
        "file.source": {"enum": ["flag", "environment", "default"]},
        "file.exists": FLAG,
        "created": FLAG,
        "settings": {"type": ["object", "null"]},
        **setting("target", TEXT_OR_NULL),
        **setting("source", TEXT),
        **setting("frontend", TEXT),
        **setting("smb_user", TEXT),
        **setting("smb_password", {"enum": ["set", "not set"]}),
        **setting("smb_timeout", {"type": "integer", "minimum": 1}),
    },
}


# Reading the schemas


@cache
def load_schema(name: str) -> Json:
    schema: Json = json.loads((SCHEMAS / f"{name}.v1.json").read_text(encoding="utf-8"))
    return schema


def resolved(node: Any, schema: Json) -> Any:
    """A part of a schema with each $ref replaced by what it points to."""
    if isinstance(node, list):
        return [resolved(item, schema) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return resolved(schema["$defs"][node["$ref"].removeprefix("#/$defs/")], schema)
    return {key: resolved(value, schema) for key, value in node.items()}


def rules_of(node: Json) -> Json:
    """What a field's value may be, leaving out what's free to change or is followed separately."""
    ignored = ("description", "properties", "items", "required")
    return {key: value for key, value in node.items() if key not in ignored}


def walk_fields(node: Json, path: str = "") -> Rules:
    children = {f"{path}.{k}" if path else k: v for k, v in node.get("properties", {}).items()}
    if "items" in node:
        children[f"{path}[]"] = node["items"]
    found: Rules = {}
    for place, child in children.items():
        found[place] = rules_of(child)
        found |= walk_fields(child, place)
    return found


def schema_fields(name: str) -> Rules:
    """Every field a schema describes and its rules, such as ``uploads[].status``."""
    schema = load_schema(name)
    return walk_fields(resolved(schema, schema))


def closed(node: Any) -> Any:
    """The same schema, except that it refuses any field it doesn't describe.

    The published ones allow extra fields so that a newer BECK still validates. BECK itself must not
    write a field they leave out.
    """
    if isinstance(node, list):
        return [closed(item) for item in node]
    if not isinstance(node, dict):
        return node
    copy = {key: closed(value) for key, value in node.items()}
    if "properties" in node:
        copy["additionalProperties"] = False
    return copy


def problems(schema: Json, document: Json) -> list[str]:
    validator = Draft202012Validator(schema)
    return [f"{error.json_path}: {error.message}" for error in validator.iter_errors(document)]


def places(node: Any, path: str = "") -> Iterator[tuple[str, Any, Any]]:
    """Every value in a document: its field, as in ``V1_FIELDS``, what holds it, and its key."""
    if isinstance(node, dict):
        children = [(f"{path}.{key}" if path else key, key) for key in node]
    elif isinstance(node, list):
        children = [(f"{path}[]", index) for index in range(len(node))]
    else:
        return
    for place, key in children:
        yield place, node, key
        yield from places(node[key], place)


def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def documented_codes() -> dict[str, int]:
    """The table of errors in the guide: each ``errors[].code`` and its exit code."""
    table = re.findall(r"^\| `(\w+)` \| (\d) \|", guide(), flags=re.MULTILINE)
    return {code: int(exit_code) for code, exit_code in table}


# Setting up a run


class World:
    """The folders of one run, and what a scenario needs to prepare it."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.monkeypatch = monkeypatch
        self.source, self.device, self.app = root / "source", root / "device", root / "app"
        for folder in (self.source, self.device, self.app / "bios"):
            folder.mkdir(parents=True)

    def report(self, *entries: MissingBios) -> None:
        """Put a report on the device."""
        (self.device / "missing_bios_report.txt").write_text(
            make_report_text(entries), encoding="utf-8", newline=""
        )

    def report_file(self, *entries: MissingBios) -> str:
        """Write a local copy of a report."""
        path = self.root / "report.txt"
        path.write_text(make_report_text(entries), encoding="utf-8", newline="")
        return str(path)

    def check(self, *flags: str) -> list[str]:
        target = ["--source", str(self.source), "--target-dir", str(self.device)]
        return ["--json", "check", *target, *flags]

    def on_smb(self, *entries: MissingBios) -> FakeSMBServer:
        """The settings file names a fake server, which has this report."""
        (self.app / "settings.toml").write_text(ACCOUNT, encoding="utf-8")
        self.monkeypatch.setenv("BECK_CONFIG", str(self.app / "settings.toml"))
        self.monkeypatch.setenv("BECK_SMB_PASSWORD", "beck-test-password")
        server = install_fake_smb(self.monkeypatch)
        server.files[("bios", "missing_bios_report.txt")] = make_report_text(entries).encode()
        return server


def raises(error: Exception) -> Callable[..., NoReturn]:
    def fail(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise error

    return fail


# Every way a run can end


@dataclass(frozen=True)
class Scenario:
    arrange: Arrange
    schema: str
    exit_code: int = 0


SCENARIOS: dict[str, Scenario] = {}


def scenario(schema: str, exit_code: int = 0) -> Callable[[Arrange], Arrange]:
    def register(arrange: Arrange) -> Arrange:
        SCENARIOS[arrange.__name__] = Scenario(arrange, schema, exit_code)
        return arrange

    return register


def only(*arguments: str) -> Arrange:
    """A scenario that needs nothing prepared."""
    return lambda _world: list(arguments)


# check: uploads


@scenario(CHECK)
def check_uploads_a_file(world: World) -> list[str]:
    file = make_bios_file(world.source, "ps1/copy.bin")
    world.report(make_missing("ps1/scph.bin", file.md5), make_missing("gone.bin", A))
    return world.check()


@scenario(CHECK)
def check_with_a_target_url(world: World) -> list[str]:
    world.on_smb()
    return [
        "--json",
        "check",
        "--source",
        str(world.source),
        "--target",
        "smb://beck-test-user@beck-test-server/bios",
    ]


@scenario(CHECK)
def check_with_json_after_the_command(world: World) -> list[str]:
    world.report()
    return ["check", "--json", "--source", str(world.source), "--target-dir", str(world.device)]


@scenario(CHECK)
def check_accounts_for_every_local_file(world: World) -> list[str]:
    own = make_bios_file(world.source, "z/target.bin")
    other = make_bios_file(world.source, "a-other.bin")
    kept = make_bios_file(world.source, "b.bin")
    make_bios_file(world.source, "b-copy.bin", kept.path.read_bytes())
    make_bios_file(world.source, "junk.bin")
    (world.source / "broken").symlink_to(world.source / "nowhere")
    world.report(make_missing("target.bin", own.md5, other.md5), make_missing("b.bin", kept.md5))
    return world.check()


@scenario(CHECK)
def check_changes_an_extension(world: World) -> list[str]:
    file = make_bios_file(world.source, "neocd.bin")
    world.report(
        make_missing("neocd/neocd.bin", file.md5), make_missing("neocd/neocd.rom", file.md5)
    )
    return world.check()


@scenario(CHECK)
def check_holds_back_a_file_that_is_not_a_zip(world: World) -> list[str]:
    file = make_bios_file(world.source, "neocd.bin")
    world.report(make_missing("neocd/neocd.bin", file.md5), make_missing("neocdz.zip", file.md5))
    return world.check()


@scenario(CHECK)
def check_uploads_files_from_zip_archives(world: World) -> list[str]:
    bios = os.urandom(64)
    make_zip(world.source, "a-bios.zip", {"ps1/scph1001.bin": bios, "readme.txt": b"text"})
    make_zip(world.source, "b-copy.zip", {"scph1001.bin": bios})
    neogeo = {"000-lo.lo": os.urandom(64), "sp-s2.sp1": os.urandom(64)}
    make_zip(world.source, "neogeo-mine.zip", neogeo)
    neocd = os.urandom(64)
    make_zip(world.source, "cd.zip", {"neocd.bin": neocd, "other.rom": os.urandom(64)})
    filled, other = os.urandom(64), os.urandom(64)
    make_bios_file(world.source, "filled.bin", filled)
    make_zip(world.source, "z-other.zip", {"other.bin": other})
    world.report(
        make_missing("ps1/scph1001.bin", md5_of(bios)),
        make_missing("neogeo.zip", contents_md5(neogeo)),
        make_missing("neocdz.zip", md5_of(neocd)),
        make_missing("x.bin", md5_of(filled), md5_of(other)),
    )
    return world.check()


@scenario(CHECK)
def check_moves_a_file(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    world.report(make_missing("a.bin", file.md5))
    return world.check("--move", "--yes")


@scenario(CHECK)
def check_moves_nothing_so_it_needs_no_confirmation(world: World) -> list[str]:
    make_bios_file(world.source, "junk.bin")
    world.report(make_missing("a.bin", A))
    return world.check("--move")


@scenario(CHECK)
def check_cleans_unmatched_files(world: World) -> list[str]:
    make_bios_file(world.source, "junk.bin")
    world.report(make_missing("a.bin", A))
    return world.check("--clean-unmatched", "--yes")


@scenario(CHECK)
def check_keeps_a_file_on_the_device(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    make_bios_file(world.device, "a.bin")
    world.report(make_missing("a.bin", file.md5))
    return world.check()


@scenario(CHECK)
def check_overwrites_a_file(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    make_bios_file(world.device, "a.bin")
    world.report(make_missing("a.bin", file.md5))
    return world.check("--overwrite")


@scenario(CHECK)
def check_on_a_file_name_that_is_not_utf8(world: World) -> list[str]:
    (world.source / os.fsdecode(b"bad-\xff.bin")).write_bytes(os.urandom(64))
    world.report(make_missing("a.bin", A))
    return world.check()


@scenario(CHECK)
def check_on_the_real_report(world: World) -> list[str]:
    make_bios_file(world.source, "junk.bin")
    return world.check("--report-file", str(REPORTS / f"{REAL_REPORT}.txt"))


# check: dry runs


@scenario(CHECK)
def check_dry_run_plans_uploads_and_deletions(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    make_bios_file(world.source, "junk.bin")
    world.report(make_missing("a.bin", file.md5))
    return world.check("--dry-run", "--clean-unmatched")


@scenario(CHECK)
def check_dry_run_would_overwrite(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    make_bios_file(world.device, "a.bin")
    world.report(make_missing("a.bin", file.md5))
    return world.check("--dry-run", "--overwrite")


@scenario(CHECK)
def check_dry_run_with_nothing_missing(world: World) -> list[str]:
    world.report()
    return world.check("--dry-run")


# check: what the report says about each file


@scenario(CHECK)
def check_lists_an_optional_file_as_still_missing(world: World) -> list[str]:
    world.report(make_missing("a.bin", A, required=False))
    make_bios_file(world.source, "junk.bin")
    return world.check()


@scenario(CHECK)
def check_on_a_report_that_does_not_say_what_is_required(world: World) -> list[str]:
    entries = [
        make_missing("a.bin", A, required=None),
        make_missing("b.bin", A, required=None, incorrect=True),
    ]
    world.monkeypatch.setattr(RecalboxAdapter, "parse_report", lambda _self, _text: entries)
    make_bios_file(world.source, "junk.bin")
    world.report()
    return world.check()


@scenario(CHECK)
def check_lists_an_incorrect_file(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    make_bios_file(world.device, "a.bin")
    world.report(
        make_missing("a.bin", file.md5, incorrect=True, current_md5=B),
        make_missing("b.bin", A),
        make_missing("c.bin", A, required=False, incorrect=True),
    )
    return world.check()


@scenario(CHECK)
def check_overwrites_an_incorrect_file(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    make_bios_file(world.device, "a.bin")
    world.report(make_missing("a.bin", file.md5, incorrect=True, current_md5=B))
    return world.check("--overwrite")


# check: runs that end early


@scenario(CHECK)
def check_with_nothing_missing(world: World) -> list[str]:
    make_bios_file(world.source, "a.bin")
    world.report()
    return world.check()


@scenario(CHECK)
def check_with_only_incorrect_files(world: World) -> list[str]:
    world.report(make_missing("a.bin", A, incorrect=True))
    return world.check()


@scenario(CHECK)
def check_with_no_local_files(world: World) -> list[str]:
    (world.source / "broken").symlink_to(world.source / "nowhere")
    world.report(make_missing("a.bin", A))
    return world.check()


@scenario(CHECK)
def check_with_no_local_files_and_overwrite(world: World) -> list[str]:
    world.report(make_missing("a.bin", A, incorrect=True, current_md5=B))
    return world.check("--overwrite")


# check: one item fails, and the run carries on


@scenario(CHECK, 3)
def check_with_a_failed_upload(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    world.report(make_missing("a.bin", file.md5))
    world.monkeypatch.setattr(LocalTransport, "upload", raises(TransportError("the disk is full")))
    return world.check()


@scenario(CHECK, 3)
def check_with_a_folder_that_cannot_be_created(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    (world.device / "blocked").write_bytes(b"a file, not a folder")
    world.report(make_missing("blocked/a.bin", file.md5))
    return world.check()


@scenario(CHECK, 3)
def check_with_a_size_mismatch(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    world.report(make_missing("a.bin", file.md5))
    world.monkeypatch.setattr(LocalTransport, "size", lambda _self, _path: 1)
    return world.check("--move", "--yes")


@scenario(CHECK, 3)
def check_with_an_upload_that_arrives_damaged(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    world.report(make_missing("a.bin", file.md5))
    real_upload = LocalTransport.upload

    def damaged(self: LocalTransport, local: Path, remote: PurePosixPath) -> int:
        written = real_upload(self, local, remote)
        (self.root / remote).write_bytes(bytes(reversed((self.root / remote).read_bytes())))
        return written

    world.monkeypatch.setattr(LocalTransport, "upload", damaged)
    return world.check("--verify")


@scenario(CHECK, 3)
def check_with_a_failed_delete(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    world.report(make_missing("a.bin", file.md5))
    world.monkeypatch.setattr(Path, "unlink", raises(PermissionError(13, "Permission denied")))
    return world.check("--move", "--yes")


@scenario(CHECK, 3)
def check_dry_run_with_a_failed_check(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    report = world.report_file(make_missing("a.bin", file.md5))
    world.monkeypatch.setattr(LocalTransport, "exists", raises(TransportError("no network")))
    return world.check("--dry-run", "--report-file", report)


# check: an entry in the report that isn't safe


@scenario(CHECK, 3)
def check_refuses_an_unsafe_entry_and_uploads_the_rest(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    report = make_report_text([make_missing("a.bin", file.md5)])
    unsafe = "  MISSING REQUIRED BIOS: ..\\evil.bin\n    Path: /recalbox/share/bios/evil.bin\n"
    (world.device / "missing_bios_report.txt").write_text(
        f"{report}{unsafe}    Possible MD5 List:\n      {A}\n", encoding="utf-8"
    )
    return world.check()


@scenario(CHECK, 3)
def check_with_only_an_unsafe_entry(world: World) -> list[str]:
    (world.device / "missing_bios_report.txt").write_text(UNSAFE_REPORT, encoding="utf-8")
    return world.check()


# check: --fail-if-missing


@scenario(CHECK, 5)
def check_fails_if_a_required_file_is_still_missing(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    world.report(make_missing("a.bin", file.md5), make_missing("gone.bin", A))
    return world.check("--fail-if-missing")


@scenario(CHECK, 5)
def check_fails_if_a_required_file_is_incorrect(world: World) -> list[str]:
    world.report(make_missing("a.bin", A, incorrect=True, current_md5=B))
    return world.check("--fail-if-missing")


@scenario(CHECK, 5)
def check_dry_run_would_fail_if_missing(world: World) -> list[str]:
    make_bios_file(world.source, "junk.bin")
    world.report(make_missing("gone.bin", A))
    return world.check("--dry-run", "--fail-if-missing")


@scenario(CHECK)
def check_passes_if_only_optional_files_are_missing(world: World) -> list[str]:
    world.report(make_missing("gone.bin", A, required=False))
    return world.check("--fail-if-missing")


# check: settings from somewhere other than the command line


@scenario(CHECK)
def check_with_a_settings_file(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    world.report(make_missing("a.bin", file.md5))
    settings = world.root / "settings.toml"
    settings.write_text(
        "schema_version = 1\n"
        f'[target]\nfrontend = "recalbox"\ndir = "{world.device}"\n'
        f'[source]\ndir = "{world.source}"\n',
        encoding="utf-8",
    )
    return ["--json", "check", "--config", str(settings)]


@scenario(CHECK)
def check_with_settings_in_the_environment(world: World) -> list[str]:
    world.report()
    world.monkeypatch.setenv("BECK_TARGET_DIR", str(world.device))
    world.monkeypatch.setenv("BECK_SOURCE", str(world.source))
    return ["--json", "check"]


@scenario(CHECK, 2)
def check_with_a_settings_file_that_has_problems(world: World) -> list[str]:
    settings = world.root / "settings.toml"
    settings.write_text('[smb]\ntimeout = "ten"\n', encoding="utf-8")
    return ["--json", "check", "--config", str(settings)]


@scenario(CHECK, 2)
def check_with_a_settings_file_that_does_not_exist(world: World) -> list[str]:
    return ["--json", "check", "--config", str(world.root / "nope.toml")]


@scenario(CHECK, 2)
def check_with_a_bad_target_in_the_environment(world: World) -> list[str]:
    world.monkeypatch.setenv("BECK_TARGET", "http://nope/bios")
    return ["--json", "check"]


# check: an error stops the run


@scenario(CHECK, 2)
def check_with_no_config(world: World) -> list[str]:
    return ["--json", "check"]


@scenario(CHECK, 2)
def check_with_a_password_in_the_url(world: World) -> list[str]:
    return ["--json", "check", "--target", "smb://user:beck-test-password@beck-test-server/bios"]


@scenario(CHECK, 2)
def check_with_a_source_that_does_not_exist(world: World) -> list[str]:
    return ["--json", "check", "--source", str(world.root / "nope")]


@scenario(CHECK, 2)
def check_with_an_unknown_frontend(world: World) -> list[str]:
    return world.check("--frontend", "no-such-frontend")


@scenario(CHECK, 2)
def check_that_would_delete_and_cannot_ask(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    (world.source / "broken").symlink_to(world.source / "nowhere")  # the run gets this far
    world.report(make_missing("a.bin", file.md5))
    return world.check("--move")


@scenario(CHECK, 3)
def check_with_a_failed_login(world: World) -> list[str]:
    world.on_smb().login_succeeds = False
    return ["--json", "check"]


@scenario(CHECK, 4)
def check_with_no_report_on_the_target(world: World) -> list[str]:
    return world.check()


@scenario(CHECK, 4)
def check_with_a_report_file_that_does_not_exist(world: World) -> list[str]:
    return world.check("--report-file", str(world.root / "nope.txt"))


@scenario(CHECK, 4)
def check_with_a_report_it_cannot_read(world: World) -> list[str]:
    (world.device / "missing_bios_report.txt").write_text("this is no report\n", encoding="utf-8")
    return world.check()


@scenario(CHECK, 4)
def check_dry_run_that_stops(world: World) -> list[str]:
    return world.check("--dry-run")


@scenario(CHECK, 1)
def check_with_a_bug(world: World) -> list[str]:
    file = make_bios_file(world.source, "a.bin")
    world.report(make_missing("a.bin", file.md5))
    world.monkeypatch.setattr(cli, "execute", raises(RuntimeError("a bug")))
    return world.check()


# report


@scenario(REPORT)
def report_from_a_file(world: World) -> list[str]:
    report = world.report_file(
        make_missing("ps1/a.bin", A, required=False, system="One"),
        make_missing("ps1/a.bin", B, required=True, system="Two"),
        make_missing("c.bin", A, incorrect=True, current_md5=B, system="Two"),
    )
    return ["--json", "report", "--report-file", report]


@scenario(REPORT)
def report_from_a_target_folder(world: World) -> list[str]:
    world.report(make_missing("a.bin", A, required=False), make_missing("b.bin", B, incorrect=True))
    return ["--json", "report", "--target-dir", str(world.device)]


@scenario(REPORT)
def report_from_smb(world: World) -> list[str]:
    world.on_smb(make_missing("a.bin", A))
    return ["--json", "report"]


@scenario(REPORT)
def report_from_a_target_url(world: World) -> list[str]:
    world.on_smb(make_missing("a.bin", A))
    return ["--json", "report", "--target", "smb://beck-test-user@beck-test-server/bios"]


@scenario(REPORT)
def report_with_nothing_missing(world: World) -> list[str]:
    return ["--json", "report", "--report-file", world.report_file()]


@scenario(REPORT)
def report_that_does_not_say_what_is_required(world: World) -> list[str]:
    entries = [
        make_missing("a.bin", A, required=None),
        make_missing("b.bin", A, required=None, incorrect=True),
    ]
    world.monkeypatch.setattr(RecalboxAdapter, "parse_report", lambda _self, _text: entries)
    return ["--json", "report", "--report-file", world.report_file()]


@scenario(REPORT)
def report_from_a_target_in_the_environment(world: World) -> list[str]:
    world.report(make_missing("a.bin", A))
    world.monkeypatch.setenv("BECK_TARGET_DIR", str(world.device))
    return ["--json", "report"]


@scenario(REPORT, 3)
def report_with_an_unsafe_entry(world: World) -> list[str]:
    (world.device / "missing_bios_report.txt").write_text(UNSAFE_REPORT, encoding="utf-8")
    return ["--json", "report", "--target-dir", str(world.device)]


@scenario(REPORT, 2)
def report_with_a_settings_file_that_has_problems(world: World) -> list[str]:
    settings = world.root / "settings.toml"
    settings.write_text("schema_version = 99\n", encoding="utf-8")
    return ["--json", "report", "--config", str(settings)]


@scenario(REPORT, 2)
def report_with_no_config(world: World) -> list[str]:
    return ["--json", "report"]


@scenario(REPORT, 2)
def report_with_a_password_in_the_url(world: World) -> list[str]:
    return ["--json", "report", "--target", "smb://user:beck-test-password@beck-test-server/bios"]


@scenario(REPORT, 3)
def report_with_a_failed_login(world: World) -> list[str]:
    world.on_smb().login_succeeds = False
    return ["--json", "report"]


@scenario(REPORT, 4)
def report_with_a_file_that_does_not_exist(world: World) -> list[str]:
    return ["--json", "report", "--report-file", str(world.root / "nope.txt")]


@scenario(REPORT, 4)
def report_with_none_on_the_target(world: World) -> list[str]:
    return ["--json", "report", "--target-dir", str(world.device)]


@scenario(REPORT, 4)
def report_it_cannot_read(world: World) -> list[str]:
    path = world.root / "report.txt"
    path.write_text("this is no report\n", encoding="utf-8")
    return ["--json", "report", "--report-file", str(path)]


@scenario(REPORT, 1)
def report_with_a_bug(world: World) -> list[str]:
    world.monkeypatch.setattr(RecalboxAdapter, "parse_report", raises(RuntimeError("a bug")))
    return ["--json", "report", "--report-file", world.report_file()]


# Every real and derived report we have, because their contents come from outside BECK.
SCENARIOS |= {
    f"report_on_fixture_{name}": Scenario(
        only("--json", "report", "--report-file", str(REPORTS / f"{name}.txt")), REPORT
    )
    for name in REPORT_NAMES
}


# scan


@scenario(SCAN)
def scan_lists_files_and_what_it_cannot_read(world: World) -> list[str]:
    make_bios_file(world.source, "ps1/a.bin")
    (world.source / "broken").symlink_to(world.source / "nowhere")
    return ["--json", "scan", "--source", str(world.source)]


@scenario(SCAN)
def scan_lists_the_members_of_a_zip_archive(world: World) -> list[str]:
    make_zip(world.source, "neogeo.zip", {"000-lo.lo": os.urandom(64), "sp-s2.sp1": b"x"})
    return ["--json", "scan", "--source", str(world.source)]


@scenario(SCAN)
def scan_with_an_empty_folder(world: World) -> list[str]:
    return ["--json", "scan", "--source", str(world.source)]


@scenario(SCAN)
def scan_with_the_default_folder(world: World) -> list[str]:
    make_bios_file(world.app / "bios", "a.bin")
    return ["--json", "scan"]


@scenario(SCAN)
def scan_with_no_default_folder(world: World) -> list[str]:
    (world.app / "bios").rmdir()
    return ["--json", "scan"]


@scenario(SCAN)
def scan_on_a_file_name_that_is_not_utf8(world: World) -> list[str]:
    (world.source / os.fsdecode(b"bad-\xff.bin")).write_bytes(os.urandom(64))
    return ["--json", "scan", "--source", str(world.source)]


@scenario(SCAN)
def scan_with_a_source_in_the_environment(world: World) -> list[str]:
    make_bios_file(world.source, "a.bin")
    world.monkeypatch.setenv("BECK_SOURCE", str(world.source))
    return ["--json", "scan"]


@scenario(SCAN, 2)
def scan_with_a_settings_file_that_has_problems(world: World) -> list[str]:
    settings = world.root / "settings.toml"
    settings.write_text("this is not toml", encoding="utf-8")
    return ["--json", "scan", "--config", str(settings)]


@scenario(SCAN, 2)
def scan_with_a_source_that_does_not_exist(world: World) -> list[str]:
    return ["--json", "scan", "--source", str(world.root / "nope")]


@scenario(SCAN, 1)
def scan_with_a_bug(world: World) -> list[str]:
    world.monkeypatch.setattr(cli, "scan", raises(RuntimeError("a bug")))
    return ["--json", "scan", "--source", str(world.source)]


# export


def exporting(world: World, *flags: str) -> list[str]:
    return ["--json", "export", str(world.root / "out"), "--target-dir", str(world.device), *flags]


@scenario(EXPORT)
def export_copies_the_rom_and_bin_files(world: World) -> list[str]:
    make_bios_file(world.device, "ps1/scph1001.bin")
    make_bios_file(world.device, "atari800/ATARIBAS.ROM")
    make_bios_file(world.device, "neogeo.zip")
    return exporting(world)


@scenario(EXPORT)
def export_dry_run(world: World) -> list[str]:
    make_bios_file(world.device, "ps1/scph1001.bin")
    return exporting(world, "--dry-run")


@scenario(EXPORT)
def export_keeps_a_file_already_here(world: World) -> list[str]:
    make_bios_file(world.device, "a.bin")
    make_bios_file(world.root / "out", "a.bin")
    return exporting(world)


@scenario(EXPORT)
def export_with_a_target_url(world: World) -> list[str]:
    server = world.on_smb()
    server.files[("bios", "a.bin")] = b"beck-test-bytes"
    return [
        "--json",
        "export",
        str(world.root / "out"),
        "--target",
        "smb://beck-test-user@beck-test-server/bios",
    ]


@scenario(EXPORT, 3)
def export_with_a_file_that_cannot_be_written(world: World) -> list[str]:
    make_bios_file(world.device, "ps1/a.bin")
    make_bios_file(world.device, "b.bin")
    make_bios_file(world.root / "out", "ps1")  # a file where a folder must go
    return exporting(world)


@scenario(EXPORT, 3)
def export_with_a_file_that_cannot_be_read(world: World) -> list[str]:
    make_bios_file(world.device, "a.bin")
    world.monkeypatch.setattr(LocalTransport, "read_bytes", raises(TransportError("refused")))
    return exporting(world)


@scenario(EXPORT, 3)
def export_with_a_target_that_does_not_exist(world: World) -> list[str]:
    return ["--json", "export", str(world.root / "out"), "--target-dir", str(world.root / "nope")]


@scenario(EXPORT, 2)
def export_to_a_file(world: World) -> list[str]:
    make_bios_file(world.root, "out")
    return exporting(world)


@scenario(EXPORT, 2)
def export_with_a_settings_file_that_has_problems(world: World) -> list[str]:
    (world.app / "settings.toml").write_text("[target\n", encoding="utf-8")
    world.monkeypatch.setenv("BECK_CONFIG", str(world.app / "settings.toml"))
    return ["--json", "export", str(world.root / "out")]


@scenario(EXPORT, 1)
def export_with_a_bug(world: World) -> list[str]:
    world.monkeypatch.setattr(cli, "export", raises(RuntimeError("a bug")))
    return exporting(world)


# config


@scenario(CONFIG)
def config_path_of_a_file_that_does_not_exist(world: World) -> list[str]:
    return ["--json", "config", "path"]


@scenario(CONFIG)
def config_path_of_a_named_file(world: World) -> list[str]:
    (world.app / "settings.toml").write_text(ACCOUNT, encoding="utf-8")
    return ["--json", "config", "path", "--config", str(world.app / "settings.toml")]


@scenario(CONFIG)
def config_path_from_the_environment(world: World) -> list[str]:
    world.monkeypatch.setenv("BECK_CONFIG", str(world.root / "settings.toml"))
    return ["--json", "config", "path"]


@scenario(CONFIG)
def config_init_creates_the_file(world: World) -> list[str]:
    return ["--json", "config", "init", "--config", str(world.root / "new" / "settings.toml")]


@scenario(CONFIG, 2)
def config_init_refuses_to_replace_a_file(world: World) -> list[str]:
    (world.app / "settings.toml").write_text(ACCOUNT, encoding="utf-8")
    return ["--json", "config", "init", "--config", str(world.app / "settings.toml")]


@scenario(CONFIG)
def config_show_with_nothing_set(world: World) -> list[str]:
    return ["--json", "config", "show"]


@scenario(CONFIG)
def config_show_with_everything_set(world: World) -> list[str]:
    (world.app / "settings.toml").write_text(ACCOUNT, encoding="utf-8")
    world.monkeypatch.setenv("BECK_SMB_PASSWORD", "beck-test-password")
    return ["--json", "config", "show", "--config", str(world.app / "settings.toml")]


@scenario(CONFIG, 2)
def config_show_with_a_file_that_has_problems(world: World) -> list[str]:
    (world.app / "settings.toml").write_text("this is not toml", encoding="utf-8")
    return ["--json", "config", "show", "--config", str(world.app / "settings.toml")]


@scenario(CONFIG, 1)
def config_with_a_bug(world: World) -> list[str]:
    world.monkeypatch.setattr(cli, "find_config", raises(RuntimeError("a bug")))
    return ["--json", "config", "path"]


# A command line that can't be parsed

SCENARIOS |= {
    f"rejected_{name}": Scenario(only(*arguments), REJECTED, 2)
    for name, arguments in {
        "flag": ["--json", "--no-such-flag"],
        "command": ["--json", "no-such-command"],
        "flag_on_a_command": ["--json", "check", "--no-such-flag"],
        "flag_on_a_command_with_json_after_it": ["check", "--json", "--no-such-flag"],
        "flag_with_no_value": ["--json", "check", "--source"],
        "two_targets": ["--json", "check", "--target", "smb://h/s", "--target-dir", "x"],
        "flag_with_json_shortened": ["--js", "check", "--no-such-flag"],
        "config_with_no_action": ["--json", "config"],
        "config_with_an_unknown_action": ["--json", "config", "nope"],
    }.items()
}


# Running them


@dataclass(frozen=True)
class Outcome:
    exit_code: int
    stdout: str
    stderr: str


def run(item: Scenario, folder: Path) -> Outcome:
    stdout, stderr = io.StringIO(), io.StringIO()
    with pytest.MonkeyPatch.context() as monkeypatch:
        isolate_settings(monkeypatch)  # this runs too early for the fixture that does it elsewhere
        world = World(folder, monkeypatch)
        arguments = item.arrange(world)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = cli.main(arguments, base_dir=world.app)
    return Outcome(exit_code, stdout.getvalue(), stderr.getvalue())


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Outcome]:
    """Each scenario runs once, because the tests below all read the same documents."""
    root = tmp_path_factory.mktemp("contract")
    return {name: run(item, root / name) for name, item in SCENARIOS.items()}


def documents_of(schema: str, outcomes: Mapping[str, Outcome]) -> Iterator[Json]:
    """A new copy of each document this schema describes, which a test is free to change."""
    for name, item in SCENARIOS.items():
        if item.schema == schema:
            document: Json = json.loads(outcomes[name].stdout)
            yield document


# Every document matches its schema, and what the guide says about it


@pytest.mark.parametrize("name", SCENARIOS)
def test_the_document_matches_its_schema_and_the_guide(
    name: str, outcomes: dict[str, Outcome]
) -> None:
    item, outcome = SCENARIOS[name], outcomes[name]
    assert outcome.exit_code == item.exit_code, outcome.stderr

    document = json.loads(outcome.stdout)  # refuses anything but one document

    schema = load_schema(item.schema)
    assert problems(schema, document) == []
    assert problems(closed(schema), document) == [], "the schema doesn't describe a field"
    assert document["ok"] is (item.exit_code == 0)
    assert "beck-test-password" not in outcome.stdout + outcome.stderr
    assert "beck-test-user" not in (document.get("target") or "")
    lists = {field: value for field, value in document.items() if isinstance(value, list)}
    counts = document.get("summary", {})
    for field, count in counts.items():
        if field in lists:
            assert count == len(lists[field]), f"summary.{field} isn't the length of {field}"
    if any(error["item"] is None for error in document["errors"]):
        assert not any(value for field, value in lists.items() if field != "errors")
        assert not any(count for field, count in counts.items() if field != "errors")


FOLDERS = ["--source", "{folder}", "--target-dir", "{folder}"]


@pytest.mark.parametrize(
    ("command", "schema", "exit_code"),
    [
        (["-m", "beck", "--json", "scan", "--source", "{folder}"], SCAN, 0),
        (["-m", "beck", "--json", "report", "--target-dir", "{folder}"], REPORT, 4),
        (["-m", "beck", "--json", "check", *FOLDERS], CHECK, 4),
        (["-m", "beck", "--json", "--no-such-flag"], REJECTED, 2),
    ],
    ids=["scan", "report", "check", "rejected"],
)
def test_a_real_process_writes_the_same_documents(
    command: list[str], schema: str, exit_code: int, tmp_path: Path
) -> None:
    arguments = [argument.replace("{folder}", str(tmp_path)) for argument in command]

    done = subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [sys.executable, *arguments],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )

    assert done.returncode == exit_code, done.stderr
    assert problems(closed(load_schema(schema)), json.loads(done.stdout)) == []


def test_the_guide_has_one_valid_example_of_each_document() -> None:
    blocks = re.findall(r"^```json\n(.*?)^```", guide(), flags=re.MULTILINE | re.DOTALL)
    examples = [json.loads(block) for block in blocks]

    assert sorted(SCHEMA_OF_COMMAND[example["command"]] for example in examples) == sorted(
        V1_FIELDS
    )
    for example in examples:
        schema = load_schema(SCHEMA_OF_COMMAND[example["command"]])
        assert problems(closed(schema), example) == []


# The compatibility promise


@pytest.mark.parametrize("name", V1_FIELDS)
def test_no_v1_field_disappeared_or_changed(name: str) -> None:
    current = schema_fields(name)
    changed = {field: rule for field, rule in V1_FIELDS[name].items() if current.get(field) != rule}

    assert not changed, (
        "Within schema_version 1, fields are only added. Changing or removing one needs "
        "schema_version 2 and the owner's OK (DEC-23)."
    )


@pytest.mark.parametrize("name", V1_FIELDS)
def test_a_new_field_is_in_the_record(name: str) -> None:
    new = set(schema_fields(name)) - set(V1_FIELDS[name])

    assert not new, "A new field is a promise from now on, so add it to V1_FIELDS."


def test_every_schema_file_is_in_the_record() -> None:
    files = {path.name.removesuffix(".v1.json") for path in SCHEMAS.glob("*.v1.json")}

    assert files == set(V1_FIELDS)


@pytest.mark.parametrize("name", V1_FIELDS)
def test_the_schema_file_is_a_valid_schema(name: str) -> None:
    schema = load_schema(name)

    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == Draft202012Validator.META_SCHEMA["$id"]
    assert schema["$id"].endswith(f"/docs/schemas/{name}.v1.json")


@pytest.mark.parametrize("name", V1_FIELDS)
def test_the_schema_refuses_a_document_with_a_field_gone_or_wrong(
    name: str, outcomes: dict[str, Outcome]
) -> None:
    schema = load_schema(name)
    tested = set()

    for document in documents_of(name, outcomes):
        for place, holder, key in list(places(document)):
            if place in tested:
                continue
            tested.add(place)
            value = holder[key]
            holder[key] = {"not": "what this field holds"}
            assert problems(schema, document), f"the schema accepts a wrong value for {place}"
            if isinstance(holder, dict):
                del holder[key]
                assert problems(schema, document), f"the schema doesn't require {place}"
            holder[key] = value

    assert tested == set(V1_FIELDS[name])


@pytest.mark.parametrize("name", V1_FIELDS)
def test_the_schema_accepts_a_field_from_a_newer_beck_and_closing_it_does_not(
    name: str, outcomes: dict[str, Outcome]
) -> None:
    schema = load_schema(name)

    for document in documents_of(name, outcomes):
        for _place, holder, _key in list(places(document)):
            if isinstance(holder, dict):
                holder["a_field_from_a_newer_beck"] = 1
        assert problems(schema, document) == []
        assert problems(closed(schema), document) != []


# The scenarios reach everything


def kinds_allowed(rule: Json) -> set[str]:
    """What a field's value may be, with true and false apart. Nothing for a fixed value."""
    kinds = rule.get("type", [option["type"] for option in rule.get("anyOf", [])])
    named = {kinds} if isinstance(kinds, str) else set(kinds)
    return named - {"boolean"} | {"true", "false"} if "boolean" in named else named


def kind_of(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    names = {dict: "object", list: "array", str: "string", int: "integer", type(None): "null"}
    return names[type(value)]


@pytest.mark.parametrize("name", V1_FIELDS)
def test_every_field_comes_up_in_every_form(name: str, outcomes: dict[str, Outcome]) -> None:
    """A field no scenario writes, or a null no scenario writes, would never be checked."""
    seen: dict[str, set[str]] = {}
    for document in documents_of(name, outcomes):
        for place, holder, key in places(document):
            seen.setdefault(place, set()).add(kind_of(holder[key]))

    assert set(seen) == set(V1_FIELDS[name])
    for field, rule in V1_FIELDS[name].items():
        # Only a check and a report have errors about one item. The others share the shape anyway.
        only_stops = name not in (CHECK, REPORT, EXPORT) and field == "errors[].item"
        expected = {"null"} if only_stops else kinds_allowed(rule)
        assert seen[field] == (expected or seen[field]), field


def test_every_upload_status_comes_up(outcomes: dict[str, Outcome]) -> None:
    seen = {
        upload["status"]
        for document in documents_of(CHECK, outcomes)
        for upload in document["uploads"]
    }

    assert seen == set(UPLOAD_STATUS["enum"])


def test_every_error_code_comes_up_with_its_documented_exit_code(
    outcomes: dict[str, Outcome],
) -> None:
    seen = {
        (error["code"], item.exit_code)
        for name, item in SCENARIOS.items()
        for error in json.loads(outcomes[name].stdout)["errors"]
    }

    assert seen == set(documented_codes().items())


def test_every_error_code_in_the_source_is_in_the_guide() -> None:
    errors: list[type[BeckError]] = [BeckError, *BeckError.__subclasses__()]
    classes = {error.code: error.exit_code for error in errors}
    literals = {
        code
        for path in SOURCE_CODE.rglob("*.py")
        for code in re.findall(r'\bcode="(\w+)"', path.read_text(encoding="utf-8"))
    }

    assert classes.items() <= documented_codes().items()
    assert set(documented_codes()) == set(classes) | literals


@pytest.mark.parametrize("command", cli.COMMANDS)
def test_every_command_can_succeed_stop_and_meet_a_bug(
    command: str, outcomes: dict[str, Outcome]
) -> None:
    exit_codes = {
        item.exit_code
        for name, item in SCENARIOS.items()
        if json.loads(outcomes[name].stdout)["command"] == command
    }

    assert {0, 1, 2} <= exit_codes
