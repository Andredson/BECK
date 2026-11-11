# SPDX-License-Identifier: GPL-3.0-only
"""Full runs through cli.main with a fake SMB server: every stage 03 behavior, end to end.

D1-D14 regression tests that need a whole run live here; the rest are next to each module.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

import pytest
from smb.smb_structs import OperationFailure

import beck
from beck import cli
from beck.errors import TransportError
from beck.frontends.recalbox import RecalboxAdapter
from beck.models import MissingBios
from beck.transports.local import LocalTransport
from tests.conftest import REAL_REPORT, load_report
from tests.factories import make_missing, make_report_text, md5_of, settings_text, snapshot
from tests.fakes import FakeSMBConnection, FakeSMBServer, install_fake_smb

SERVER_URL = "smb://beck-test-server/bios"


def block(name: str, *md5s: str, folder: str = "") -> str:
    hashes = "".join(f"      {md5.upper()}\n" for md5 in md5s)
    return (
        f"  MISSING REQUIRED BIOS: {name}\n"
        f"    Path: /recalbox/share/bios/{folder}{name}\n"
        f"    Possible MD5 List:\n{hashes}\n"
    )


def write(path: Path, data: bytes | None = None) -> bytes:
    content = os.urandom(64) if data is None else data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("this must not be called")


def forbidden_upload(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise TransportError("the disk is full")


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeSMBServer:
    return install_fake_smb(monkeypatch)


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder with settings for a guest and an empty bios folder. It's the current directory."""
    folder = tmp_path / "app"
    write(folder / "settings.toml", settings_text(SERVER_URL).encode())
    (folder / "settings.toml").chmod(0o600)
    monkeypatch.setenv("BECK_CONFIG", str(folder / "settings.toml"))
    (folder / "bios").mkdir()
    monkeypatch.chdir(folder)
    return folder


