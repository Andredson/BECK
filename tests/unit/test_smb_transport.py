# SPDX-License-Identifier: GPL-3.0-only
"""SmbTransport: from the stage 03 SmbSession tests (D4, D6, D7, D11, D16), with fake SMB server."""

import os
import socket
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

import pytest
from smb.base import SMBTimeout
from smb.smb_structs import OperationFailure

from beck.errors import TransportError
from beck.transports.base import Transport
from beck.transports.smb import SmbTransport
from tests.fakes import FakeSMBConnection, FakeSMBServer, install_fake_smb

CREDENTIAL = "beck-test-password"


def _forbidden(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("this must not be called")


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeSMBServer:
    # Run in an empty folder, so a regression that writes local files can't touch the repository.
    monkeypatch.chdir(tmp_path)
    return install_fake_smb(monkeypatch)


def transport(port: int = 445, timeout: float = 30) -> Transport:
    # Annotated as Transport, so mypy checks that the class follows the Protocol.
    return SmbTransport("beck-test-server", port, "bios", "beck-test-user", CREDENTIAL, timeout)


def only_connection(server: FakeSMBServer) -> FakeSMBConnection:
    assert len(server.connections) == 1
    return server.connections[0]


def local_file(tmp_path: Path, data: bytes = b"\x00\x01\x02") -> Path:
    file = tmp_path / "local.bin"
    file.write_bytes(data)
    return file


def test_one_connection_for_many_operations_and_it_closes(
    server: FakeSMBServer, tmp_path: Path
) -> None:
    server.files[("bios", "report.txt")] = b"report"

    with transport() as opened:
        opened.read_bytes(PurePosixPath("report.txt"))
        opened.makedirs(PurePosixPath("ps1"))
        opened.upload(local_file(tmp_path), PurePosixPath("ps1/a.bin"))

    conn = only_connection(server)
    assert conn.calls.count("connect") == 1
    assert conn.calls.count("listShares") == 1
    assert conn.calls[-1] == "close"
    assert (conn.username, conn.password, conn.remote_name) == (
        "beck-test-user",
        CREDENTIAL,
        "beck-test-server",
    )


@pytest.mark.parametrize(("port", "direct_tcp"), [(445, True), (139, False), (4445, False)])
def test_direct_tcp_is_used_on_port_445(server: FakeSMBServer, port: int, direct_tcp: bool) -> None:
    with transport(port):
        pass

    assert only_connection(server).is_direct_tcp is direct_tcp


def test_the_timeout_reaches_every_call(server: FakeSMBServer, tmp_path: Path) -> None:
    server.files[("bios", "a.txt")] = b"a"

    with transport(timeout=7) as opened:
        opened.read_bytes(PurePosixPath("a.txt"))
        opened.exists(PurePosixPath("a.txt"))
        opened.size(PurePosixPath("a.txt"))
        opened.makedirs(PurePosixPath("ps1"))
        opened.upload(local_file(tmp_path), PurePosixPath("ps1/a.bin"))

    conn = only_connection(server)
    assert len(conn.timeouts) >= 7
    assert set(conn.timeouts) == {7}


def test_client_name_is_the_host_name_without_a_dns_lookup(
    server: FakeSMBServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket, "gethostname", lambda: "beck-test-host")
    monkeypatch.setattr(socket, "gethostbyname", _forbidden)

    with transport():
        pass

    assert only_connection(server).my_name == "beck-test-host"


def test_client_name_falls_back_to_beck(
    server: FakeSMBServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_hostname() -> str:
        raise OSError("no host name")

    monkeypatch.setattr(socket, "gethostname", broken_hostname)

    with transport():
        pass

    assert only_connection(server).my_name == "BECK"


def test_an_error_inside_the_block_still_closes_it(server: FakeSMBServer) -> None:
    with pytest.raises(RuntimeError), transport():
        raise RuntimeError("boom")

    assert only_connection(server).closed


def _unreachable(server: FakeSMBServer) -> None:
    server.failures["connect"] = OSError("No route to host")


def _connect_times_out(server: FakeSMBServer) -> None:
    server.failures["connect"] = TimeoutError()


def _login_refused(server: FakeSMBServer) -> None:
    server.login_succeeds = False


def _listing_shares_fails(server: FakeSMBServer) -> None:
    server.failures["listShares"] = OperationFailure("access denied", [])


def _share_missing(server: FakeSMBServer) -> None:
    server.shares = ("share",)


@pytest.mark.parametrize(
    ("break_server", "message"),
    [
        (_unreachable, "Error connecting to SMB server beck-test-server: No route to host"),
        (_connect_times_out, "Timed out connecting to SMB server beck-test-server"),
        (_login_refused, "SMB server beck-test-server refused the login"),
        (_listing_shares_fails, "Error listing the shares of SMB server beck-test-server"),
        (_share_missing, "The share bios doesn't exist on SMB server beck-test-server"),
    ],
)
def test_opening_errors_are_transport_errors_and_close_the_connection(
    server: FakeSMBServer, break_server: Callable[[FakeSMBServer], None], message: str
) -> None:
    break_server(server)

    with pytest.raises(TransportError, match=message) as error, transport():
        pass

    assert only_connection(server).closed
    assert CREDENTIAL not in str(error.value)


def test_read_bytes_is_in_memory_and_keeps_the_exact_bytes(
    server: FakeSMBServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.files[("bios", "report.txt")] = b"caf\xe9\r\n"
    for name in ("NamedTemporaryFile", "TemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, _forbidden)

    with transport() as opened:
        assert opened.read_bytes(PurePosixPath("report.txt")) == b"caf\xe9\r\n"

    assert list(tmp_path.iterdir()) == []  # the old code wrote ./test.txt (D6)


def test_upload_returns_the_size_and_closes_the_local_file(
    server: FakeSMBServer, tmp_path: Path
) -> None:
    data = os.urandom(5000)
    local = local_file(tmp_path, data)

    with transport() as opened:
        assert opened.upload(local, PurePosixPath("a.bin")) == 5000
        stored = only_connection(server).stored_files

    assert stored[0].closed  # checked directly: CI doesn't run on Windows (D7, DEC-49)
    assert str(stored[0].name) == str(local)  # read from the file, not loaded into memory
    assert server.files[("bios", "a.bin")] == data
    assert local.read_bytes() == data


def test_a_file_at_the_share_root_uses_its_bare_name(server: FakeSMBServer, tmp_path: Path) -> None:
    with transport() as opened:
        opened.upload(local_file(tmp_path), PurePosixPath("a.bin"))

    assert ("bios", "a.bin") in server.files


def test_size(server: FakeSMBServer) -> None:
    server.files[("bios", "ps1/a.bin")] = b"12345"
    server.dirs.add(("bios", "ps1"))

    with transport() as opened:
        assert opened.size(PurePosixPath("ps1/a.bin")) == 5


def test_exists_walks_down_each_level(server: FakeSMBServer) -> None:
    server.dirs.update({("bios", "a"), ("bios", "a/b")})
    server.files[("bios", "a/b/file.bin")] = b""
    server.files[("bios", "top.bin")] = b""

    with transport() as opened:
        assert opened.exists(PurePosixPath("."))
        assert opened.exists(PurePosixPath("top.bin"))
        assert opened.exists(PurePosixPath("a/b"))
        assert opened.exists(PurePosixPath("a/b/file.bin"))
        assert not opened.exists(PurePosixPath("missing.bin"))
        assert not opened.exists(PurePosixPath("a/missing.bin"))
        assert not opened.exists(PurePosixPath("no/such/folder/file.bin"))


def test_exists_ignores_case_because_samba_does(server: FakeSMBServer) -> None:
    # Otherwise, a file differing only in case reads as absent, and the upload overwrites it.
    server.dirs.add(("bios", "Mupen64plus"))
    server.files[("bios", "Mupen64plus/IPL.n64")] = b""

    with transport() as opened:
        assert opened.exists(PurePosixPath("mupen64PLUS/ipl.N64"))


def test_makedirs_ignores_case_because_samba_does(server: FakeSMBServer) -> None:
    server.dirs.add(("bios", "Mupen64plus"))

    with transport() as opened:
        opened.makedirs(PurePosixPath("mupen64plus"))

    assert only_connection(server).calls.count("createDirectory") == 0


def test_a_name_at_another_level_does_not_count_as_existing(server: FakeSMBServer) -> None:
    server.dirs.update({("bios", "a"), ("bios", "b")})

    with transport() as opened:
        assert not opened.exists(PurePosixPath("a/b"))


def test_exists_treats_a_failed_listing_as_an_error_not_as_missing(server: FakeSMBServer) -> None:
    with transport() as opened:
        server.failures["listPath"] = OperationFailure("access denied", [])
        with pytest.raises(TransportError, match="access denied"):
            opened.exists(PurePosixPath("a.bin"))


@pytest.mark.parametrize(
    ("method", "action", "message"),
    [
        (
            "retrieveFile",
            lambda t, _: t.read_bytes(PurePosixPath("a.txt")),
            r"reading a\.txt from share bios",
        ),
        (
            "getAttributes",
            lambda t, _: t.size(PurePosixPath("a.txt")),
            r"getting the size of a\.txt on share bios",
        ),
        (
            "listPath",
            lambda t, _: t.makedirs(PurePosixPath("a")),
            "listing folder '' on share bios",
        ),
        (
            "createDirectory",
            lambda t, _: t.makedirs(PurePosixPath("a")),
            "creating folder a on share bios",
        ),
        (
            "storeFile",
            lambda t, local: t.upload(local, PurePosixPath("a.bin")),
            r"uploading .+ to a\.bin on share bios",
        ),
    ],
)
@pytest.mark.parametrize(
    ("error", "start", "end"),
    [
        (OperationFailure("short reason", []), "Error", ": short reason"),
        (SMBTimeout(), "Timed out", ""),
        (TimeoutError(), "Timed out", ""),
        (ConnectionResetError("reset by peer"), "Error", ": reset by peer"),
    ],
    ids=["failure", "smb-timeout", "socket-timeout", "connection-lost"],
)
def test_operation_errors_say_what_failed(
    server: FakeSMBServer,
    tmp_path: Path,
    method: str,
    action: Callable[[Transport, Path], object],
    message: str,
    error: Exception,
    start: str,
    end: str,
) -> None:
    local = local_file(tmp_path)

    with transport() as opened:
        server.failures[method] = error
        with pytest.raises(TransportError, match=f"^{start} {message}.*{end}$") as raised:
            action(opened, local)

    assert CREDENTIAL not in str(raised.value)
    assert only_connection(server).closed


def test_a_failure_message_leaves_out_the_smb_message_dump(server: FakeSMBServer) -> None:
    server.failures["retrieveFile"] = OperationFailure("short reason", ["raw SMB message dump"])

    with transport() as opened, pytest.raises(TransportError) as raised:
        opened.read_bytes(PurePosixPath("a.txt"))

    assert "raw SMB" not in str(raised.value)


def test_upload_of_a_missing_local_file_is_a_transport_error(
    server: FakeSMBServer, tmp_path: Path
) -> None:
    with transport() as opened, pytest.raises(TransportError, match="Error uploading"):
        opened.upload(tmp_path / "no-such-file", PurePosixPath("a.bin"))


def test_makedirs_creates_each_level_once_in_order(server: FakeSMBServer) -> None:
    with transport() as opened:
        opened.makedirs(PurePosixPath("a/b/c"))

    assert server.dirs == {("bios", "a"), ("bios", "a/b"), ("bios", "a/b/c")}
    assert only_connection(server).calls.count("createDirectory") == 3


def test_makedirs_checks_the_parent_of_each_level(server: FakeSMBServer) -> None:
    # A folder named "b" at the share root must not count as "a/b".
    server.dirs.update({("bios", "a"), ("bios", "b")})

    with transport() as opened:
        opened.makedirs(PurePosixPath("a/b"))

    assert ("bios", "a/b") in server.dirs


def test_makedirs_keeps_existing_levels(server: FakeSMBServer) -> None:
    server.dirs.add(("bios", "amiga"))

    with transport() as opened:
        opened.makedirs(PurePosixPath("amiga/bios"))

    assert only_connection(server).calls.count("createDirectory") == 1
    assert ("bios", "amiga/bios") in server.dirs


def test_makedirs_creates_nothing_when_everything_exists(server: FakeSMBServer) -> None:
    server.dirs.update({("bios", "amiga"), ("bios", "amiga/bios")})

    with transport() as opened:
        opened.makedirs(PurePosixPath("amiga/bios"))

    assert only_connection(server).calls.count("createDirectory") == 0


def test_makedirs_at_the_share_root_does_nothing(server: FakeSMBServer) -> None:
    with transport() as opened:
        opened.makedirs(PurePosixPath("."))

    calls = only_connection(server).calls
    assert "createDirectory" not in calls
    assert "listPath" not in calls


def test_makedirs_with_a_file_in_the_way_is_a_transport_error(server: FakeSMBServer) -> None:
    server.files[("bios", "a")] = b"a file"

    with transport() as opened, pytest.raises(TransportError, match="creating folder a"):
        opened.makedirs(PurePosixPath("a/b"))


def test_a_root_folder_applies_to_every_operation(server: FakeSMBServer, tmp_path: Path) -> None:
    # smb://recalbox/share/bios: the BIOS folder is a folder inside the share.
    server.dirs.update({("bios", "share"), ("bios", "share/inner")})
    server.files[("bios", "share/inner/report.txt")] = b"report"
    transport = SmbTransport(
        "beck-test-server", 445, "bios", "", "", root=PurePosixPath("share/inner")
    )

    with transport as opened:
        assert opened.read_bytes(PurePosixPath("report.txt")) == b"report"
        assert opened.size(PurePosixPath("report.txt")) == 6
        assert opened.exists(PurePosixPath("report.txt"))
        assert not opened.exists(PurePosixPath("share"))
        opened.makedirs(PurePosixPath("ps1"))
        opened.upload(local_file(tmp_path, b"data"), PurePosixPath("ps1/a.bin"))

    assert server.files[("bios", "share/inner/ps1/a.bin")] == b"data"
    assert ("bios", "ps1") not in server.dirs


def test_makedirs_creates_a_missing_root_folder(server: FakeSMBServer) -> None:
    with SmbTransport("beck-test-server", 445, "bios", "", "", root=PurePosixPath("a/b")) as opened:
        opened.makedirs(PurePosixPath("c"))

    assert ("bios", "a/b/c") in server.dirs


def test_url_has_the_host_port_share_and_root_but_no_credentials() -> None:
    plain = SmbTransport("beck-test-server", 445, "bios", "beck-test-user", "beck-test-password")
    nested = SmbTransport(
        "beck-test-server",
        4450,
        "bios",
        "beck-test-user",
        "beck-test-password",
        root=PurePosixPath("a/b"),
    )

    assert plain.url() == "smb://beck-test-server:445/bios"
    assert nested.url() == "smb://beck-test-server:4450/bios/a/b"


def test_describe_shows_the_root_folder(server: FakeSMBServer) -> None:
    transport = SmbTransport("beck-test-server", 445, "bios", "", "", root=PurePosixPath("a/b"))

    assert transport.describe() == "SMB share bios/a/b on beck-test-server:445"


def test_describe_never_includes_the_credentials(server: FakeSMBServer) -> None:
    with transport() as opened:
        description = opened.describe()

    assert description == "SMB share bios on beck-test-server:445"
