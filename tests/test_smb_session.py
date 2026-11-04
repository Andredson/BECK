"""SmbSession (03.3): one connection per run, in-memory reads, closed files (D6, D7, D11, D16)."""

import hashlib
import os
import socket
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import pytest
from smb.smb_structs import OperationFailure

import check_bios
from tests.fakes import FakeSMBConnection, FakeSMBServer, install_fake_smb

CONFIG = """\
smb:
  user: "beck-test-user"
  passwd: "beck-test-password"
  server: "beck-test-server"
  port: 445
"""

# One block in the format of the real reports (tests/fixtures/reports/), with the test file's MD5.
REPORT = """\
  MISSING REQUIRED BIOS: scph5501.bin
    Path: /recalbox/share/bios/ps1/scph5501.bin
    For: libretro/pcsx_rearmed
    Possible MD5 List:
      {md5}
"""


def _forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("this must not be called")


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeSMBServer:
    # Run in an empty folder, so a regression that writes local files can't touch the repository.
    monkeypatch.chdir(tmp_path)
    return install_fake_smb(monkeypatch)


def open_session(port: int = 445) -> "check_bios.SmbSession":
    return check_bios.SmbSession(
        "beck-test-server", port, "beck-test-user", "beck-test-password", "bios"
    )


def only_connection(server: FakeSMBServer) -> FakeSMBConnection:
    assert len(server.connections) == 1
    return server.connections[0]


def test_full_run_opens_one_connection_and_closes_it(
    server: FakeSMBServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = os.urandom(1024)
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest().upper()
    server.files[("bios", "missing_bios_report.txt")] = REPORT.format(md5=md5).encode()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "bios").mkdir()
    (tmp_path / "bios" / "my-ps1-bios.bin").write_bytes(data)
    monkeypatch.chdir(tmp_path)
    # Until step 03.11, validate_bios looks for the bios folder next to the script.
    monkeypatch.setattr(check_bios, "__file__", str(tmp_path / "check_bios.py"))

    check_bios.main()

    conn = only_connection(server)
    assert conn.calls.count("connect") == 1
    assert conn.calls.count("listShares") == 1
    assert conn.calls[-1] == "close"
    assert (conn.username, conn.password, conn.remote_name) == (
        "beck-test-user",
        "beck-test-password",
        "beck-test-server",
    )
    assert server.files[("bios", "ps1/scph5501.bin")] == data


