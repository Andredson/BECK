"""Full runs through cli.main with a fake SMB server: every stage 03 behavior, end to end.

D1-D14 regression tests that need a whole run live here; the rest are next to each module.
"""

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import pytest
from smb.smb_structs import OperationFailure

from beck import cli
from beck.errors import ConfigError
from tests.conftest import REAL_REPORT, load_report
from tests.factories import md5_of, snapshot
from tests.fakes import FakeSMBServer, install_fake_smb

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
    return cli.main([], base_dir=app)


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

    assert cli.main([]) == 0

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
