# SPDX-License-Identifier: GPL-3.0-only
"""--json: every way a run can end gives exactly one valid document on stdout, and no secrets."""

import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

import pytest

from beck import __version__, cli
from beck.errors import TransportError, UsageError
from beck.models import Unreadable
from beck.output.json import JsonRenderer
from beck.transports.local import LocalTransport
from tests.conftest import REAL_REPORT, REPORTS, load_report
from tests.factories import (
    make_bios_file,
    make_missing,
    make_report_text,
    md5_of,
    settings_text,
    snapshot,
)
from tests.fakes import FakeSMBServer, install_fake_smb

A, B = "a" * 32, "b" * 32
SENTINEL = "beck-test-password-sentinel"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "source"
    folder.mkdir()
    return folder


@pytest.fixture
def device(tmp_path: Path) -> Path:
    folder = tmp_path / "device"
    folder.mkdir()
    return folder


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder with settings for a user whose password must never appear anywhere."""
    folder = tmp_path / "app"
    (folder / "bios").mkdir(parents=True)
    settings = settings_text("smb://beck-test-server/bios", "beck-test-user")
    (folder / "settings.toml").write_text(settings, encoding="utf-8")
    monkeypatch.setenv("BECK_CONFIG", str(folder / "settings.toml"))
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)
    return folder


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeSMBServer:
    return install_fake_smb(monkeypatch)


def put_report(device: Path, *entries: Any) -> None:
    (device / "missing_bios_report.txt").write_text(
        make_report_text(entries), encoding="utf-8", newline=""
    )


def check(source: Path, device: Path, *flags: str) -> list[str]:
    return ["--json", "check", "--source", str(source), "--target-dir", str(device), *flags]


def document(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """Stdout must be one JSON document and nothing else: json.loads refuses anything more."""
    parsed: dict[str, Any] = json.loads(capsys.readouterr().out)
    return parsed


def statuses(doc: dict[str, Any]) -> dict[str, str]:
    return {item["target"]: item["status"] for item in doc["uploads"]}


# Check: a complete document


def test_a_normal_run_gives_the_whole_document(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(source, "ps1/copy.bin")
    put_report(device, make_missing("ps1/scph.bin", file.md5), make_missing("gone.bin", A))

    assert cli.main(check(source, device)) == 0

    assert document(capsys) == {
        "schema_version": 1,
        "beck_version": __version__,
        "command": "check",
        "ok": True,
        "dry_run": False,
        "frontend": "recalbox",
        "target": device.resolve().as_uri(),
        "summary": {
            "missing_entries": 2,
            "satisfied": 1,
            "still_missing": 1,
            "files_scanned": 1,
            "uploaded": 1,
            "duplicates": 0,
            "unmatched": 0,
            "deleted": 0,
            "errors": 0,
        },
        "uploads": [
            {
                "source": "ps1/copy.bin",
                "target": "ps1/scph.bin",
                "md5": file.md5,
                "status": "uploaded",
                "replaces": False,
                "error": None,
                "warning": None,
            }
        ],
        "incorrect": [],
        "still_missing": [
            {"name": "gone.bin", "target": "gone.bin", "md5s": [A], "required": True}
        ],
        "duplicates": [],
        "already_filled": [],
        "unmatched": [],
        "unreadable": [],
        "deleted": [],
        "errors": [],
    }
    assert (device / "ps1" / "scph.bin").read_bytes() == file.path.read_bytes()


def test_every_local_file_is_accounted_for(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = make_bios_file(source, "a.bin")
    dup = make_bios_file(source, "b-copy.bin", kept.path.read_bytes())
    junk = make_bios_file(source, "junk.bin")
    (source / "broken").symlink_to(source / "nowhere")
    put_report(device, make_missing("a.bin", kept.md5))

    assert cli.main(check(source, device)) == 0

    doc = document(capsys)
    assert doc["duplicates"] == [{"path": "b-copy.bin", "of": "a.bin", "md5": dup.md5}]
    assert doc["unmatched"] == [{"path": "junk.bin", "md5": junk.md5, "size": junk.size}]
    assert [item["path"] for item in doc["unreadable"]] == ["broken"]
    assert doc["unreadable"][0]["reason"]
    assert doc["summary"]["duplicates"] == doc["summary"]["unmatched"] == 1
    assert doc["summary"]["files_scanned"] == 3
    assert doc["ok"] is True


def test_a_file_whose_targets_are_filled_is_listed(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    own = make_bios_file(source, "z/target.bin")
    other = make_bios_file(source, "a-other.bin")
    entries = [make_missing("target.bin", own.md5, other.md5)]
    put_report(device, *entries)

    assert cli.main(check(source, device)) == 0

    doc = document(capsys)
    assert doc["already_filled"] == [{"path": "a-other.bin", "md5": other.md5, "size": other.size}]
    assert statuses(doc) == {"target.bin": "uploaded"}


def test_a_target_in_several_systems_is_one_item_and_required_wins(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(source, "other.bin")
    put_report(
        device,
        make_missing("a.bin", A, required=False, system="One"),
        make_missing("a.bin", B, required=True, system="Two"),
        make_missing("c.bin", A, required=False, system="Two"),
    )

    assert cli.main(check(source, device)) == 0

    doc = document(capsys)
    assert doc["still_missing"] == [
        {"name": "a.bin", "target": "a.bin", "md5s": [A, B], "required": True},
        {"name": "c.bin", "target": "c.bin", "md5s": [A], "required": False},
    ]
    assert doc["summary"]["missing_entries"] == doc["summary"]["still_missing"] == 2


def test_an_extension_change_carries_its_warning_on_the_upload(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(source, "neocd.bin")
    report = (make_missing("neocd/neocd.bin", file.md5), make_missing("neocdz.zip", file.md5))
    put_report(device, *report)

    assert cli.main(check(source, device)) == 0

    warnings = {item["target"]: item["warning"] for item in document(capsys)["uploads"]}
    assert warnings["neocd/neocd.bin"] is None
    assert warnings["neocdz.zip"] == (
        "neocd.bin has a different extension from neocdz.zip. The MD5 matches, but an emulator "
        "may not be able to read it."
    )


# Check: what a dry run and existing files look like


def test_a_dry_run_plans_and_changes_nothing(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(source, "a.bin")
    junk = make_bios_file(source, "junk.bin")
    put_report(device, make_missing("a.bin", file.md5))
    local, remote = snapshot(source), snapshot(device)

    assert cli.main(check(source, device, "--dry-run", "--clean-unmatched")) == 0

    doc = document(capsys)
    assert doc["dry_run"] is True
    assert statuses(doc) == {"a.bin": "planned"}
    assert doc["summary"]["satisfied"] == 1
    assert doc["summary"]["uploaded"] == 0
    assert doc["summary"]["deleted"] == 1
    assert doc["deleted"] == [{"path": "junk.bin", "md5": junk.md5, "size": junk.size}]
    assert snapshot(source) == local
    assert snapshot(device) == remote


def test_a_file_already_on_the_device_is_kept(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(source, "a.bin")
    make_bios_file(device, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))

    assert cli.main(check(source, device)) == 0

    doc = document(capsys)
    assert statuses(doc) == {"a.bin": "kept"}
    assert doc["uploads"][0]["replaces"] is False
    assert doc["summary"]["satisfied"] == 0


def test_overwrite_reports_replaced(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(source, "a.bin")
    make_bios_file(device, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))

    assert cli.main(check(source, device, "--overwrite")) == 0

    doc = document(capsys)
    assert statuses(doc) == {"a.bin": "replaced"}
    assert doc["uploads"][0]["replaces"] is True


def test_a_dry_run_says_which_uploads_would_overwrite(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    swap, new = make_bios_file(source, "swap.bin"), make_bios_file(source, "new.bin")
    make_bios_file(device, "swap.bin")
    put_report(device, make_missing("swap.bin", swap.md5), make_missing("new.bin", new.md5))

    assert cli.main(check(source, device, "--overwrite", "--dry-run")) == 0

    uploads = {item["target"]: item for item in document(capsys)["uploads"]}
    assert uploads["swap.bin"]["status"] == uploads["new.bin"]["status"] == "planned"
    assert uploads["swap.bin"]["replaces"] is True
    assert uploads["new.bin"]["replaces"] is False


def test_an_incorrect_file_is_listed_with_its_current_md5(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(source, "a.bin")
    make_bios_file(device, "a.bin")
    put_report(device, make_missing("a.bin", file.md5, incorrect=True, current_md5=B))

    assert cli.main(check(source, device)) == 0

    doc = document(capsys)
    assert doc["incorrect"] == [
        {
            "name": "a.bin",
            "target": "a.bin",
            "md5s": [file.md5],
            "required": True,
            "current_md5": B,
        }
    ]
    assert doc["uploads"] == []


def test_overwrite_fills_an_incorrect_target(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(source, "a.bin")
    make_bios_file(device, "a.bin")
    put_report(device, make_missing("a.bin", file.md5, incorrect=True, current_md5=B))

    assert cli.main(check(source, device, "--overwrite")) == 0

    doc = document(capsys)
    assert statuses(doc) == {"a.bin": "replaced"}
    assert doc["incorrect"] == []


# Check: runs with nothing to upload still give the whole document


def test_nothing_missing(source: Path, device: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_bios_file(source, "a.bin")
    put_report(device)

    assert cli.main(check(source, device)) == 0

    doc = document(capsys)
    assert doc["ok"] is True
    assert doc["uploads"] == doc["still_missing"] == doc["incorrect"] == []
    assert doc["summary"]["missing_entries"] == 0


def test_a_dry_run_with_nothing_to_upload_still_says_it_was_a_dry_run(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    put_report(device)

    assert cli.main(check(source, device, "--dry-run")) == 0

    assert document(capsys)["dry_run"] is True


def test_only_incorrect_files(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(device, "a.bin")
    put_report(device, make_missing("a.bin", A, incorrect=True, current_md5=B))

    assert cli.main(check(source, device)) == 0

    doc = document(capsys)
    assert doc["ok"] is True
    assert [item["target"] for item in doc["incorrect"]] == ["a.bin"]
    assert doc["still_missing"] == []


def test_no_local_files_still_lists_what_is_missing(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (source / "broken").symlink_to(source / "nowhere")
    put_report(device, make_missing("a.bin", A))

    assert cli.main(check(source, device)) == 0

    doc = document(capsys)
    assert doc["ok"] is True
    assert [item["target"] for item in doc["still_missing"]] == ["a.bin"]
    assert doc["summary"]["files_scanned"] == 0
    assert doc["summary"]["missing_entries"] == 1
    assert [item["path"] for item in doc["unreadable"]] == ["broken"]


def test_no_local_files_with_overwrite_lists_the_incorrect_ones(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_bios_file(device, "a.bin")
    put_report(device, make_missing("a.bin", A, incorrect=True, current_md5=B))

    assert cli.main(check(source, device, "--overwrite")) == 0

    assert [item["target"] for item in document(capsys)["incorrect"]] == ["a.bin"]


# Check: failures of one item


def test_a_failed_upload_is_failed_and_the_run_is_not_ok(
    source: Path,
    device: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, bad = make_bios_file(source, "good.bin"), make_bios_file(source, "bad.bin")
    put_report(device, make_missing("good.bin", good.md5), make_missing("bad.bin", bad.md5))
    real_upload = LocalTransport.upload

    def upload(self: LocalTransport, local: Path, remote: PurePosixPath) -> int:
        if remote.name == "bad.bin":
            raise TransportError("the disk is full")
        return real_upload(self, local, remote)

    monkeypatch.setattr(LocalTransport, "upload", upload)

    assert cli.main(check(source, device)) == 3

    doc = document(capsys)
    assert doc["ok"] is False
    uploads = {item["target"]: item for item in doc["uploads"]}
    assert uploads["bad.bin"]["status"] == "failed"
    assert uploads["bad.bin"]["error"] == "the disk is full"
    assert uploads["good.bin"]["status"] == "uploaded"
    assert uploads["good.bin"]["error"] is None
    assert doc["errors"] == [
        {"code": "transport", "message": "the disk is full", "item": "bad.bin"}
    ]
    assert doc["summary"]["errors"] == 1


def test_a_failed_check_in_a_dry_run_is_failed_not_planned(
    source: Path,
    device: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = make_bios_file(source, "a.bin")
    report_copy = source.parent / "report.txt"
    report_copy.write_text(
        make_report_text([make_missing("a.bin", file.md5)]), encoding="utf-8", newline=""
    )

    def exists(self: LocalTransport, path: PurePosixPath) -> bool:
        raise TransportError("the network went away")

    monkeypatch.setattr(LocalTransport, "exists", exists)

    assert cli.main(check(source, device, "--dry-run", "--report-file", str(report_copy))) == 3

    doc = document(capsys)
    assert statuses(doc) == {"a.bin": "failed"}
    assert doc["summary"]["satisfied"] == 0


def test_an_upload_skipped_by_a_failed_folder_is_skipped(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(source, "a.bin")
    (device / "blocked").write_bytes(b"a file, not a folder")
    put_report(device, make_missing("blocked/a.bin", file.md5))

    assert cli.main(check(source, device)) == 3

    doc = document(capsys)
    assert statuses(doc) == {"blocked/a.bin": "skipped"}
    assert [(e["code"], e["item"]) for e in doc["errors"]] == [("transport", "blocked")]


def test_a_size_mismatch_fails_the_upload_and_has_its_own_code(
    source: Path,
    device: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    monkeypatch.setattr(LocalTransport, "size", lambda _self, _path: 1)

    assert cli.main(check(source, device, "--move", "--yes")) == 3

    doc = document(capsys)
    assert statuses(doc) == {"a.bin": "failed"}
    assert doc["errors"][0]["code"] == "size_mismatch"
    assert doc["uploads"][0]["error"] == doc["errors"][0]["message"]
    assert doc["deleted"] == []
    assert file.path.exists()


def test_a_failed_delete_is_not_mistaken_for_an_upload_with_the_same_name(
    source: Path,
    device: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))

    def refuse(_self: Path) -> NoReturn:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "unlink", refuse)

    assert cli.main(check(source, device, "--move", "--yes")) == 3

    doc = document(capsys)
    assert statuses(doc) == {"a.bin": "uploaded"}
    assert doc["uploads"][0]["error"] is None
    assert doc["errors"] == [
        {
            "code": "delete_failed",
            "message": "Couldn't delete a.bin: Permission denied",
            "item": "a.bin",
        }
    ]
    assert doc["deleted"] == []


# Never asking


class Keyboard:
    """A terminal on stdin that fails the test if BECK ever tries to read an answer from it."""

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        raise AssertionError("--json must never ask")


def test_json_never_asks_even_on_a_terminal(
    source: Path,
    device: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    monkeypatch.setattr(sys, "stdin", Keyboard())
    local, remote = snapshot(source), snapshot(device)

    assert cli.main(check(source, device, "--move")) == 2

    doc = document(capsys)
    assert doc["ok"] is False
    assert doc["errors"][0]["code"] == "usage"
    assert "--yes" in doc["errors"][0]["message"]
    assert doc["summary"]["files_scanned"] == 0, "a stopped run has zero counts"
    assert snapshot(source) == local
    assert snapshot(device) == remote


def test_yes_confirms_without_asking(
    source: Path,
    device: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    monkeypatch.setattr(sys, "stdin", Keyboard())

    assert cli.main(check(source, device, "--move", "--yes")) == 0

    doc = document(capsys)
    assert doc["deleted"] == [{"path": "a.bin", "md5": file.md5, "size": file.size}]
    assert not file.path.exists()


def test_the_renderer_would_refuse_if_it_were_ever_asked(tmp_path: Path) -> None:
    renderer = JsonRenderer("check", frontend="recalbox", dry_run=False)

    assert renderer.can_ask() is False
    assert renderer.confirm_deletion(None) is False  # type: ignore[arg-type]


# Errors that stop a run


def test_a_missing_config_is_a_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--json", "check"], base_dir=tmp_path) == 2

    doc = document(capsys)
    assert doc["ok"] is False
    assert doc["command"] == "check"
    assert doc["target"] is None
    assert doc["uploads"] == []
    assert doc["summary"]["errors"] == 1
    assert doc["errors"][0]["code"] == "config"
    assert doc["errors"][0]["item"] is None


def test_a_connection_failure_names_the_target_without_credentials(
    app: Path, server: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    server.login_succeeds = False

    assert cli.main(["--json", "check"], base_dir=app) == 3

    out = capsys.readouterr()
    doc = json.loads(out.out)
    assert doc["errors"][0]["code"] == "transport"
    assert doc["target"] == "smb://beck-test-server:445/bios"
    assert SENTINEL not in out.out + out.err
    assert "beck-test-user" not in doc["target"]


def test_a_missing_report_is_a_report_error(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(check(source, device)) == 4

    doc = document(capsys)
    assert doc["errors"][0]["code"] == "report_not_found"
    assert doc["target"] == device.resolve().as_uri()


def test_an_unreadable_report_is_a_report_error(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (device / "missing_bios_report.txt").write_text("this is not a report\n", encoding="utf-8")

    assert cli.main(check(source, device)) == 4

    assert document(capsys)["errors"][0]["code"] == "report_parse"


def test_a_stopped_dry_run_still_says_it_was_a_dry_run(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(check(source, device, "--dry-run")) == 4

    assert document(capsys)["dry_run"] is True


def test_a_url_with_a_password_never_repeats_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"smb://user:{SENTINEL}@beck-test-server/bios"

    assert cli.main(["--json", "check", "--target", url], base_dir=tmp_path) == 2

    out = capsys.readouterr()
    assert json.loads(out.out)["errors"][0]["code"] == "usage"
    assert SENTINEL not in out.out + out.err


def test_a_source_that_does_not_exist_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["--json", "check", "--source", str(tmp_path / "nope")]

    assert cli.main(arguments, base_dir=tmp_path) == 2

    assert document(capsys)["errors"][0]["code"] == "usage"


def test_a_bug_gives_a_document_and_the_traceback_stays_on_stderr(
    source: Path,
    device: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))

    def broken(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError(f"a bug holding {SENTINEL}")

    monkeypatch.setattr(cli, "execute", broken)

    assert cli.main(check(source, device)) == 1

    out = capsys.readouterr()
    doc = json.loads(out.out)
    assert doc["ok"] is False
    assert doc["errors"] == [
        {
            "code": "internal",
            "message": "Unexpected error. The details are on stderr.",
            "item": None,
        }
    ]
    assert SENTINEL not in out.out
    assert "Traceback" in out.err


def test_the_same_bug_prints_nothing_on_stdout_without_json(
    source: Path,
    device: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))

    def broken(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError("a bug")

    monkeypatch.setattr(cli, "execute", broken)
    arguments = ["check", "--source", str(source), "--target-dir", str(device)]

    assert cli.main(arguments) == 1

    assert "{" not in capsys.readouterr().out


def test_a_stopped_report_has_the_report_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = str(tmp_path / "nope.txt")

    assert cli.main(["--json", "report", "--report-file", missing]) == 4

    doc = document(capsys)
    assert doc["command"] == "report"
    assert doc["ok"] is False
    assert doc["missing"] == doc["incorrect"] == []
    assert doc["summary"] == {"missing": 0, "incorrect": 0}
    assert doc["errors"][0]["code"] == "report_not_found"


def test_a_stopped_run_forgets_what_it_scanned(capsys: pytest.CaptureFixture[str]) -> None:
    renderer = JsonRenderer("check", frontend="recalbox", dry_run=False)
    unreadable = Unreadable(PurePosixPath("broken"), "broken symlink")
    renderer.files_found(3)
    renderer.unreadable((unreadable,))

    renderer.error(UsageError("stopped"))

    doc = document(capsys)
    assert doc["summary"]["files_scanned"] == 0
    assert doc["unreadable"] == []


def test_a_stopped_scan_has_the_scan_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--json", "scan", "--source", str(tmp_path / "nope")]) == 2

    doc = document(capsys)
    assert doc["command"] == "scan"
    assert doc["ok"] is False
    assert doc["files"] == doc["unreadable"] == []
    assert doc["errors"][0]["code"] == "usage"


# A command line that can't be parsed


@pytest.mark.parametrize(
    "arguments",
    [
        ["--json", "--no-such-flag"],
        ["--json", "no-such-command"],
        ["--json", "check", "--no-such-flag"],
        ["check", "--json", "--no-such-flag"],
        ["--json", "check", "--source"],
        ["--json", "check", "--target", "smb://h/s", "--target-dir", "x"],
        ["--js", "check", "--no-such-flag"],
    ],
)
def test_a_rejected_command_line_gives_a_small_document_on_stdout(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(arguments) == 2

    out = capsys.readouterr()
    doc = json.loads(out.out)
    assert doc["schema_version"] == 1
    assert doc["beck_version"] == __version__
    assert doc["command"] is None
    assert doc["ok"] is False
    assert doc["errors"][0]["code"] == "usage"
    assert doc["errors"][0]["item"] is None
    assert set(doc) == {"schema_version", "beck_version", "command", "ok", "errors"}
    assert out.err == ""


@pytest.mark.parametrize(
    "arguments",
    [
        ["check", "--no-such-flag"],
        ["check", "--", "junk"],
        ["check", "-", "junk"],
        ["check", "--source=--json", "junk"],
    ],
)
def test_without_json_a_rejected_command_line_is_still_argparse_on_stderr(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(arguments)

    assert stop.value.code == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert "unrecognized arguments" in out.err


@pytest.mark.parametrize("arguments", [["--json", "--help"], ["--json", "--version"]])
def test_help_and_version_are_text_even_with_json(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(arguments)

    assert stop.value.code == 0
    assert "beck" in capsys.readouterr().out


# Where --json goes, and what else stays out of stdout


def test_json_works_after_the_command_too(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    put_report(device)
    arguments = ["check", "--json", "--source", str(source), "--target-dir", str(device)]

    assert cli.main(arguments) == 0

    assert document(capsys)["command"] == "check"


def test_no_command_counts_as_check_and_the_hint_stays_on_stderr(
    app: Path, server: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    server.files[("bios", "missing_bios_report.txt")] = make_report_text([]).encode()

    assert cli.main(["--json"], base_dir=app) == 0

    out = capsys.readouterr()
    assert json.loads(out.out)["command"] == "check"
    assert "beck check" in out.err


def test_colors_never_reach_the_document(
    source: Path,
    device: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))

    assert cli.main(check(source, device)) == 0

    assert "\033" not in capsys.readouterr().out


def test_a_file_name_that_is_not_valid_utf8_cannot_break_the_output(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    name = os.fsdecode(b"bad-\xff.bin")
    (source / name).write_bytes(os.urandom(64))
    put_report(device, make_missing("a.bin", A))

    assert cli.main(check(source, device)) == 0

    out = capsys.readouterr().out
    assert out.isascii()
    assert json.loads(out)["unmatched"][0]["path"] == name


def test_the_password_never_appears_in_a_full_run(
    app: Path, server: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    data = os.urandom(64)
    (app / "bios" / "a.bin").write_bytes(data)
    entries = [make_missing("a.bin", md5_of(data))]
    server.files[("bios", "missing_bios_report.txt")] = make_report_text(entries).encode()

    assert cli.main(["--json", "check"], base_dir=app) == 0

    out = capsys.readouterr()
    doc = json.loads(out.out)
    assert doc["target"] == "smb://beck-test-server:445/bios"
    assert statuses(doc) == {"a.bin": "uploaded"}
    assert SENTINEL not in out.out + out.err
    assert "beck-test-user" not in out.out


def test_a_real_process_prints_only_the_document_on_stdout(source: Path, device: Path) -> None:
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    code = "from beck.cli import main; import sys; sys.exit(main(sys.argv[1:]))"

    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code, *check(source, device)],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["ok"] is True


# Report and scan


def test_report_lists_missing_and_incorrect_once_each(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "report.txt"
    report.write_text(
        make_report_text(
            [
                make_missing("ps1/a.bin", A, required=False, system="One"),
                make_missing("ps1/a.bin", B, required=True, system="Two"),
                make_missing("b.bin", A, required=False, system="Two"),
                make_missing("c.bin", A, incorrect=True, current_md5=B, system="Two"),
            ]
        ),
        encoding="utf-8",
        newline="",
    )

    assert cli.main(["--json", "report", "--report-file", str(report)]) == 0

    assert document(capsys) == {
        "schema_version": 1,
        "beck_version": __version__,
        "command": "report",
        "ok": True,
        "frontend": "recalbox",
        "target": None,
        "summary": {"missing": 2, "incorrect": 1},
        "missing": [
            {"name": "b.bin", "target": "b.bin", "md5s": [A], "required": False},
            {"name": "a.bin", "target": "ps1/a.bin", "md5s": [A, B], "required": True},
        ],
        "incorrect": [
            {
                "name": "c.bin",
                "target": "c.bin",
                "md5s": [A],
                "required": True,
                "current_md5": B,
            }
        ],
        "errors": [],
    }


def test_report_from_a_target_names_it(device: Path, capsys: pytest.CaptureFixture[str]) -> None:
    put_report(device, make_missing("a.bin", A))

    assert cli.main(["--json", "report", "--target-dir", str(device)]) == 0

    assert document(capsys)["target"] == device.resolve().as_uri()


def test_report_on_the_real_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = REPORTS / f"{REAL_REPORT}.txt"
    assert load_report(REAL_REPORT)

    assert cli.main(["--json", "report", "--report-file", str(path)]) == 0

    doc = document(capsys)
    assert doc["summary"] == {"missing": 232, "incorrect": 0}
    targets = [item["target"] for item in doc["missing"]]
    assert targets == sorted(targets)
    assert len(targets) == len(set(targets))


def test_a_required_flag_nobody_set_stays_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    renderer = JsonRenderer("report", frontend="recalbox", dry_run=False)

    renderer.report(
        [make_missing("a.bin", A, required=None), make_missing("a.bin", B, required=False)]
    )

    assert document(capsys)["missing"][0]["required"] is None


def test_scan_lists_the_files_and_what_it_could_not_read(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(source, "ps1/a.bin")
    (source / "broken").symlink_to(source / "nowhere")
    before = snapshot(source / "ps1")

    assert cli.main(["--json", "scan", "--source", str(source)]) == 0

    doc = document(capsys)
    assert doc["command"] == "scan"
    assert doc["ok"] is True
    assert doc["summary"] == {"files": 1, "unreadable": 1}
    assert doc["files"] == [{"path": "ps1/a.bin", "md5": file.md5, "size": file.size}]
    assert [item["path"] for item in doc["unreadable"]] == ["broken"]
    assert doc["errors"] == []
    assert set(doc) == {
        "schema_version",
        "beck_version",
        "command",
        "ok",
        "summary",
        "files",
        "unreadable",
        "errors",
    }
    assert snapshot(source / "ps1") == before


def test_scan_uses_no_network(
    source: Path, server: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--json", "scan", "--source", str(source)]) == 0

    assert server.connections == []
    assert document(capsys)["summary"]["files"] == 0