@pytest.fixture
def account(app: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The same folder, with settings for a user who has a password."""
    write(app / "settings.toml", settings_text(SERVER_URL, "beck-test-user").encode())
    monkeypatch.setenv("BECK_SMB_PASSWORD", "beck-test-password")
    return app


def report(server: FakeSMBServer, text: str | bytes) -> None:
    content = text.encode() if isinstance(text, str) else text
    server.files[("bios", "missing_bios_report.txt")] = content


def run(app: Path) -> int:
    return cli.main(["check"], base_dir=app)


# Settings


def test_no_target_anywhere_prints_what_to_do_and_returns_2(
    tmp_path: Path, server: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path) == 2
    output = capsys.readouterr().out
    assert "BECK has no target" in output
    assert "beck config init" in output
    assert server.connections == []


def test_the_settings_reach_the_connection(
    server: FakeSMBServer, account: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report(server, "MISSING BIOS REPORT\n")

    assert run(account) == 0

    conn = server.connections[0]
    assert (conn.username, conn.password, conn.remote_name) == (
        "beck-test-user",
        "beck-test-password",
        "beck-test-server",
    )
    assert conn.is_direct_tcp is True
    assert "beck-test-password" not in "".join(capsys.readouterr())


# Where files are found


def test_with_no_base_dir_it_uses_the_current_folder(
    server: FakeSMBServer, app: Path, tmp_path: Path
) -> None:
    data = write(app / "bios" / "copy.bin")
    report(server, block("scph5501.bin", md5_of(data)))

    assert cli.main(["check"]) == 0

    assert server.files[("bios", "scph5501.bin")] == data


def test_a_full_run_works_from_an_unrelated_folder(
    server: FakeSMBServer, app: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    data = write(app / "bios" / "ps1" / "my-copy.bin")
    report(server, block("scph5501.bin", md5_of(data)))
    monkeypatch.chdir(elsewhere)

    assert run(app) == 0

    assert server.files[("bios", "scph5501.bin")] == data
    assert list(elsewhere.iterdir()) == []


# One connection, in-memory report


def test_a_full_run_opens_one_connection_and_closes_it(server: FakeSMBServer, app: Path) -> None:
    data = write(app / "bios" / "my-ps1-bios.bin")
    report(server, block("scph5501.bin", md5_of(data), folder="ps1/"))

    assert run(app) == 0

    assert len(server.connections) == 1
    conn = server.connections[0]
    assert conn.calls.count("connect") == 1
    assert conn.calls.count("listShares") == 1
    assert conn.calls[-1] == "close"
    assert server.files[("bios", "ps1/scph5501.bin")] == data


def test_reading_the_report_creates_and_changes_no_local_file(
    server: FakeSMBServer, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report(server, "MISSING BIOS REPORT\n")
    write(app / "test.txt", b"the user's own notes")
    for name in ("NamedTemporaryFile", "TemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, forbidden)
    before = snapshot(app)

    assert run(app) == 0

    # The old code wrote the report to ./test.txt, then deleted it (D6).
    assert snapshot(app) == before


def test_a_report_with_bytes_that_are_not_utf8_still_parses(
    server: FakeSMBServer, app: Path
) -> None:
    data = write(app / "bios" / "copy.bin")
    report(server, b"caf\xe9\n" + block("a.bin", md5_of(data)).encode())

    assert run(app) == 0

    assert server.files[("bios", "a.bin")] == data


def test_a_folder_is_created_only_once_for_two_targets(server: FakeSMBServer, app: Path) -> None:
    md5 = md5_of(write(app / "bios" / "copy.bin"))
    report(server, block("a.bin", md5, folder="ps1/") + block("b.bin", md5, folder="ps1/"))

    assert run(app) == 0

    assert server.connections[0].calls.count("createDirectory") == 1


@pytest.mark.parametrize("existing", [(), ("amiga",), ("amiga", "amiga/bios")])
def test_a_nested_target_uploads_whatever_folders_exist(
    server: FakeSMBServer, app: Path, existing: tuple[str, ...]
) -> None:
    server.dirs.update(("bios", folder) for folder in existing)
    data = write(app / "bios" / "my-copy.rom")
    report(server, block("kick39106.A1200", md5_of(data), folder="amiga/bios/"))

    assert run(app) == 0

    assert server.files[("bios", "amiga/bios/kick39106.A1200")] == data


# The report


def test_real_crlf_report_over_smb_keeps_every_entry(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Regression from step 03.3: CRLF merged the whole real report into one entry.
    report(server, load_report(REAL_REPORT))
    write(app / "bios" / "junk.bin")

    assert run(app) == 0

    output = capsys.readouterr().out
    assert "There are 232 missing bios in your RECALBOX" in output  # 238 blocks, 232 targets
    assert "Final result: 0/232 missing entries satisfied, 1 files analysed" in output


def test_no_missing_bios_says_so_and_closes(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report(server, "MISSING BIOS REPORT\r\n")

    assert run(app) == 0

    output = capsys.readouterr().out
    assert "No missing bios were found" in output
    assert "Final result" not in output
    assert server.connections[0].closed


def incorrect(name: str, *md5s: str) -> str:
    return (
        block(name, *md5s, folder="two/")
        .replace("MISSING REQUIRED", "INCORRECT REQUIRED")
        .replace("    Possible", f"    Current MD5: {'C' * 32}\n    Possible")
    )


def test_an_incorrect_file_is_reported_kept_and_exits_normally(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # DEC-54: the device's file stays, even with a valid local file.
    valid = write(app / "bios" / "b.bin")
    server.dirs.add(("bios", "two"))
    server.files[("bios", "two/b.bin")] = b"the wrong file on the device"
    report(server, incorrect("b.bin", md5_of(valid)))

    assert run(app) == 0

    assert server.files[("bios", "two/b.bin")] == b"the wrong file on the device"
    assert server.connections[0].calls.count("storeFile") == 0
    output = capsys.readouterr().out
    assert "INCORRECT: two/b.bin is on the device with a wrong MD5, and was kept" in output
    assert "No missing bios" not in output
    # Nothing else to do, so it stops here instead of counting 0 missing and scanning.
    assert "There are" not in output
    assert "Final result" not in output


def test_a_real_report_with_incorrect_files(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The same outcome as a real run against the Recalbox 10.1.1 VM that wrote this report.
    report(server, load_report("recalbox-10.1.1/incorrect-files"))
    write(app / "bios" / "junk.bin")

    assert run(app) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "INCORRECT: scummvm/MT32_CONTROL.ROM is on the device with a wrong MD5, and was kept",
        "INCORRECT: xbox/mcpx_1.0.bin is on the device with a wrong MD5, and was kept",
        "There are 78 missing bios in your RECALBOX",
        "There are 1 possible bios to be analysed in your system",
        "junk.bin: no match, kept",
        "Final result: 0/78 missing entries satisfied, 1 files analysed",
    ]
    assert server.connections[0].calls.count("storeFile") == 0


def test_incorrect_files_are_reported_beside_normal_uploads(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good, valid = write(app / "bios" / "good.bin"), write(app / "bios" / "valid.bin")
    report(server, block("a.bin", md5_of(good)) + incorrect("b.bin", md5_of(valid)))

    assert run(app) == 0

    assert server.files[("bios", "a.bin")] == good
    assert ("bios", "two/b.bin") not in server.files
    output = capsys.readouterr().out
    assert "There are 1 missing bios" in output
    assert "INCORRECT: two/b.bin" in output
    assert "valid.bin: valid for two/b.bin, which is incorrect on the device, kept" in output
    assert "Final result: 1/1 missing entries satisfied, 2 files analysed" in output


def test_overwrite_replaces_an_incorrect_file_with_a_valid_one(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # DEC-61: the explicit opt-in that DEC-54 left open.
    valid = write(app / "bios" / "valid.bin")
    server.dirs.add(("bios", "two"))
    server.files[("bios", "two/b.bin")] = b"the wrong file"
    report(server, incorrect("b.bin", md5_of(valid)))

    assert cli.main(["check", "--overwrite"], base_dir=app) == 0

    assert server.files[("bios", "two/b.bin")] == valid
    output = capsys.readouterr().out
    assert "valid.bin: replaced -> two/b.bin" in output
    assert "INCORRECT:" not in output
    assert "Final result: 1/1 missing entries satisfied, 1 files analysed" in output
    assert "PLEASE SCAN" in output


def test_overwrite_still_keeps_an_incorrect_file_with_no_valid_copy(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(app / "bios" / "junk.bin")
    server.dirs.add(("bios", "two"))
    server.files[("bios", "two/b.bin")] = b"the wrong file"
    report(server, incorrect("b.bin", "0" * 32))

    assert cli.main(["check", "--overwrite"], base_dir=app) == 0

    assert server.files[("bios", "two/b.bin")] == b"the wrong file"
    assert (
        "INCORRECT: two/b.bin is on the device with a wrong MD5, and was kept"
        in capsys.readouterr().out
    )


def test_overwrite_with_no_local_files_still_reports_incorrect_files(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report(server, incorrect("b.bin", "0" * 32))

    assert cli.main(["check", "--overwrite"], base_dir=app) == 0

    output = capsys.readouterr().out
    assert "INCORRECT: two/b.bin" in output
    assert "No BIOS files found" in output


def test_a_normal_run_has_no_preview(server: FakeSMBServer, app: Path) -> None:
    # A preview walks the listings a second time, so only a run that might delete has one.
    data = write(app / "bios" / "copy.bin")
    report(server, block("a.bin", md5_of(data)))

    assert run(app) == 0
    listings = server.connections[0].calls.count("listPath")

    server.files.pop(("bios", "a.bin"))
    assert cli.main(["check", "--move", "--yes"], base_dir=app) == 0
    assert server.connections[1].calls.count("listPath") == listings


def test_a_file_already_on_the_device_is_kept_and_exits_0(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A stale report: MISSING means Recalbox didn't find it, but it's there now.
    data = write(app / "bios" / "copy.bin")
    server.files[("bios", "a.bin")] = b"already here"
    report(server, block("a.bin", md5_of(data)))

    assert run(app) == 0

    assert server.files[("bios", "a.bin")] == b"already here"
    assert server.connections[0].calls.count("storeFile") == 0
    output = capsys.readouterr().out
    assert "copy.bin: already on the device, kept -> a.bin" in output
    assert "use --overwrite" in output
    assert "Final result: 0/1 missing entries satisfied" in output
    assert "PLEASE SCAN" not in output


def test_overwrite_replaces_a_file_already_on_the_device(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = write(app / "bios" / "copy.bin")
    server.files[("bios", "a.bin")] = b"already here"
    report(server, block("a.bin", md5_of(data)))

    assert cli.main(["check", "--overwrite"], base_dir=app) == 0

    assert server.files[("bios", "a.bin")] == data
    assert "copy.bin: replaced -> a.bin" in capsys.readouterr().out


def test_an_incorrect_file_is_reported_even_with_no_local_files(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report(server, block("a.bin", "0" * 32) + incorrect("b.bin", "1" * 32))

    assert run(app) == 0

    output = capsys.readouterr().out
    assert "INCORRECT: two/b.bin" in output
    assert "No BIOS files found" in output


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("BIOS STATUS\n", "doesn't look like a report"),
        ("", "doesn't look like a report"),
        ("MISSING BIOS REPORT\n\n  ABSENT REQUIRED BIOS: a.bin\n", "Unrecognized heading"),
        ("MISSING BIOS REPORT\n\nSYSTEM: One\n---\n", "No BIOS block under"),
    ],
    ids=["changed-title", "empty-file", "changed-heading", "system-with-no-block"],
)
def test_an_unrecognized_report_is_exit_4_not_nothing_missing(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str], text: str, message: str
) -> None:
    report(server, text)

    assert run(app) == 4

    output = capsys.readouterr().out
    assert message in output
    assert "No missing bios" not in output


def test_a_missing_report_is_exit_4_and_says_what_to_do(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(app) == 4

    output = capsys.readouterr().out
    assert "missing_bios_report.txt not found on SMB share bios" in output
    assert "Generate the report on the device first" in output
    assert server.connections[0].closed


def test_a_bad_report_block_is_exit_4(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(app / "bios" / "copy.bin")
    report(server, "  MISSING REQUIRED BIOS: a.bin\n    Path: /recalbox/share/bios/a.bin\n")

    assert run(app) == 4

    assert "No MD5 value in report block" in capsys.readouterr().out
    assert server.connections[0].calls.count("storeFile") == 0


@pytest.mark.parametrize("case", [str.upper, str.lower, str.title])
def test_it_matches_whatever_the_case_in_the_report(
    case: Callable[[str], str], server: FakeSMBServer, app: Path
) -> None:
    data = write(app / "bios" / "my-copy.bin")
    report(
        server,
        "  MISSING REQUIRED BIOS: scph5501.bin\n"
        "    Path: /recalbox/share/bios/scph5501.bin\n"
        f"    Possible MD5 List:\n      {case(md5_of(data))}\n",
    )

    assert run(app) == 0

    assert server.files[("bios", "scph5501.bin")] == data


# The local folder


def test_it_prints_one_total_for_the_whole_folder(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("a.bin", "sub/b.bin", "sub/deeper/c.bin"):
        write(app / "bios" / name)
    report(server, block("t.bin", "0" * 32))

    run(app)

    output = capsys.readouterr().out
    assert output.count("possible bios") == 1
    assert "There are 3 possible bios" in output


@pytest.mark.parametrize("hidden", [True, False])
def test_nothing_to_analyse_says_so_and_stops_cleanly(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str], hidden: bool
) -> None:
    (app / "bios" / "empty").mkdir()
    if hidden:
        write(app / "bios" / ".keep", b"")
    report(server, block("t.bin", "0" * 32))

    assert run(app) == 0

    output = capsys.readouterr().out
    assert "No BIOS files found" in output
    assert "Final result" not in output
    assert server.connections[0].closed


@pytest.mark.parametrize("relative", ["ps1/my-copy.bin", "ps1/scph5501.bin"])
def test_a_matching_file_in_a_sub_folder_uploads(
    server: FakeSMBServer, app: Path, relative: str
) -> None:
    data = write(app / "bios" / relative)
    report(server, block("scph5501.bin", md5_of(data)))

    assert run(app) == 0

    assert server.files[("bios", "scph5501.bin")] == data


def test_a_run_never_touches_the_keep_file(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(app / "bios" / ".keep", b"")
    write(app / "bios" / "unrelated.bin")
    report(server, block("t.bin", "0" * 32))

    assert run(app) == 0

    assert (app / "bios" / ".keep").exists()
    assert ".keep" not in capsys.readouterr().out


# Nothing local changes (DEC-02)


def fill_bios_folder(server: FakeSMBServer, bios: Path) -> dict[str, bytes]:
    files = {
        ".keep": b"",
        "a-match.bin": os.urandom(64),
        "c-first-for-target.bin": os.urandom(64),
        "d-second-for-target.bin": os.urandom(64),
        "e-no-match.bin": os.urandom(64),
        "ps1/nested-match.bin": os.urandom(64),
    }
    files["b-copy-of-match.bin"] = files["a-match.bin"]
    for name, data in files.items():
        write(bios / name, data)
    report(
        server,
        block("match.bin", md5_of(files["a-match.bin"]), folder="ps1/")
        + block(
            "filled.bin",
            md5_of(files["c-first-for-target.bin"]),
            md5_of(files["d-second-for-target.bin"]),
            folder="ps1/",
        )
        + block("nested.bin", md5_of(files["ps1/nested-match.bin"]), folder="ps1/"),
    )
    return files


def test_a_full_run_leaves_the_bios_folder_exactly_as_it_was(
    server: FakeSMBServer, app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bios = app / "bios"
    files = fill_bios_folder(server, bios)
    before = snapshot(bios)

    with monkeypatch.context() as blocked:
        for module, names in (
            (os, ("remove", "unlink", "rename", "replace", "rmdir")),
            (Path, ("unlink", "rename", "replace", "rmdir")),
            (shutil, ("rmtree", "move")),
        ):
            for name in names:
                blocked.setattr(module, name, forbidden)
        assert run(app) == 0

    assert snapshot(bios) == before
    assert server.files[("bios", "ps1/match.bin")] == files["a-match.bin"]
    assert server.files[("bios", "ps1/filled.bin")] == files["c-first-for-target.bin"]
    assert server.files[("bios", "ps1/nested.bin")] == files["ps1/nested-match.bin"]


def test_a_run_lists_what_happened_to_each_file(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_bios_folder(server, app / "bios")

    run(app)

    output = capsys.readouterr().out
    for line in (
        "a-match.bin: copied -> ps1/match.bin",
        "b-copy-of-match.bin: duplicate of a-match.bin, kept",
        "c-first-for-target.bin: copied -> ps1/filled.bin",
        "d-second-for-target.bin: target already filled, kept",
        "e-no-match.bin: no match, kept",
        "ps1/nested-match.bin: copied -> ps1/nested.bin",
        "Final result: 3/3 missing entries satisfied, 6 files analysed",
        "*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***",
    ):
        assert line in output
    assert ".keep" not in output


def test_a_summary_counts_targets_and_files(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    md5 = md5_of(write(app / "bios" / "copy.bin"))
    report(server, block("a.bin", md5) + block("b.bin", md5) + block("c.bin", "0" * 32))

    assert run(app) == 0

    assert "2/3 missing entries satisfied, 1 files analysed" in capsys.readouterr().out


# Commands and global options


@pytest.mark.parametrize("command", ["check", "scan", "report"])
def test_each_command_has_help(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([command, "--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert f"usage: beck {command}" in output
    assert "example:" in output
    assert cli.COMMANDS[command][0] in output


def test_help_lists_the_commands_and_examples(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--help"])

    output = capsys.readouterr().out
    for command in ("check", "scan", "report"):
        assert f"  {command} " in output
    assert "examples:" in output
    assert "docs/cli.md" in output


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"beck {beck.__version__}\n"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--no-such-flag"],
        ["check", "--no-such-flag"],
        ["scan", "--no-such-flag"],
        ["no-such-command"],
    ],
    ids=["global", "on-check", "on-scan", "command"],
)
def test_unknown_arguments_exit_2_and_run_nothing(
    arguments: list[str], server: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(arguments)

    assert exit_info.value.code == 2
    assert "usage: beck" in capsys.readouterr().err
    assert server.connections == []


def test_no_command_is_a_usage_error_and_changes_nothing(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Until 1.0, bare `beck` ran check (DEC-70).
    data = write(app / "bios" / "copy.bin")
    report(server, block("a.bin", md5_of(data)))

    with pytest.raises(SystemExit) as exit_info:
        cli.main([], base_dir=app)

    assert exit_info.value.code == 2
    assert ("bios", "a.bin") not in server.files
    captured = capsys.readouterr()
    assert "the following arguments are required: <command>" in captured.err
    assert captured.out == ""


def test_beck_check_has_no_hint(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report(server, "MISSING BIOS REPORT\n")

    assert run(app) == 0

    assert capsys.readouterr().err == ""


def test_scan_lists_path_size_and_md5_in_aligned_columns(
    server: FakeSMBServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    small, large = b"x" * 7, b"y" * 1234
    write(source / "ps1" / "my bios (v1).bin", small)
    write(source / "a.rom", large)

    assert cli.main(["scan", "--source", str(source)], base_dir=tmp_path) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"{md5_of(large)}  1234  a.rom",
        f"{md5_of(small)}     7  ps1/my bios (v1).bin",
        "Files: 2",
    ]


def test_scan_uses_the_default_folder(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = write(app / "bios" / "a.bin")

    assert cli.main(["scan"], base_dir=app) == 0

    assert f"{md5_of(data)}  64  a.bin" in capsys.readouterr().out


def test_scan_shows_what_it_cannot_read_and_it_does_not_change_the_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = write(tmp_path / "a.bin")
    (tmp_path / "broken").symlink_to(tmp_path / "nowhere")

    assert cli.main(["scan", "--source", str(tmp_path)]) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"{md5_of(data)}  64  a.bin",
        "broken: can't be read, skipped: broken symlink",
        "Files: 1, can't be read: 1",
    ]


def test_scan_of_an_empty_folder_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["scan", "--source", str(tmp_path)]) == 0

    assert capsys.readouterr().out.splitlines() == [f"No BIOS files found in {tmp_path}"]


def test_scan_with_no_default_folder_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["scan"], base_dir=tmp_path) == 0

    assert capsys.readouterr().out.splitlines() == [f"No BIOS files found in {tmp_path / 'bios'}"]


def test_scan_with_only_what_it_cannot_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "broken").symlink_to(tmp_path / "nowhere")

    assert cli.main(["scan", "--source", str(tmp_path)]) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"No BIOS files found in {tmp_path}",
        "broken: can't be read, skipped: broken symlink",
    ]


def test_scan_skips_hidden_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path / ".hidden")

    assert cli.main(["scan", "--source", str(tmp_path)]) == 0

    assert "No BIOS files found" in capsys.readouterr().out


def test_scan_of_a_source_that_does_not_exist_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["scan", "--source", str(tmp_path / "nope")]) == 2

    assert "doesn't exist" in capsys.readouterr().out


def test_scan_writes_nothing_uses_no_network_and_needs_no_config(
    server: FakeSMBServer, tmp_path: Path
) -> None:
    write(tmp_path / "a.bin")
    before = snapshot(tmp_path)

    assert cli.main(["scan", "--source", str(tmp_path)], base_dir=tmp_path) == 0

    assert snapshot(tmp_path) == before
    assert server.connections == []


def test_scan_shows_a_name_that_is_not_utf8_escaped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / os.fsdecode(b"bad-\xff.bin")).write_bytes(os.urandom(64))

    assert cli.main(["scan", "--source", str(tmp_path)]) == 0

    assert "  bad-\\xff.bin\n" in capsys.readouterr().out


def test_q_does_not_shorten_a_scan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path / "a.bin")
    (tmp_path / "broken").symlink_to(tmp_path / "nowhere")
    assert cli.main(["scan", "--source", str(tmp_path)]) == 0
    normal = capsys.readouterr().out

    assert cli.main(["-q", "scan", "--source", str(tmp_path)]) == 0

    assert capsys.readouterr().out == normal


def test_v_on_a_scan_logs_on_stderr_and_leaves_stdout_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "a.bin")
    assert cli.main(["scan", "--source", str(tmp_path)]) == 0
    normal = capsys.readouterr().out

    assert cli.main(["-v", "scan", "--source", str(tmp_path)]) == 0

    out = capsys.readouterr()
    assert out.out == normal
    assert "Scanned" in out.err


@pytest.mark.parametrize(
    "arguments",
    [["check", "--no-color"], ["--no-color", "check"]],
    ids=["after", "before"],
)
def test_no_color_works_before_or_after_the_command(
    arguments: list[str],
    server: FakeSMBServer,
    app: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("FORCE_COLOR", "1")
    data = write(app / "bios" / "copy.bin")
    report(server, block("a.bin", md5_of(data)))

    assert cli.main(arguments, base_dir=app) == 0

    assert "\033[" not in capsys.readouterr().out


# Choosing a target


def test_target_url_is_used_instead_of_the_settings_file(
    server: FakeSMBServer, account: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = account
    data = write(app / "bios" / "copy.bin")
    report(server, block("a.bin", md5_of(data), folder="ps1/"))

    assert cli.main(["check", "--target", "smb://other-host:4450/bios"], base_dir=app) == 0

    conn = server.connections[0]
    assert conn.remote_name == "other-host"
    assert server.files[("bios", "ps1/a.bin")] == data
    assert "beck-test-password" not in "".join(capsys.readouterr())


def test_the_password_in_the_old_settings_file_is_never_read(
    server: FakeSMBServer, tmp_path: Path
) -> None:
    write(
        tmp_path / "config" / "config.yml",
        b'smb:\n  user: "beck-test-user"\n  passwd: "beck-test-password"\n  server: "old"\n',
    )
    url = "smb://beck-test-user@beck-test-other/bios"

    # With no terminal to ask on, a user with no password stops here: it doesn't take the old one.
    assert cli.main(["check", "--target", url], base_dir=tmp_path) == 2

    assert server.connections == []


def test_the_password_in_the_environment_goes_with_a_user(
    server: FakeSMBServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BECK_SMB_PASSWORD", "beck-test-password")
    report(server, "MISSING BIOS REPORT\n")

    assert cli.main(["check", "--target", "smb://beck-test-user@host/bios"], base_dir=tmp_path) == 0

    connection = server.connections[0]
    assert (connection.username, connection.password) == ("beck-test-user", "beck-test-password")


def test_a_guest_sends_no_password_even_if_one_is_set(
    server: FakeSMBServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BECK_SMB_PASSWORD", "beck-test-password")
    report(server, "MISSING BIOS REPORT\n")

    assert cli.main(["check", "--target", "smb://host/bios"], base_dir=tmp_path) == 0

    connection = server.connections[0]
    assert (connection.username, connection.password) == ("", "")


def test_target_url_works_with_no_config_file(server: FakeSMBServer, tmp_path: Path) -> None:
    (tmp_path / "bios").mkdir()
    report(server, "MISSING BIOS REPORT\n")

    assert cli.main(["check", "--target", "smb://host/bios"], base_dir=tmp_path) == 0


def test_a_target_with_a_sub_path_reads_and_writes_inside_it(
    server: FakeSMBServer, app: Path
) -> None:
    data = write(app / "bios" / "copy.bin")
    server.shares = ("share",)
    server.dirs.add(("share", "bios"))
    server.files[("share", "bios/missing_bios_report.txt")] = block(
        "a.bin", md5_of(data), folder="ps1/"
    ).encode()

    assert cli.main(["check", "--target", "smb://host/share/bios"], base_dir=app) == 0

    assert server.files[("share", "bios/ps1/a.bin")] == data


def test_a_password_in_the_target_exits_2_and_is_never_printed(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = "smb://beck:beck-test-password@host/bios"

    assert cli.main(["check", "--target", url], base_dir=app) == 2

    captured = capsys.readouterr()
    assert "can't contain a password" in captured.out
    assert "beck-test-password" not in captured.out + captured.err
    assert server.connections == []


def test_both_target_flags_exit_2(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["check", "--target", "smb://host/bios", "--target-dir", str(app)]

    with pytest.raises(SystemExit) as exit_info:
        cli.main(arguments, base_dir=app)

    assert exit_info.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err
    assert server.connections == []


def test_an_unknown_frontend_exits_2_and_lists_the_known_ones(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["check", "--frontend", "batocera"], base_dir=app) == 2

    output = capsys.readouterr().out
    assert "Unknown frontend 'batocera'" in output
    assert "recalbox" in output
    assert server.connections == []


def test_the_known_frontend_can_be_named(server: FakeSMBServer, app: Path) -> None:
    report(server, "MISSING BIOS REPORT\n")

    assert cli.main(["check", "--frontend", "recalbox"], base_dir=app) == 0


@pytest.fixture
def device(tmp_path: Path) -> Path:
    """A folder standing in for a mounted SD card."""
    folder = tmp_path / "sdcard"
    folder.mkdir()
    return folder


def test_target_dir_copies_files_to_a_folder_with_no_smb(
    app: Path, device: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "SmbTransport", forbidden)
    data = write(app / "bios" / "copy.bin")
    write(
        device / "missing_bios_report.txt", block("a.bin", md5_of(data), folder="ps1/x/").encode()
    )
    before = snapshot(app / "bios")

    assert cli.main(["check", "--target-dir", str(device)], base_dir=app) == 0

    assert (device / "ps1" / "x" / "a.bin").read_bytes() == data
    assert snapshot(app / "bios") == before
    assert (
        "Final result: 1/1 missing entries satisfied, 1 files analysed" in capsys.readouterr().out
    )


def test_target_dir_with_no_report_is_exit_4(
    app: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["check", "--target-dir", str(device)], base_dir=app) == 4

    assert f"not found on local folder {device.resolve()}" in capsys.readouterr().out


def test_a_missing_target_dir_is_exit_3(
    app: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "no-such-folder"

    assert cli.main(["check", "--target-dir", str(missing)], base_dir=app) == 3

    assert "doesn't exist" in capsys.readouterr().out


def test_target_dir_needs_no_config_file(device: Path, tmp_path: Path) -> None:
    write(device / "missing_bios_report.txt", b"MISSING BIOS REPORT\n")

    assert cli.main(["check", "--target-dir", str(device)], base_dir=tmp_path) == 0


def test_report_accepts_the_target_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["report", "--help"])

    output = capsys.readouterr().out
    assert "--target URL" in output
    assert "--target-dir DIR" in output
    assert "--report-file FILE" in output


def test_scan_has_no_target_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["scan", "--target", "smb://host/bios"])

    assert exit_info.value.code == 2


# --source and --report-file


def test_source_is_used_instead_of_the_bios_folder(
    server: FakeSMBServer, app: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(app / "bios" / "ignored.bin")
    data = write(tmp_path / "elsewhere" / "ps1" / "copy.bin")
    report(server, block("a.bin", md5_of(data)))

    assert cli.main(["check", "--source", str(tmp_path / "elsewhere")], base_dir=app) == 0

    assert server.files[("bios", "a.bin")] == data
    output = capsys.readouterr().out
    assert "ps1/copy.bin: copied -> a.bin" in output
    assert "ignored.bin" not in output


def test_a_relative_source_is_relative_to_the_current_folder(
    server: FakeSMBServer, app: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = write(tmp_path / "work" / "mine" / "copy.bin")
    report(server, block("a.bin", md5_of(data)))
    monkeypatch.chdir(tmp_path / "work")

    assert cli.main(["check", "--source", "mine"], base_dir=app) == 0

    assert server.files[("bios", "a.bin")] == data


@pytest.mark.parametrize("name", ["no-such-folder", "a-file"])
def test_a_source_that_isnt_a_folder_exits_2(
    name: str,
    server: FakeSMBServer,
    app: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Treating a typo as an empty folder would say "No BIOS files found" and exit 0.
    write(tmp_path / "a-file")

    assert cli.main(["check", "--source", str(tmp_path / name)], base_dir=app) == 2

    assert f"The source folder {tmp_path / name} doesn't exist" in capsys.readouterr().out
    assert server.connections == []


def test_a_missing_default_bios_folder_still_says_no_files(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (app / "bios").rmdir()
    report(server, block("a.bin", "0" * 32))

    assert run(app) == 0

    assert "No BIOS files found" in capsys.readouterr().out


def local_report(tmp_path: Path, text: str) -> str:
    file = tmp_path / "copy-of-the-report.txt"
    file.write_bytes(text.encode())
    return str(file)


def test_check_with_a_report_file_ignores_the_report_on_the_target(
    server: FakeSMBServer, app: Path, tmp_path: Path
) -> None:
    data = write(app / "bios" / "copy.bin")
    report(server, "MISSING BIOS REPORT\n")  # says nothing is missing
    file = local_report(tmp_path, block("a.bin", md5_of(data), folder="ps1/"))

    assert cli.main(["check", "--report-file", file], base_dir=app) == 0

    assert server.files[("bios", "ps1/a.bin")] == data
    assert server.connections[0].calls.count("retrieveFile") == 0


def test_check_with_a_report_file_still_needs_a_target(
    server: FakeSMBServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = local_report(tmp_path, "MISSING BIOS REPORT\n")

    assert cli.main(["check", "--report-file", file], base_dir=tmp_path) == 2

    assert "BECK has no target" in capsys.readouterr().out


def test_check_can_combine_a_report_file_and_a_target(
    server: FakeSMBServer, tmp_path: Path
) -> None:
    (tmp_path / "bios").mkdir()
    data = write(tmp_path / "bios" / "copy.bin")
    file = local_report(tmp_path, block("a.bin", md5_of(data)))

    arguments = ["check", "--report-file", file, "--target", "smb://host/bios"]
    assert cli.main(arguments, base_dir=tmp_path) == 0

    assert server.files[("bios", "a.bin")] == data


def test_report_from_a_file_uses_no_network_and_no_config(
    server: FakeSMBServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        block("b.bin", "0" * 32, folder="ps1/")
        + block("a.bin", "1" * 32, folder="ps1/").replace("REQUIRED", "OPTIONAL")
        + block("root.bin", "2" * 32)
        + block("kick.rom", "3" * 32, folder="amiga/bios/")
    )
    file = local_report(tmp_path, text)

    assert cli.main(["report", "--report-file", file], base_dir=tmp_path) == 0

    assert server.connections == []
    assert capsys.readouterr().out.splitlines() == [
        "There are 4 missing bios in your RECALBOX",
        "(BIOS folder)",
        "  root.bin (required)",
        "amiga/bios/",
        "  kick.rom (required)",
        "ps1/",
        "  a.bin (optional)",
        "  b.bin (required)",
    ]


@pytest.mark.parametrize("optional_first", [True, False], ids=["optional-first", "required-first"])
def test_report_lists_a_repeated_target_once_and_required_wins(
    optional_first: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    optional = block("x.pce", "0" * 32).replace("REQUIRED", "OPTIONAL")
    required = block("x.pce", "1" * 32)
    text = optional + required if optional_first else required + optional
    file = local_report(tmp_path, text)

    assert cli.main(["report", "--report-file", file], base_dir=tmp_path) == 0

    assert capsys.readouterr().out.splitlines() == [
        "There are 1 missing bios in your RECALBOX",
        "(BIOS folder)",
        "  x.pce (required)",
    ]


def test_report_shows_incorrect_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = local_report(tmp_path, incorrect("b.bin", "0" * 32))

    assert cli.main(["report", "--report-file", file], base_dir=tmp_path) == 0

    output = capsys.readouterr().out
    assert "INCORRECT: two/b.bin (required) is on the device with a wrong MD5" in output
    assert "No missing bios" not in output
    assert "There are" not in output


def test_report_says_whether_an_incorrect_file_is_required_and_does_not_say_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A report changes nothing, so it has kept nothing."""
    report_path = tmp_path / "report.txt"
    report_path.write_text(
        make_report_text(
            [
                make_missing("ps1/bad.bin", "0" * 32, incorrect=True, system="One"),
                make_missing("spare.bin", "1" * 32, required=False, incorrect=True, system="One"),
                make_missing("both.bin", "2" * 32, required=False, incorrect=True, system="One"),
                make_missing("both.bin", "3" * 32, required=True, incorrect=True, system="Two"),
            ]
        ),
        encoding="utf-8",
        newline="",
    )

    assert cli.main(["report", "--report-file", str(report_path)]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "INCORRECT: both.bin (required) is on the device with a wrong MD5",
        "INCORRECT: ps1/bad.bin (required) is on the device with a wrong MD5",
        "INCORRECT: spare.bin (optional) is on the device with a wrong MD5",
    ]


def test_report_counts_a_file_as_required_when_the_report_does_not_say(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = [
        make_missing("a.bin", "0" * 32, required=None),
        make_missing("b.bin", "1" * 32, required=None, incorrect=True),
    ]
    monkeypatch.setattr(RecalboxAdapter, "parse_report", lambda _self, _text: entries)

    file = local_report(tmp_path, "MISSING BIOS REPORT\n")

    assert cli.main(["report", "--report-file", file]) == 0

    output = capsys.readouterr().out
    assert "  a.bin (required)" in output
    assert "INCORRECT: b.bin (required)" in output


def test_report_with_nothing_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = local_report(tmp_path, "MISSING BIOS REPORT\n")

    assert cli.main(["report", "--report-file", file], base_dir=tmp_path) == 0

    assert "No missing bios were found" in capsys.readouterr().out


def test_report_of_the_real_fixture(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    file = local_report(tmp_path, load_report(REAL_REPORT))

    assert cli.main(["report", "--report-file", file], base_dir=tmp_path) == 0

    output = capsys.readouterr().out
    assert "There are 232 missing bios in your RECALBOX" in output
    assert "amiga/bios/\n" in output
    assert "  kick39106.A1200 (required)\n" in output


def test_report_reads_the_target_and_writes_nothing(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(app / "bios" / "copy.bin")
    report(server, block("a.bin", md5_of((app / "bios" / "copy.bin").read_bytes()), folder="x/"))

    assert cli.main(["report"], base_dir=app) == 0

    calls = server.connections[0].calls
    assert "storeFile" not in calls
    assert "createDirectory" not in calls
    assert ("bios", "x/a.bin") not in server.files
    assert "  a.bin (required)" in capsys.readouterr().out


def test_report_from_a_target_folder(
    device: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(device / "missing_bios_report.txt", block("a.bin", "0" * 32).encode())
    before = snapshot(device)

    assert cli.main(["report", "--target-dir", str(device)], base_dir=tmp_path) == 0

    assert snapshot(device) == before
    assert "  a.bin (required)" in capsys.readouterr().out


def test_report_file_and_a_target_together_exit_2(
    server: FakeSMBServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["report", "--report-file", "x.txt", "--target", "smb://host/bios"]

    with pytest.raises(SystemExit) as exit_info:
        cli.main(arguments, base_dir=tmp_path)

    assert exit_info.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["check", "report"])
def test_a_missing_report_file_is_exit_4(
    command: str, server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([command, "--report-file", "no-such-report.txt"], base_dir=app) == 4

    output = capsys.readouterr().out
    assert "Can't read the report no-such-report.txt: No such file or directory" in output


def test_a_folder_as_report_file_is_exit_4(tmp_path: Path) -> None:
    assert cli.main(["report", "--report-file", str(tmp_path)], base_dir=tmp_path) == 4


def test_a_report_file_in_an_unknown_format_is_exit_4(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = local_report(tmp_path, "A FORMAT BECK DOESN'T KNOW\n")

    assert cli.main(["report", "--report-file", file], base_dir=tmp_path) == 4

    assert "doesn't look like a report" in capsys.readouterr().out


def test_a_report_file_with_bytes_that_arent_utf8_still_parses(tmp_path: Path) -> None:
    file = tmp_path / "report.txt"
    file.write_bytes(b"caf\xe9\n" + block("a.bin", "0" * 32).encode())

    assert cli.main(["report", "--report-file", str(file)], base_dir=tmp_path) == 0


def test_scan_accepts_source_but_report_does_not(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["scan", "--help"])
    assert "--source DIR" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["report", "--source", "x"])
    assert exit_info.value.code == 2


# Every way out of cli.main, by exit code


def test_unreadable_local_files_are_reported_and_the_good_ones_upload(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = write(app / "bios" / "good.bin")
    (app / "bios" / "broken.bin").symlink_to(app / "no-such-target")
    os.mkfifo(app / "bios" / "pipe.bin")
    report(server, block("a.bin", md5_of(good)))

    assert run(app) == 0  # DEC-59: an unreadable file doesn't change the exit code

    assert server.files[("bios", "a.bin")] == good
    captured = capsys.readouterr()
    assert "broken.bin: can't be read, skipped: broken symlink" in captured.out
    assert "pipe.bin: can't be read, skipped: not a regular file" in captured.out
    assert "There are 1 possible bios" in captured.out
    assert "Final result: 1/1 missing entries satisfied, 1 files analysed" in captured.out
    assert captured.err == ""  # no traceback


def test_only_unreadable_files_says_so_and_stops_cleanly(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (app / "bios" / "broken.bin").symlink_to(app / "no-such-target")
    report(server, block("a.bin", "0" * 32))

    assert run(app) == 0

    output = capsys.readouterr().out
    assert "broken.bin: can't be read, skipped: broken symlink" in output
    assert "No BIOS files found" in output
    assert "Final result" not in output


def test_unreadable_files_stay_as_they_were(server: FakeSMBServer, app: Path) -> None:
    link = app / "bios" / "broken.bin"
    link.symlink_to(app / "no-such-target")
    write(app / "bios" / "good.bin")
    report(server, block("a.bin", "0" * 32))

    run(app)

    assert link.is_symlink()
    assert not (app / "no-such-target").exists()


def test_exit_0_a_normal_run(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = write(app / "bios" / "copy.bin")
    write(app / "bios" / "junk.bin")
    report(server, block("a.bin", md5_of(file), folder="ps1/") + block("b.bin", "0" * 32))

    assert cli.main(["check"], base_dir=app) == 0

    output = capsys.readouterr().out
    for line in (
        "There are 2 missing bios in your RECALBOX",
        "There are 2 possible bios to be analysed in your system",
        "FOUND: a.bin -> ps1/a.bin",
        "copy.bin: copied -> ps1/a.bin",
        "junk.bin: no match, kept",
        "Final result: 1/2 missing entries satisfied, 2 files analysed",
        "*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***",
    ):
        assert line in output


def test_exit_0_nothing_matched_has_no_scan_message(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(app / "bios" / "junk.bin")
    report(server, block("a.bin", "0" * 32))

    assert cli.main(["check"], base_dir=app) == 0

    output = capsys.readouterr().out
    assert "Final result: 0/1 missing entries satisfied, 1 files analysed" in output
    assert "PLEASE SCAN" not in output


def test_exit_0_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    assert exit_info.value.code == 0
    assert "usage: beck" in capsys.readouterr().out


def test_exit_2_usage_error(server: FakeSMBServer, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["check", "--no-such-flag"])

    assert exit_info.value.code == 2
    assert "unrecognized arguments: --no-such-flag" in capsys.readouterr().err
    assert server.connections == []


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (None, "not found"),
        ("this is not toml\n", "isn't valid TOML"),
        ("other = 1\n", "schema_version: missing"),
        ('schema_version = 1\n[smb]\ntimeout = "ten"\n', "smb.timeout"),
    ],
    ids=["missing", "malformed", "no-version", "wrong-value"],
)
def test_exit_2_config_error(
    server: FakeSMBServer,
    app: Path,
    capsys: pytest.CaptureFixture[str],
    config: str | None,
    message: str,
) -> None:
    if config is None:
        (app / "settings.toml").unlink()
    else:
        write(app / "settings.toml", config.encode())

    assert cli.main(["check"], base_dir=app) == 2

    assert message in capsys.readouterr().out
    assert server.connections == []


def test_exit_3_one_failed_upload_after_the_others_finish(
    server: FakeSMBServer,
    app: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, bad = write(app / "bios" / "good.bin"), write(app / "bios" / "bad.bin")
    report(server, block("a.bin", md5_of(good)) + block("b.bin", md5_of(bad)))
    real_store = FakeSMBConnection.storeFile

    def fail_for_b(
        self: FakeSMBConnection, share: str, path: str, *args: Any, **kwargs: Any
    ) -> int:
        if path == "b.bin":
            raise OSError("disk full")
        return real_store(self, share, path, *args, **kwargs)

    monkeypatch.setattr(FakeSMBConnection, "storeFile", fail_for_b)

    assert cli.main(["check"], base_dir=app) == 3

    assert server.files[("bios", "a.bin")] == good
    output = capsys.readouterr().out
    assert "good.bin: copied -> a.bin" in output
    assert "bad.bin: failed -> b.bin" in output
    assert "disk full" in output
    assert "Final result: 1/2 missing entries satisfied, 2 files analysed" in output
    assert "PLEASE SCAN" in output


# The real entry points, in a new process. A folder with no config, so they can't reach any device.


def test_python_dash_m_beck_help_runs_as_a_process(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "beck", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert "usage: beck" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "command",
    [
        [sys.executable, "-m", "beck", "check"],
        [str(Path(sys.executable).with_name("beck")), "check"],
    ],
    ids=["python-m", "console-script"],
)
def test_the_exit_code_reaches_the_operating_system(tmp_path: Path, command: list[str]) -> None:
    result = subprocess.run(  # noqa: S603 - fixed arguments, no external input
        command, capture_output=True, text=True, check=False, cwd=tmp_path
    )

    assert result.returncode == 2
    assert "BECK has no target" in result.stdout
    assert result.stderr == ""


def test_a_usage_error_reaches_the_operating_system(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "beck", "check", "--no-such-flag"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


# Color, through the real command


def test_no_color_means_no_escape_codes(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = write(app / "bios" / "copy.bin")
    report(server, block("a.bin", md5_of(file)))

    assert run(app) == 0

    assert "\033[" not in capsys.readouterr().out


def test_force_color_reaches_the_output(
    server: FakeSMBServer,
    app: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("FORCE_COLOR", "1")
    file = write(app / "bios" / "copy.bin")
    report(server, block("a.bin", md5_of(file)))

    assert run(app) == 0

    assert "\033[92mFOUND:\033[0m a.bin -> a.bin" in capsys.readouterr().out


# Failures


def test_a_failed_upload_is_exit_3_and_leaves_the_folder_as_it_was(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bios = app / "bios"
    fill_bios_folder(server, bios)
    before = snapshot(bios)
    server.failures["storeFile"] = OSError("disk full")

    assert run(app) == 3

    assert snapshot(bios) == before
    output = capsys.readouterr().out
    assert "disk full" in output
    assert "Final result: 0/3 missing entries satisfied" in output
    assert "PLEASE SCAN" not in output
    assert server.connections[0].closed


def _connect_fails(server: FakeSMBServer) -> None:
    server.failures["connect"] = OSError("No route to host")


def _login_refused(server: FakeSMBServer) -> None:
    server.login_succeeds = False


def _listing_shares_fails(server: FakeSMBServer) -> None:
    server.failures["listShares"] = OperationFailure("access denied", [])


def _share_missing(server: FakeSMBServer) -> None:
    server.shares = ("share",)


def _report_unreadable(server: FakeSMBServer) -> None:
    server.files[("bios", "missing_bios_report.txt")] = b""
    server.failures["retrieveFile"] = OperationFailure("access denied", [])


@pytest.mark.parametrize(
    ("break_server", "message"),
    [
        (_connect_fails, "Error connecting to SMB server beck-test-server: No route to host"),
        (_login_refused, "SMB server beck-test-server refused the login"),
        (_listing_shares_fails, "Error listing the shares of SMB server beck-test-server"),
        (_share_missing, "The share bios doesn't exist on SMB server beck-test-server"),
        (_report_unreadable, "Error reading missing_bios_report.txt from share bios"),
    ],
)
def test_a_transport_error_prints_returns_3_and_closes(
    server: FakeSMBServer,
    account: Path,
    capsys: pytest.CaptureFixture[str],
    break_server: Callable[[FakeSMBServer], None],
    message: str,
) -> None:
    break_server(server)

    assert run(account) == 3

    output = capsys.readouterr().out
    assert f"Error: {message}" in output
    assert "beck-test-password" not in output
    assert server.connections[0].closed


def test_an_unexpected_error_returns_1_with_a_traceback_on_stderr(
    server: FakeSMBServer,
    app: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report(server, block("a.bin", "0" * 32))

    def a_bug(_folder: Path, _on_file: Any) -> NoReturn:
        raise RuntimeError("a bug in BECK")

    monkeypatch.setattr(cli, "scan", a_bug)

    assert run(app) == 1

    captured = capsys.readouterr()
    assert "Unexpected error" in captured.err
    assert "RuntimeError: a bug in BECK" in captured.err
    assert "a bug in BECK" not in captured.out
    assert server.connections[0].closed


def test_a_full_run_warns_when_an_upload_changes_the_extension(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = write(app / "bios" / "neocd.bin")
    report(server, block("neocdz.zip", md5_of(data)))

    assert cli.main(["check"], base_dir=app) == 0

    assert server.files[("bios", "neocdz.zip")] == data
    output = capsys.readouterr().out
    assert "neocd.bin: copied -> neocdz.zip\nWarning: neocd.bin has a different extension" in output


# File names stdout can't show (D18), and failed checks in a dry run (D19)

BAD_NAME = os.fsdecode(b"bad-\xff.bin")
BAD_NAME_SHOWN = "bad-\\xff.bin"


def test_a_run_with_a_name_that_is_not_valid_utf8_finishes(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = write(app / "bios" / "good.bin")
    (app / "bios" / BAD_NAME).write_bytes(os.urandom(64))
    report(server, block("good.bin", md5_of(data)))

    assert run(app) == 0

    assert server.files[("bios", "good.bin")] == data
    output = capsys.readouterr().out
    assert f"{BAD_NAME_SHOWN}: no match, kept" in output
    assert "Final result: 1/1 missing entries satisfied, 2 files analysed" in output
    assert "PLEASE SCAN" in output


def test_a_move_with_a_name_that_is_not_valid_utf8_tells_what_it_deleted(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The run that found D18: the file went, then BECK crashed and exited with 1."""
    data = write(app / "bios" / "good.bin")
    (app / "bios" / BAD_NAME).write_bytes(os.urandom(64))
    report(server, block("good.bin", md5_of(data)))

    assert cli.main(["check", "--move", "--yes"], base_dir=app) == 0

    assert not (app / "bios" / "good.bin").exists()
    assert (app / "bios" / BAD_NAME).exists()
    output = capsys.readouterr().out
    assert "good.bin: deleted" in output
    assert "Deleted 1 local files." in output
    assert "PLEASE SCAN" in output


def test_a_file_named_badly_in_utf8_can_still_be_uploaded(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = os.urandom(64)
    (app / "bios" / BAD_NAME).write_bytes(data)
    report(server, block("a.zip", md5_of(data)))

    assert run(app) == 0

    assert server.files[("bios", "a.zip")] == data
    output = capsys.readouterr().out
    assert f"{BAD_NAME_SHOWN}: copied -> a.zip" in output
    assert f"Warning: {BAD_NAME_SHOWN} has a different extension from a.zip" in output


def test_an_unreadable_name_that_is_not_valid_utf8_is_listed(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (app / "bios" / BAD_NAME).symlink_to(app / "bios" / "nowhere")
    report(server, block("a.bin", "a" * 32))

    assert run(app) == 0

    assert f"{BAD_NAME_SHOWN}: can't be read, skipped" in capsys.readouterr().out


def test_a_folder_named_badly_in_utf8_cannot_break_an_error_message(
    app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["check", "--source", str(app / BAD_NAME)]

    assert cli.main(arguments, base_dir=app) == 2

    assert f"{BAD_NAME_SHOWN} doesn't exist" in capsys.readouterr().out


def test_an_empty_folder_named_badly_in_utf8_cannot_break_the_message(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (app / BAD_NAME).mkdir()
    report(server, block("a.bin", "a" * 32))

    assert cli.main(["check", "--source", str(app / BAD_NAME)], base_dir=app) == 0

    assert f"No BIOS files found in {app}/{BAD_NAME_SHOWN}" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("stdout_encoding", "name", "shown"),
    [
        ("utf-8:strict", BAD_NAME, BAD_NAME_SHOWN),
        ("ascii:strict", "é.bin", "\\xe9.bin"),
        ("ascii:strict", BAD_NAME, BAD_NAME_SHOWN),
    ],
    ids=["utf8", "encode-accent", "encode-bad-name"],
)
def test_a_real_process_finishes_with_a_stdout_that_cannot_encode_a_name(
    tmp_path: Path, stdout_encoding: str, name: str, shown: str
) -> None:
    """A real stdout, in case pytest's capture hides or causes something."""
    source, device = tmp_path / "source", tmp_path / "device"
    good = write(source / "good.bin")
    (source / name).write_bytes(os.urandom(64))
    device.mkdir()
    (device / "missing_bios_report.txt").write_text(block("good.bin", md5_of(good)))

    result = subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [
            sys.executable,
            "-m",
            "beck",
            "check",
            "--source",
            str(source),
            "--target-dir",
            str(device),
            "--move",
            "--yes",
        ],
        capture_output=True,
        check=False,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONIOENCODING": stdout_encoding},
    )

    output = result.stdout.decode("ascii" if "ascii" in stdout_encoding else "utf-8")
    assert result.returncode == 0, result.stderr
    assert f"{shown}: no match, kept" in output
    assert "Deleted 1 local files." in output
    assert (device / "good.bin").read_bytes() == good
    assert not (source / "good.bin").exists()
    assert (source / name).exists()


def test_a_failed_check_in_a_dry_run_says_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, device = tmp_path / "source", tmp_path / "device"
    data = write(source / "a.bin")
    device.mkdir()
    report_file = tmp_path / "report.txt"
    report_file.write_text(block("a.bin", md5_of(data)))

    def exists(_self: LocalTransport, _path: PurePosixPath) -> bool:
        raise TransportError("the network went away")

    monkeypatch.setattr(LocalTransport, "exists", exists)
    arguments = [
        "check",
        "--source",
        str(source),
        "--target-dir",
        str(device),
        "--report-file",
        str(report_file),
        "--dry-run",
    ]

    assert cli.main(arguments) == 3

    output = capsys.readouterr().out
    assert "a.bin: failed -> a.bin" in output
    assert "would copy" not in output
    assert "Dry run: 0/1 missing entries would be satisfied" in output


# Exit 5: --fail-if-missing


def fills(path: Path) -> str:
    """A local file with random bytes, and the MD5 a report entry needs to match it."""
    return md5_of(write(path))


def on_the_device(device: Path, *entries: MissingBios) -> None:
    (device / "missing_bios_report.txt").write_text(
        make_report_text(entries), encoding="utf-8", newline=""
    )


def check_run(source: Path, device: Path, *flags: str) -> int:
    source.mkdir(exist_ok=True)
    return cli.main(["check", "--source", str(source), "--target-dir", str(device), *flags])


ZERO, ONE = "0" * 32, "1" * 32


def test_exit_5_a_required_file_is_still_missing_and_the_rest_still_uploads(
    tmp_path: Path, device: Path
) -> None:
    source = tmp_path / "source"
    md5 = fills(source / "good.bin")
    on_the_device(device, make_missing("good.bin", md5), make_missing("gone.bin", ZERO))

    assert check_run(source, device, "--fail-if-missing") == 5

    assert (device / "good.bin").exists()


def test_exit_5_with_no_local_files_at_all(tmp_path: Path, device: Path) -> None:
    on_the_device(device, make_missing("gone.bin", ZERO))

    assert check_run(tmp_path / "source", device, "--fail-if-missing") == 5


def test_exit_5_when_the_report_does_not_say_whether_it_is_required(
    tmp_path: Path, device: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = [make_missing("gone.bin", ZERO, required=None)]
    monkeypatch.setattr(RecalboxAdapter, "parse_report", lambda _self, _text: entries)
    on_the_device(device)

    assert check_run(tmp_path / "source", device, "--fail-if-missing") == 5


def test_exit_5_when_any_system_requires_the_file(tmp_path: Path, device: Path) -> None:
    on_the_device(
        device,
        make_missing("gone.bin", ZERO, required=False, system="One"),
        make_missing("gone.bin", ONE, required=True, system="Two"),
    )

    assert check_run(tmp_path / "source", device, "--fail-if-missing") == 5


def test_exit_5_a_required_incorrect_file_counts(tmp_path: Path, device: Path) -> None:
    """DEC-59: the device still can't use it. This run ends early, with nothing to upload."""
    write(device / "bad.bin")
    on_the_device(device, make_missing("bad.bin", ZERO, incorrect=True))

    assert check_run(tmp_path / "source", device, "--fail-if-missing") == 5


def test_exit_5_a_required_incorrect_file_with_no_replacement_counts_with_overwrite(
    tmp_path: Path, device: Path
) -> None:
    source = tmp_path / "source"
    md5 = fills(source / "good.bin")
    write(device / "bad.bin")
    on_the_device(
        device, make_missing("good.bin", md5), make_missing("bad.bin", ZERO, incorrect=True)
    )

    assert check_run(source, device, "--fail-if-missing", "--overwrite") == 5


def test_exit_5_with_overwrite_and_no_local_files(tmp_path: Path, device: Path) -> None:
    write(device / "bad.bin")
    on_the_device(device, make_missing("bad.bin", ZERO, incorrect=True))

    assert check_run(tmp_path / "source", device, "--fail-if-missing", "--overwrite") == 5


def test_exit_5_after_deleting_what_it_was_asked_to(tmp_path: Path, device: Path) -> None:
    source = tmp_path / "source"
    md5 = fills(source / "good.bin")
    on_the_device(device, make_missing("good.bin", md5), make_missing("gone.bin", ZERO))

    assert check_run(source, device, "--fail-if-missing", "--move", "--yes") == 5

    assert not (source / "good.bin").exists()


def test_exit_5_an_unreadable_local_file_does_not_hide_it(tmp_path: Path, device: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "broken").symlink_to(source / "nowhere")
    on_the_device(device, make_missing("gone.bin", ZERO))

    assert check_run(source, device, "--fail-if-missing") == 5


def test_exit_5_a_dry_run_predicts_it_and_changes_nothing(tmp_path: Path, device: Path) -> None:
    source = tmp_path / "source"
    md5 = fills(source / "good.bin")
    on_the_device(device, make_missing("good.bin", md5), make_missing("gone.bin", ZERO))
    before = snapshot(device)

    assert check_run(source, device, "--fail-if-missing", "--dry-run") == 5

    assert snapshot(device) == before


def test_exit_0_a_dry_run_that_would_fill_everything(tmp_path: Path, device: Path) -> None:
    source = tmp_path / "source"
    on_the_device(device, make_missing("good.bin", fills(source / "good.bin")))

    assert check_run(source, device, "--fail-if-missing", "--dry-run") == 0

    assert not (device / "good.bin").exists()


def test_exit_0_without_the_flag_when_a_required_file_is_missing(
    tmp_path: Path, device: Path
) -> None:
    on_the_device(device, make_missing("gone.bin", ZERO))

    assert check_run(tmp_path / "source", device) == 0


def test_exit_0_with_the_flag_when_everything_was_filled(tmp_path: Path, device: Path) -> None:
    source = tmp_path / "source"
    on_the_device(device, make_missing("good.bin", fills(source / "good.bin")))

    assert check_run(source, device, "--fail-if-missing") == 0


def test_exit_0_with_the_flag_when_nothing_is_missing(tmp_path: Path, device: Path) -> None:
    on_the_device(device)

    assert check_run(tmp_path / "source", device, "--fail-if-missing") == 0


def test_exit_0_with_the_flag_when_only_optional_files_are_missing(
    tmp_path: Path, device: Path
) -> None:
    write(device / "bad.bin")
    on_the_device(
        device,
        make_missing("gone.bin", ZERO, required=False),
        make_missing("bad.bin", ONE, required=False, incorrect=True),
    )

    assert check_run(tmp_path / "source", device, "--fail-if-missing") == 0


def test_exit_0_with_the_flag_when_overwrite_replaced_the_incorrect_file(
    tmp_path: Path, device: Path
) -> None:
    source = tmp_path / "source"
    md5 = fills(source / "bad.bin")
    write(device / "bad.bin")
    on_the_device(device, make_missing("bad.bin", md5, incorrect=True))

    assert check_run(source, device, "--fail-if-missing", "--overwrite") == 0


def test_exit_0_with_the_flag_when_the_file_is_already_on_the_device(
    tmp_path: Path, device: Path
) -> None:
    """It isn't missing. A report that's out of date is the usual reason for this."""
    source = tmp_path / "source"
    md5 = fills(source / "good.bin")
    write(device / "good.bin")
    on_the_device(device, make_missing("good.bin", md5))

    assert check_run(source, device, "--fail-if-missing") == 0


def test_exit_3_beats_exit_5(
    tmp_path: Path,
    device: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DEC-59: the run didn't do all it could, so the list of what's missing isn't final."""
    source = tmp_path / "source"
    md5 = fills(source / "good.bin")
    on_the_device(device, make_missing("good.bin", md5), make_missing("gone.bin", ZERO))
    monkeypatch.setattr(LocalTransport, "upload", forbidden_upload)

    assert check_run(source, device, "--fail-if-missing") == 3

    assert "--fail-if-missing" not in capsys.readouterr().out


def test_exit_4_beats_exit_5(tmp_path: Path, device: Path) -> None:
    assert check_run(tmp_path / "source", device, "--fail-if-missing") == 4


@pytest.mark.parametrize(
    "arguments",
    [
        ["report", "--fail-if-missing", "--report-file", "x"],
        ["scan", "--fail-if-missing"],
        ["--fail-if-missing", "check"],
    ],
    ids=["report", "scan", "before-the-command"],
)
def test_exit_2_the_flag_belongs_to_check(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(arguments)

    assert exit_info.value.code == 2


def test_exit_5_says_what_is_missing_and_why_it_failed(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    md5 = fills(source / "good.bin")
    write(device / "bad.bin")
    on_the_device(
        device,
        make_missing("good.bin", md5),
        make_missing("ps1/gone.bin", ZERO),
        make_missing("skipped.bin", ZERO, required=False),
        make_missing("bad.bin", ONE, incorrect=True),
    )

    assert check_run(source, device, "--fail-if-missing") == 5

    lines = capsys.readouterr().out.splitlines()
    assert "MISSING: ps1/gone.bin" in lines
    assert not any(line.startswith("MISSING:") and "skipped.bin" in line for line in lines)
    assert not any(line.startswith("MISSING:") and "bad.bin" in line for line in lines), (
        "it has its own INCORRECT line"
    )
    assert "INCORRECT: bad.bin is on the device with a wrong MD5, and was kept" in lines
    assert lines[-1] == (
        "Required files still missing or incorrect: 2. Exit code 5, because of --fail-if-missing."
    )


def test_exit_5_says_so_when_the_run_ends_early(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    on_the_device(device, make_missing("gone.bin", ZERO))

    assert check_run(tmp_path / "source", device, "--fail-if-missing") == 5

    lines = capsys.readouterr().out.splitlines()
    assert "MISSING: gone.bin" in lines
    assert lines[-1].startswith("Required files still missing or incorrect: 1.")


def test_exit_5_counts_a_file_listed_in_several_systems_once(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    on_the_device(
        device,
        make_missing("gone.bin", ZERO, system="One"),
        make_missing("gone.bin", ONE, system="Two"),
    )

    assert check_run(tmp_path / "source", device, "--fail-if-missing") == 5

    lines = capsys.readouterr().out.splitlines()
    assert lines.count("MISSING: gone.bin") == 1
    assert lines[-1].startswith("Required files still missing or incorrect: 1.")


def test_exit_5_a_dry_run_that_ends_early_says_would(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    on_the_device(device, make_missing("gone.bin", ZERO))

    assert check_run(tmp_path / "source", device, "--fail-if-missing", "--dry-run") == 5

    assert (
        capsys.readouterr()
        .out.splitlines()[-1]
        .startswith("Required files that would still be missing or incorrect: 1.")
    )


def test_exit_5_a_dry_run_says_would(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    write(source / "junk.bin")
    on_the_device(device, make_missing("gone.bin", ZERO))

    assert check_run(source, device, "--fail-if-missing", "--dry-run") == 5

    assert capsys.readouterr().out.splitlines()[-1] == (
        "Required files that would still be missing or incorrect: 1. "
        "Exit code 5, because of --fail-if-missing."
    )


def test_exit_0_prints_nothing_about_the_flag(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    on_the_device(device, make_missing("gone.bin", ZERO, required=False))

    assert check_run(tmp_path / "source", device, "--fail-if-missing") == 0

    assert "--fail-if-missing" not in capsys.readouterr().out


def test_exit_0_without_the_flag_prints_nothing_about_it(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    on_the_device(device, make_missing("gone.bin", ZERO))

    assert check_run(tmp_path / "source", device) == 0

    output = capsys.readouterr().out
    assert "MISSING: gone.bin" not in output
    assert "--fail-if-missing" not in output


@pytest.mark.parametrize("flags", [(), ("--dry-run",)], ids=["run", "dry-run"])
def test_exit_5_with_json_is_not_ok_and_lists_the_files(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str], flags: tuple[str, ...]
) -> None:
    source = tmp_path / "source"
    write(source / "junk.bin")
    on_the_device(device, make_missing("gone.bin", ZERO))

    assert check_run(source, device, "--json", "--fail-if-missing", *flags) == 5

    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is False
    assert document["errors"] == [], "nothing went wrong: the files just aren't there"
    assert [item["target"] for item in document["still_missing"]] == ["gone.bin"]


def test_exit_5_with_json_when_the_run_ends_early(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    on_the_device(device, make_missing("gone.bin", ZERO))

    assert check_run(tmp_path / "source", device, "--json", "--fail-if-missing") == 5

    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_exit_0_with_json_and_the_flag_is_ok(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    on_the_device(device, make_missing("gone.bin", ZERO, required=False))

    assert check_run(tmp_path / "source", device, "--json", "--fail-if-missing") == 0

    assert json.loads(capsys.readouterr().out)["ok"] is True


# Exit 2: settings that can't work are a configuration error, not a connection error or a bug


needs_permissions = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")


@needs_permissions
def test_exit_2_a_settings_file_it_cannot_read(server: FakeSMBServer, app: Path) -> None:
    file = app / "settings.toml"
    file.chmod(0o000)
    try:
        assert cli.main(["check"], base_dir=app) == 2
    finally:
        file.chmod(0o644)


def test_exit_2_a_settings_file_that_is_a_folder(server: FakeSMBServer, app: Path) -> None:
    (app / "settings.toml").unlink()
    (app / "settings.toml").mkdir()

    assert cli.main(["check"], base_dir=app) == 2


@pytest.mark.parametrize("port", [1, 65535])
def test_exit_0_the_lowest_and_highest_ports_can_work(
    server: FakeSMBServer, tmp_path: Path, port: int
) -> None:
    report(server, block("gone.bin", ZERO))
    url = f"smb://beck-test-server:{port}/bios"

    assert cli.main(["check", "--target", url], base_dir=tmp_path) == 0

    assert server.connections


def test_exit_2_a_url_with_port_0(server: FakeSMBServer, tmp_path: Path) -> None:
    assert cli.main(["check", "--target", "smb://beck-test-server:0/bios"], base_dir=tmp_path) == 2

    assert server.connections == []


# Exit 3: a target that fails is one failed item, or a transport error, and never looks like a bug


@needs_permissions
def test_exit_3_a_locked_folder_on_the_target_fails_one_item_and_the_run_carries_on(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    md5, other = fills(source / "z.bin"), fills(source / "a.bin")
    locked = device / "locked"
    locked.mkdir()
    on_the_device(device, make_missing("locked/a.bin", other), make_missing("z.bin", md5))
    locked.chmod(0o000)
    try:
        assert check_run(source, device, "--json") == 3
    finally:
        locked.chmod(0o755)

    document = json.loads(capsys.readouterr().out)
    statuses = {upload["target"]: upload["status"] for upload in document["uploads"]}
    assert statuses == {"locked/a.bin": "failed", "z.bin": "uploaded"}
    assert (device / "z.bin").exists()


def test_exit_3_a_name_too_long_for_the_target_fails_one_item(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    md5, other = fills(source / "z.bin"), fills(source / "a.bin")
    long_name = f"{'x' * 300}.bin"
    on_the_device(device, make_missing(long_name, other), make_missing("z.bin", md5))

    assert check_run(source, device, "--json") == 3

    document = json.loads(capsys.readouterr().out)
    statuses = {upload["target"]: upload["status"] for upload in document["uploads"]}
    assert statuses == {long_name: "failed", "z.bin": "uploaded"}


@needs_permissions
def test_exit_3_a_target_folder_it_cannot_read(tmp_path: Path, device: Path) -> None:
    device.chmod(0o000)
    try:
        assert check_run(tmp_path / "source", device) == 3
    finally:
        device.chmod(0o755)


def test_exit_3_a_target_folder_that_is_a_symlink_loop(tmp_path: Path) -> None:
    loop = tmp_path / "loop"
    loop.symlink_to(loop)

    assert check_run(tmp_path / "source", loop) == 3


def test_exit_3_a_target_inside_a_symlink_loop_fails_one_item(
    tmp_path: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    md5, other = fills(source / "z.bin"), fills(source / "a.bin")
    (device / "loop").symlink_to(device / "loop")
    on_the_device(device, make_missing("loop/a.bin", other), make_missing("z.bin", md5))

    assert check_run(source, device, "--json") == 3

    document = json.loads(capsys.readouterr().out)
    assert {upload["target"]: upload["status"] for upload in document["uploads"]}["z.bin"] == (
        "uploaded"
    )


# Exit 1, and exit 4 on a full run


def test_exit_1_a_bug_is_reported_as_one(
    tmp_path: Path, device: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    on_the_device(device, make_missing("good.bin", fills(source / "good.bin")))
    monkeypatch.setattr(cli, "execute", forbidden)

    assert check_run(source, device) == 1


def test_exit_4_no_report_on_the_target(tmp_path: Path, device: Path) -> None:
    assert check_run(tmp_path / "source", device) == 4
