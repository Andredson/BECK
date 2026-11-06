# SPDX-License-Identifier: GPL-3.0-only
"""A target comes from a report, which could be crafted or corrupted: a bad one is refused (07.6).

One bad entry is one failed item, and the rest of the run carries on. A report BECK can't read at
all is still an error for the whole run.
"""

import json
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from beck import cli
from beck.errors import ReportParseError, TransportError
from beck.frontends.recalbox import RecalboxAdapter
from beck.transports.smb import SmbTransport
from tests.factories import make_bios_file, snapshot
from tests.fakes import FakeSMBServer, install_fake_smb

ROOT = "/recalbox/share/bios/"
A = "a" * 32

# Each is a report entry: its name, and its Path line.
UNSAFE = {
    "path-climbs": ("evil.bin", f"{ROOT}../../etc/evil.bin"),
    "path-climbs-from-inside": ("evil.bin", f"{ROOT}a/../../evil.bin"),
    "path-climbs-at-the-end": ("evil.bin", f"{ROOT}a/.."),
    "path-outside-the-root": ("evil.bin", "/etc/evil.bin"),
    "path-absolute-after-the-root": ("evil.bin", f"{ROOT}/etc/evil.bin"),
    "path-relative": ("evil.bin", "share/bios/evil.bin"),
    "name-climbs": ("../evil.bin", f"{ROOT}evil.bin"),
    "name-is-dots": ("..", f"{ROOT}evil.bin"),
    "name-is-a-dot": (".", f"{ROOT}evil.bin"),
    "name-absolute": ("/etc/evil.bin", f"{ROOT}evil.bin"),
    "name-with-a-slash": ("a/evil.bin", f"{ROOT}evil.bin"),
    "name-with-a-backslash": ("a\\evil.bin", f"{ROOT}evil.bin"),
    "name-climbs-with-backslashes": ("..\\..\\evil.bin", f"{ROOT}evil.bin"),
    "folder-with-a-backslash": ("evil.bin", f"{ROOT}a\\b/evil.bin"),
    "path-ends-with-a-backslash-name": ("evil.bin", f"{ROOT}..\\..\\evil.bin"),
    "name-with-a-replaced-byte": ("ev�il.bin", f"{ROOT}evil.bin"),
    "folder-with-a-replaced-byte": ("evil.bin", f"{ROOT}ev�il/evil.bin"),
    "name-with-an-escape": ("ev\x1b[2Jil.bin", f"{ROOT}evil.bin"),
    "name-with-a-bell": ("ev\x07il.bin", f"{ROOT}evil.bin"),
    "name-with-a-tab": ("ev\til.bin", f"{ROOT}evil.bin"),
    "name-with-del": ("ev\x7fil.bin", f"{ROOT}evil.bin"),
    "name-with-a-one-byte-escape": ("ev\x9bil.bin", f"{ROOT}evil.bin"),
    "name-that-reverses-text": ("ev‮il.bin", f"{ROOT}evil.bin"),
    "folder-with-a-tab": ("evil.bin", f"{ROOT}ev\til/evil.bin"),
    "folder-with-an-escape": ("evil.bin", f"{ROOT}ev\x1b/evil.bin"),
    "no-name": ("", f"{ROOT}evil.bin"),
}
SAFE = {
    "plain": ("a.bin", f"{ROOT}a.bin", "a.bin"),
    "in-a-folder": ("a.bin", f"{ROOT}ps1/a.bin", "ps1/a.bin"),
    "deep": ("a.bin", f"{ROOT}a/b/c/a.bin", "a/b/c/a.bin"),
    "spaces-and-brackets": ("My BIOS (v1) [x].bin", f"{ROOT}My BIOS (v1) [x].bin", None),
    "accents": ("açaí-日本語.bin", f"{ROOT}jogos/açaí-日本語.bin", "jogos/açaí-日本語.bin"),
    "dots-in-a-name": ("a..b.bin", f"{ROOT}a..b.bin", "a..b.bin"),
    "starts-with-a-dot": (".hidden", f"{ROOT}.hidden", ".hidden"),
    "a-doubled-slash-is-harmless": ("a.bin", f"{ROOT}x//a.bin", "x/a.bin"),
    "a-dot-folder-is-harmless": ("a.bin", f"{ROOT}./a.bin", "a.bin"),
}


def block(name: str, path: str, md5: str = A, kind: str = "MISSING REQUIRED") -> str:
    return f"  {kind} BIOS: {name}\n    Path: {path}\n    Possible MD5 List:\n      {md5}\n"


def report_text(*blocks: str) -> str:
    return "MISSING BIOS REPORT\n" + "".join(blocks)


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    source, device = tmp_path / "source", tmp_path / "device"
    source.mkdir()
    device.mkdir()
    return source, device


