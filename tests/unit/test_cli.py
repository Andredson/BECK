"""Full runs through cli.main with a fake SMB server: every stage 03 behavior, end to end.

D1-D14 regression tests that need a whole run live here; the rest are next to each module.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import pytest
from smb.smb_structs import OperationFailure

import beck
from beck import cli
from beck.errors import ConfigError
from tests.conftest import REAL_REPORT, load_report
from tests.factories import md5_of, snapshot
from tests.fakes import FakeSMBConnection, FakeSMBServer, install_fake_smb

GUEST = 'smb: {user: "", passwd: "", server: "beck-test-server", port: 445}\n'
ACCOUNT = """\
smb:
  user: "beck-test-user"
  passwd: "beck-test-password"
  server: "beck-test-server"
  port: 445
"""


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


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeSMBServer:
    return install_fake_smb(monkeypatch)


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder with a config and an empty bios folder, which is also the current directory."""
    folder = tmp_path / "app"
    write(folder / "config" / "config.yml", GUEST.encode())
    (folder / "bios").mkdir()
    monkeypatch.chdir(folder)
    return folder


def report(server: FakeSMBServer, text: str | bytes) -> None:
    content = text.encode() if isinstance(text, str) else text
    server.files[("bios", "missing_bios_report.txt")] = content


def run(app: Path) -> int:
    return cli.main(["check"], base_dir=app)


# Settings


def test_missing_config_tells_the_user_to_copy_the_example(tmp_path: Path) -> None:
    missing = tmp_path / "config" / "config.yml"

    with pytest.raises(ConfigError) as error:
        cli.load_legacy_config(missing)

    assert f"{missing} not found" in str(error.value)
    assert "Copy config/config.example.yml to config/config.yml and fill it in" in str(error.value)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "other: 1\n",
        "- a list\n",
        "smb: 1\n",
        'smb: {user: "", passwd: "", server: "x"}\n',
        'smb: {user: "", passwd: "", port: 445}\n',
    ],
)
def test_config_without_the_needed_settings_is_a_clear_error(tmp_path: Path, content: str) -> None:
    file = tmp_path / "config.yml"
    file.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError, match="needs an smb section"):
        cli.load_legacy_config(file)


def test_malformed_yaml_is_a_clear_error(tmp_path: Path) -> None:
    file = tmp_path / "config.yml"
    file.write_text("smb: {unclosed\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="isn't valid YAML"):
        cli.load_legacy_config(file)


def test_a_config_error_prints_and_returns_2(
    tmp_path: Path, server: FakeSMBServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path) == 2
    assert "Copy config/config.example.yml" in capsys.readouterr().out
    assert server.connections == []


def test_the_settings_reach_the_connection(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(app / "config" / "config.yml", ACCOUNT.encode())
    report(server, "MISSING BIOS REPORT\n")

    assert run(app) == 0

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


def test_no_command_works_as_check_with_a_hint_on_stderr(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = write(app / "bios" / "copy.bin")
    report(server, block("a.bin", md5_of(data)))

    assert cli.main([], base_dir=app) == 0

    assert server.files[("bios", "a.bin")] == data
    captured = capsys.readouterr()
    assert "Hint: use 'beck check'" in captured.err
    assert "Hint" not in captured.out


def test_beck_check_has_no_hint(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report(server, "MISSING BIOS REPORT\n")

    assert run(app) == 0

    assert capsys.readouterr().err == ""


def test_scan_still_to_come_says_so_and_exits_2(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["scan"], base_dir=app) == 2

    assert "beck scan isn't available yet" in capsys.readouterr().out
    assert server.connections == []


@pytest.mark.parametrize(
    "arguments",
    [["check", "--no-color"], ["--no-color", "check"], ["--no-color"]],
    ids=["after", "before", "no-command"],
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


def test_target_url_is_used_instead_of_the_config(
    server: FakeSMBServer, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(app / "config" / "config.yml", ACCOUNT.encode())
    data = write(app / "bios" / "copy.bin")
    report(server, block("a.bin", md5_of(data), folder="ps1/"))

    assert cli.main(["check", "--target", "smb://other-host:4450/bios"], base_dir=app) == 0

    conn = server.connections[0]
    assert conn.remote_name == "other-host"
    assert server.files[("bios", "ps1/a.bin")] == data
    assert "beck-test-password" not in "".join(capsys.readouterr())


def test_the_password_in_the_config_never_goes_to_a_target_url(
    server: FakeSMBServer, app: Path
) -> None:
    # Sending it to whatever host the flag names would leak it.
    write(app / "config" / "config.yml", ACCOUNT.encode())
    report(server, "MISSING BIOS REPORT\n")

    assert cli.main(["check", "--target", "smb://beck-test-user@evil/bios"], base_dir=app) == 0

    assert server.connections[0].username == "beck-test-user"
    assert server.connections[0].password == ""


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

    assert "Copy config/config.example.yml" in capsys.readouterr().out


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


def test_report_lists_a_repeated_target_once_and_required_wins(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    optional = block("x.pce", "0" * 32).replace("REQUIRED", "OPTIONAL")
    file = local_report(tmp_path, optional + block("x.pce", "1" * 32))

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
    assert "INCORRECT: two/b.bin is on the device with a wrong MD5" in output
    assert "No missing bios" not in output
    assert "There are" not in output


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
        cli.main(["--no-such-flag"])

    assert exit_info.value.code == 2
    assert "unrecognized arguments: --no-such-flag" in capsys.readouterr().err
    assert server.connections == []


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (None, "Copy config/config.example.yml"),
        ("smb: {unclosed\n", "isn't valid YAML"),
        ("other: 1\n", "needs an smb section"),
    ],
    ids=["missing", "malformed", "no-smb-section"],
)
def test_exit_2_config_error(
    server: FakeSMBServer,
    app: Path,
    capsys: pytest.CaptureFixture[str],
    config: str | None,
    message: str,
) -> None:
    if config is None:
        (app / "config" / "config.yml").unlink()
    else:
        write(app / "config" / "config.yml", config.encode())

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
    assert "Copy config/config.example.yml" in result.stdout
    assert result.stderr == ""


def test_a_usage_error_reaches_the_operating_system(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "beck", "--no-such-flag"],
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
    app: Path,
    capsys: pytest.CaptureFixture[str],
    break_server: Callable[[FakeSMBServer], None],
    message: str,
) -> None:
    write(app / "config" / "config.yml", ACCOUNT.encode())
    break_server(server)

    assert run(app) == 3

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

    def a_bug(_folder: Path) -> NoReturn:
        raise RuntimeError("a bug in BECK")

    monkeypatch.setattr(cli, "scan", a_bug)

    assert run(app) == 1

    captured = capsys.readouterr()
    assert "Unexpected error" in captured.err
    assert "RuntimeError: a bug in BECK" in captured.err
    assert "a bug in BECK" not in captured.out
    assert server.connections[0].closed