def test_reading_the_report_creates_and_changes_no_local_file(
    server: FakeSMBServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.files[("bios", "missing_bios_report.txt")] = b"MISSING REQUIRED BIOS\n"
    (tmp_path / "test.txt").write_text("the user's own notes", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for name in ("NamedTemporaryFile", "TemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, _forbidden)

    with open_session() as session:
        text = session.read_text("missing_bios_report.txt")

    assert text == "MISSING REQUIRED BIOS\n"
    # The old code wrote the report to ./test.txt, then deleted it (D6).
    assert {p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()} == {
        "test.txt": "the user's own notes"
    }


def test_read_text_replaces_bytes_that_are_not_utf8(server: FakeSMBServer) -> None:
    server.files[("bios", "report.txt")] = b"caf\xe9\n"

    with open_session() as session:
        assert session.read_text("report.txt") == "caf�\n"


def test_upload_closes_the_local_file_before_returning(
    server: FakeSMBServer, tmp_path: Path
) -> None:
    local = tmp_path / "scph5501.bin"
    local.write_bytes(b"\x00\x01\x02")

    with open_session() as session:
        session.upload(local, "scph5501.bin")
        stored = only_connection(server).stored_files

    assert len(stored) == 1
    # Checked directly: CI doesn't run on Windows, where an open file can't be deleted (D7, DEC-49).
    assert stored[0].closed
    assert server.files[("bios", "scph5501.bin")] == b"\x00\x01\x02"


@pytest.mark.parametrize(("port", "direct_tcp"), [(445, True), (139, False)])
def test_direct_tcp_is_used_on_port_445(server: FakeSMBServer, port: int, direct_tcp: bool) -> None:
    with open_session(port):
        pass

    assert only_connection(server).is_direct_tcp is direct_tcp


def test_client_name_is_the_host_name_without_a_dns_lookup(
    server: FakeSMBServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket, "gethostname", lambda: "beck-test-host")
    monkeypatch.setattr(socket, "gethostbyname", _forbidden)

    with open_session():
        pass

    assert only_connection(server).my_name == "beck-test-host"


def test_client_name_falls_back_to_beck(
    server: FakeSMBServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_hostname() -> str:
        raise OSError("no host name")

    monkeypatch.setattr(socket, "gethostname", broken_hostname)

    with open_session():
        pass

    assert only_connection(server).my_name == "BECK"


def test_an_error_inside_the_session_still_closes_it(server: FakeSMBServer) -> None:
    with pytest.raises(RuntimeError), open_session():
        raise RuntimeError("boom")

    assert only_connection(server).closed


def _connect_fails(server: FakeSMBServer) -> None:
    server.failures["connect"] = OSError("No route to host")


def _login_refused(server: FakeSMBServer) -> None:
    server.login_succeeds = False


def _listing_shares_fails(server: FakeSMBServer) -> None:
    server.failures["listShares"] = OperationFailure("access denied", [])


def _share_missing(server: FakeSMBServer) -> None:
    server.shares = ("share",)


@pytest.mark.parametrize(
    ("break_server", "message"),
    [
        (_connect_fails, "Error connecting to SMB server beck-test-server: No route to host"),
        (_login_refused, "SMB server beck-test-server refused the login"),
        (_listing_shares_fails, "Error listing the shares of SMB server beck-test-server"),
        (_share_missing, "The share bios doesn't exist on SMB server beck-test-server"),
    ],
)
def test_opening_errors_raise_beck_error_and_close_the_connection(
    server: FakeSMBServer, break_server: Callable[[FakeSMBServer], None], message: str
) -> None:
    break_server(server)

    with pytest.raises(check_bios.BeckError, match=message), open_session():
        pass

    assert only_connection(server).closed


def test_operation_errors_raise_beck_error(server: FakeSMBServer, tmp_path: Path) -> None:
    server.dirs.add(("bios", "ps1"))

    with open_session() as session:
        with pytest.raises(
            check_bios.BeckError, match=r"Error reading missing\.txt from share bios"
        ):
            session.read_text("missing.txt")
        with pytest.raises(
            check_bios.BeckError, match=r"Error uploading .+ to x\.bin on share bios"
        ):
            session.upload(tmp_path / "does-not-exist.bin", "x.bin")
        with pytest.raises(check_bios.BeckError, match="Error listing folder 'n64' on share bios"):
            session.list_dirs("n64")
        with pytest.raises(check_bios.BeckError, match="Error creating folder ps1/ on share bios"):
            session.make_dir("ps1/")


def test_list_dirs_returns_only_sub_folders(server: FakeSMBServer) -> None:
    server.dirs.update({("bios", "ps1"), ("bios", "dc"), ("bios", "ps1/nested")})
    server.files[("bios", "missing_bios_report.txt")] = b""

    with open_session() as session:
        assert sorted(session.list_dirs("")) == ["dc", "ps1"]
        assert session.list_dirs("ps1") == ["nested"]


def test_make_dir_creates_the_folder(server: FakeSMBServer) -> None:
    with open_session() as session:
        session.make_dir("ps1/")

    assert ("bios", "ps1") in server.dirs


def test_main_prints_the_error_and_exits_1(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _connect_fails(server)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exit_info:
        check_bios.main()

    assert exit_info.value.code == 1
    assert "Error connecting to SMB server beck-test-server" in capsys.readouterr().out
    assert only_connection(server).closed


def test_ensure_dir_creates_each_level_once_in_order(server: FakeSMBServer) -> None:
    with open_session() as session:
        session.ensure_dir("a/b/c/")

    assert {("bios", "a"), ("bios", "a/b"), ("bios", "a/b/c")} == server.dirs
    assert only_connection(server).calls.count("createDirectory") == 3


def test_ensure_dir_checks_the_parent_of_each_level(server: FakeSMBServer) -> None:
    # A folder named "b" at the share root must not count as "a/b".
    server.dirs.update({("bios", "a"), ("bios", "b")})

    with open_session() as session:
        session.ensure_dir("a/b/")

    assert ("bios", "a/b") in server.dirs


def test_ensure_dir_keeps_existing_levels(server: FakeSMBServer) -> None:
    server.dirs.update({("bios", "amiga")})

    with open_session() as session:
        session.ensure_dir("amiga/bios/")

    assert only_connection(server).calls.count("createDirectory") == 1
    assert ("bios", "amiga/bios") in server.dirs


def test_ensure_dir_creates_nothing_when_everything_exists(server: FakeSMBServer) -> None:
    server.dirs.update({("bios", "amiga"), ("bios", "amiga/bios")})

    with open_session() as session:
        session.ensure_dir("amiga/bios/")

    assert only_connection(server).calls.count("createDirectory") == 0


def test_ensure_dir_at_the_share_root_does_nothing(server: FakeSMBServer) -> None:
    with open_session() as session:
        session.ensure_dir("")

    calls = only_connection(server).calls
    assert "createDirectory" not in calls
    assert "listPath" not in calls


def test_ensure_dir_reports_listing_errors_as_listing(server: FakeSMBServer) -> None:
    server.failures["listPath"] = OperationFailure("access denied", [])

    with (
        pytest.raises(check_bios.BeckError, match="Error listing folder '' on share bios"),
        open_session() as session,
    ):
        session.ensure_dir("a/")


def test_ensure_dir_reports_creation_errors_as_creating(server: FakeSMBServer) -> None:
    server.failures["createDirectory"] = OperationFailure("access denied", [])

    with (
        pytest.raises(check_bios.BeckError, match="Error creating folder a on share bios"),
        open_session() as session,
    ):
        session.ensure_dir("a/")


@pytest.mark.parametrize("existing", [(), ("amiga",), ("amiga", "amiga/bios")])
def test_ensure_dir_nested_target_uploads_in_a_full_run(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: tuple[str, ...],
) -> None:
    server.dirs.update(("bios", folder) for folder in existing)
    data = os.urandom(64)
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    server.files[("bios", "missing_bios_report.txt")] = (
        "  MISSING REQUIRED BIOS: kick39106.A1200\n"
        "    Path: /recalbox/share/bios/amiga/bios/kick39106.A1200\n"
        f"    Possible MD5 List:\n      {md5}\n"
    ).encode()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "bios").mkdir()
    (tmp_path / "bios" / "my-copy.rom").write_bytes(data)
    monkeypatch.setattr(check_bios, "__file__", str(tmp_path / "check_bios.py"))

    check_bios.main()

    assert server.files[("bios", "amiga/bios/kick39106.A1200")] == data