def put(device: Path, text: str) -> None:
    (device / "missing_bios_report.txt").write_text(text, encoding="utf-8", newline="")


def check(folders: tuple[Path, Path], *flags: str) -> list[str]:
    return ["check", "--source", str(folders[0]), "--target-dir", str(folders[1]), *flags]


# Reading a report


@pytest.mark.parametrize(("name", "path"), UNSAFE.values(), ids=UNSAFE)
def test_an_unsafe_entry_is_rejected_and_the_rest_are_kept(name: str, path: str) -> None:
    adapter = RecalboxAdapter()
    text = report_text(block(name, path), block("good.bin", f"{ROOT}good.bin"))

    assert [entry.name for entry in adapter.parse_report(text)] == ["good.bin"]
    rejected = adapter.rejected_entries(text)
    assert len(rejected) == 1
    assert rejected[0].code == "unsafe_path"
    assert "\n" not in rejected[0].message


@pytest.mark.parametrize(("name", "path", "target"), SAFE.values(), ids=SAFE)
def test_a_safe_entry_is_kept(name: str, path: str, target: str | None) -> None:
    adapter = RecalboxAdapter()
    text = report_text(block(name, path))

    assert adapter.rejected_entries(text) == []
    assert [entry.target for entry in adapter.parse_report(text)] == [PurePosixPath(target or name)]


def test_the_rejected_entry_is_named_and_a_nameless_one_says_which_block() -> None:
    adapter = RecalboxAdapter()
    text = report_text(block("../evil.bin", f"{ROOT}evil.bin"), block("", f"{ROOT}x.bin"))

    named, nameless = adapter.rejected_entries(text)

    assert named.item == "../evil.bin"
    assert "../evil.bin" in named.message
    assert nameless.item == "MISSING REQUIRED BIOS:"


def test_an_incorrect_entry_is_checked_too() -> None:
    adapter = RecalboxAdapter()
    text = report_text(block("../evil.bin", f"{ROOT}evil.bin", kind="INCORRECT REQUIRED"))

    assert adapter.parse_report(text) == []
    assert len(adapter.rejected_entries(text)) == 1


def test_a_second_path_is_ignored_as_it_always_is() -> None:
    """DEC-50: only the first one is ever used, so only that one can do harm."""
    adapter = RecalboxAdapter()
    text = report_text(block("a.bin", f"{ROOT}a.bin or /etc/a.bin"))

    assert adapter.rejected_entries(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "this is not a report",
        "MISSING BIOS REPORT\n  MISSING REQUIRED BIOS: a.bin\n    Possible MD5 List:\n      "
        + A
        + "\n",
        f"MISSING BIOS REPORT\n  MISSING REQUIRED BIOS: a.bin\n    Path: {ROOT}a.bin\n",
    ],
    ids=["not-a-report", "no-path-line", "no-md5"],
)
@pytest.mark.parametrize("method", ["parse_report", "rejected_entries"])
def test_a_report_it_can_not_read_is_still_an_error_for_the_whole_run(
    text: str, method: str
) -> None:
    with pytest.raises(ReportParseError):
        getattr(RecalboxAdapter(), method)(text)


def test_a_bad_current_md5_says_what_is_wrong_with_it() -> None:
    text = report_text(
        f"  MISSING REQUIRED BIOS: a.bin\n    Path: {ROOT}a.bin\n    Current MD5: {'b' * 32}\n"
        f"    Possible MD5 List:\n      {A}\n"
    )

    with pytest.raises(ReportParseError, match="Can't read report block"):
        RecalboxAdapter().parse_report(text)


# Through a run


@pytest.mark.parametrize(("name", "path"), UNSAFE.values(), ids=UNSAFE)
def test_a_run_uploads_the_good_entry_and_nothing_for_the_bad_one(
    folders: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    name: str,
    path: str,
) -> None:
    source, device = folders
    file = make_bios_file(source, "good.bin")
    put(
        device,
        report_text(
            block(name, path, md5=file.md5), block("good.bin", f"{ROOT}good.bin", file.md5)
        ),
    )

    assert cli.main(check(folders)) == 3

    assert sorted(p.name for p in device.rglob("*") if p.is_file()) == [
        "good.bin",
        "missing_bios_report.txt",
    ]
    assert not list(device.parent.glob("evil*"))
    assert "Error: Refused" in capsys.readouterr().out


def test_json_lists_it_as_an_item_and_the_good_upload_still_happens(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, device = folders
    file = make_bios_file(source, "good.bin")
    put(
        device,
        report_text(
            block("..\\evil.bin", f"{ROOT}evil.bin", file.md5),
            block("good.bin", f"{ROOT}good.bin", file.md5),
        ),
    )

    assert cli.main(["--json", *check(folders)]) == 3

    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is False
    assert [(u["target"], u["status"]) for u in document["uploads"]] == [("good.bin", "uploaded")]
    assert [(e["code"], e["item"]) for e in document["errors"]] == [("unsafe_path", "..\\evil.bin")]
    assert document["summary"]["errors"] == 1


def test_a_refused_name_that_looks_like_a_target_does_not_mark_that_upload(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, device = folders
    file = make_bios_file(source, "good.bin")
    put(
        device,
        report_text(
            block("a/evil.bin", f"{ROOT}evil.bin", file.md5),
            block("evil.bin", f"{ROOT}a/evil.bin", file.md5),
        ),
    )

    assert cli.main(["--json", *check(folders)]) == 3

    upload = json.loads(capsys.readouterr().out)["uploads"][0]
    assert (upload["target"], upload["status"], upload["error"]) == ("a/evil.bin", "uploaded", None)


def test_refused_entries_are_sorted_as_every_list_is(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    put(
        folders[1],
        report_text(
            block("../z.bin", f"{ROOT}z.bin"),
            block("../a.bin", f"{ROOT}a.bin"),
        ),
    )

    assert cli.main(["--json", *check(folders)]) == 3

    errors = json.loads(capsys.readouterr().out)["errors"]
    assert [error["item"] for error in errors] == ["../a.bin", "../z.bin"]


def test_a_dry_run_says_so_too_and_changes_nothing(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, device = folders
    file = make_bios_file(source, "good.bin")
    put(device, report_text(block("../evil.bin", f"{ROOT}evil.bin", file.md5)))
    before = snapshot(device)

    assert cli.main(check(folders, "--dry-run")) == 3

    assert snapshot(device) == before
    assert "Error: Refused" in capsys.readouterr().out


@pytest.mark.parametrize("mode", [[], ["--json"]], ids=["human", "json"])
def test_a_report_with_only_a_bad_entry_is_not_nothing_missing(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str], mode: list[str]
) -> None:
    put(folders[1], report_text(block("../evil.bin", f"{ROOT}evil.bin")))
    make_bios_file(folders[0], "a.bin")

    assert cli.main([*mode, *check(folders)]) == 3

    output = capsys.readouterr().out
    assert "No missing bios" not in output
    assert "Refused" in output


@pytest.mark.parametrize("flags", [("--overwrite",), ()], ids=["overwrite", "plain"])
def test_only_a_bad_entry_with_no_local_files_is_still_an_error(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str], flags: tuple[str, ...]
) -> None:
    put(folders[1], report_text(block("../evil.bin", f"{ROOT}evil.bin")))

    assert cli.main(check(folders, *flags)) == 3

    assert "Refused" in capsys.readouterr().out


def test_a_good_entry_with_no_local_files_still_reports_the_bad_one(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    put(
        folders[1],
        report_text(block("../evil.bin", f"{ROOT}evil.bin"), block("a.bin", f"{ROOT}a.bin")),
    )

    assert cli.main(["--json", *check(folders)]) == 3

    document = json.loads(capsys.readouterr().out)
    assert [item["target"] for item in document["still_missing"]] == ["a.bin"]
    assert document["errors"][0]["code"] == "unsafe_path"


def test_only_an_incorrect_file_and_a_bad_entry_is_still_an_error(
    folders: tuple[Path, Path],
) -> None:
    put(
        folders[1],
        report_text(
            block("../evil.bin", f"{ROOT}evil.bin"),
            block("a.bin", f"{ROOT}a.bin", kind="INCORRECT REQUIRED"),
        ),
    )

    assert cli.main(check(folders)) == 3


def test_it_beats_fail_if_missing_as_any_failed_item_does(folders: tuple[Path, Path]) -> None:
    put(
        folders[1],
        report_text(block("../evil.bin", f"{ROOT}evil.bin"), block("a.bin", f"{ROOT}a.bin")),
    )

    assert cli.main(check(folders, "--fail-if-missing")) == 3


def test_clean_unmatched_deletes_nothing_because_the_report_was_not_fully_read(
    folders: tuple[Path, Path],
) -> None:
    """A file that seems to match nothing could be the one a rejected entry asked for."""
    source, device = folders
    file = make_bios_file(source, "wanted.bin")
    other = make_bios_file(source, "other.bin")
    put(
        device,
        report_text(
            block("../evil.bin", f"{ROOT}evil.bin", file.md5),
            block("a.bin", f"{ROOT}a.bin", other.md5),
        ),
    )

    assert cli.main(check(folders, "--clean-unmatched", "--yes")) == 3

    assert file.path.exists()


def test_move_still_moves_what_it_uploaded(folders: tuple[Path, Path]) -> None:
    source, device = folders
    file = make_bios_file(source, "good.bin")
    put(
        device,
        report_text(
            block("../evil.bin", f"{ROOT}evil.bin"), block("good.bin", f"{ROOT}good.bin", file.md5)
        ),
    )

    assert cli.main(check(folders, "--move", "--yes")) == 3

    assert (device / "good.bin").exists()
    assert not file.path.exists()


def test_the_message_shows_a_hostile_name_escaped(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    put(folders[1], report_text(block("ev\x1b[2Jil.bin", f"{ROOT}evil.bin")))

    assert cli.main(check(folders)) == 3

    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert "ev\\x1b[2Jil.bin" in output


def test_json_keeps_the_exact_name_of_what_it_refused(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    put(folders[1], report_text(block("ev\x07il.bin", f"{ROOT}evil.bin")))

    assert cli.main(["--json", *check(folders)]) == 3

    assert json.loads(capsys.readouterr().out)["errors"][0]["item"] == "ev\x07il.bin"


# beck report


@pytest.mark.parametrize("mode", [[], ["--json"]], ids=["human", "json"])
def test_report_lists_the_good_entries_and_refuses_the_bad_one(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str], mode: list[str]
) -> None:
    device = folders[1]
    put(
        device,
        report_text(block("../evil.bin", f"{ROOT}evil.bin"), block("a.bin", f"{ROOT}a.bin")),
    )

    assert cli.main([*mode, "report", "--target-dir", str(device)]) == 3

    output = capsys.readouterr().out
    assert "a.bin" in output
    assert "Refused" in output


def test_report_of_only_a_bad_entry_is_not_nothing_missing(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    device = folders[1]
    put(device, report_text(block("../evil.bin", f"{ROOT}evil.bin")))

    assert cli.main(["report", "--target-dir", str(device)]) == 3

    output = capsys.readouterr().out
    assert "No missing bios" not in output
    assert "Error: Refused" in output


def test_report_as_a_document_says_it_failed(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    device = folders[1]
    put(
        device, report_text(block("../evil.bin", f"{ROOT}evil.bin"), block("a.bin", f"{ROOT}a.bin"))
    )

    assert cli.main(["--json", "report", "--target-dir", str(device)]) == 3

    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is False
    assert [item["target"] for item in document["missing"]] == ["a.bin"]
    assert document["errors"][0]["item"] == "../evil.bin"


# Over SMB, as defense in depth: this is what a transport refuses whoever calls it


BAD_PATHS = {
    "absolute": "/etc/evil.bin",
    "climbs": "../evil.bin",
    "climbs-from-inside": "a/../../evil.bin",
    "backslash": "a\\evil.bin",
    "climbs-with-backslashes": "..\\..\\evil.bin",
    "folder-with-a-backslash": "a\\b/evil.bin",
}


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Any:
    server = install_fake_smb(monkeypatch)
    server.files[("bios", "seeded.bin")] = b"x"
    with SmbTransport("beck-test-server", 445, "bios", "", "", timeout=5) as opened:
        opened.fake_server = server  # type: ignore[attr-defined]
        yield opened


@pytest.mark.parametrize("path", BAD_PATHS.values(), ids=BAD_PATHS)
@pytest.mark.parametrize("operation", ["read_bytes", "exists", "size", "makedirs"])
def test_smb_refuses_a_path_that_could_leave_where_it_should_be(
    transport: SmbTransport, operation: str, path: str
) -> None:
    with pytest.raises(TransportError, match="outside"):
        getattr(transport, operation)(PurePosixPath(path))


@pytest.mark.parametrize("path", BAD_PATHS.values(), ids=BAD_PATHS)
def test_smb_refuses_to_upload_to_such_a_path(
    transport: SmbTransport, tmp_path: Path, path: str
) -> None:
    local = tmp_path / "local.bin"
    local.write_bytes(b"x")
    server: FakeSMBServer = transport.fake_server  # type: ignore[attr-defined]
    before = dict(server.files)

    with pytest.raises(TransportError, match="outside"):
        transport.upload(local, PurePosixPath(path))

    assert server.files == before


def test_smb_still_does_its_job_on_a_good_path(transport: SmbTransport, tmp_path: Path) -> None:
    local = tmp_path / "local.bin"
    local.write_bytes(b"data")
    remote = PurePosixPath("ps1/a..b.bin")

    transport.makedirs(remote.parent)
    assert transport.upload(local, remote) == 4
    assert transport.exists(remote)
    assert transport.size(remote) == 4
    assert transport.read_bytes(remote) == b"data"


def test_a_root_in_the_url_can_not_be_left_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = install_fake_smb(monkeypatch)
    with (
        SmbTransport(
            "beck-test-server", 445, "bios", "", "", timeout=5, root=PurePosixPath("sub")
        ) as opened,
        pytest.raises(TransportError, match="outside"),
    ):
        opened.exists(PurePosixPath("../evil.bin"))

    assert server.connections
