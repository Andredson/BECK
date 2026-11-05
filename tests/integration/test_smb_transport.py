"""BECK against a real Samba server: what the fake SMB server can only assume (DEC-33).

Run with BECK_TEST_SMB_HOST=127.0.0.1 BECK_TEST_SMB_PORT=4450 uv run pytest -m integration
"""

import os
import socket
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from beck import cli
from beck.errors import ConfigError, ReportParseError, TransportError
from beck.executor import execute
from beck.hashing import scan
from beck.matcher import plan
from beck.transports.smb import SmbTransport
from tests.conftest import load_report
from tests.factories import make_bios_file, make_missing, make_report_text, snapshot
from tests.integration.conftest import ACCOUNT_CREDENTIAL, SEEDED_FILE, SEEDED_TEXT, Samba

pytestmark = pytest.mark.integration

BAD_CREDENTIAL = "beck-test-wrong"
PutReport = Callable[[str | bytes], None]


def local_file(tmp_path: Path, data: bytes | None = None, name: str = "local.bin") -> Path:
    file = tmp_path / name
    file.write_bytes(os.urandom(4096) if data is None else data)
    return file


# Logging in


def test_guest_can_read_a_seeded_file(samba: Samba) -> None:
    with samba.guest("readonly") as transport:
        assert transport.read_bytes(SEEDED_FILE) == SEEDED_TEXT
        assert transport.size(SEEDED_FILE) == len(SEEDED_TEXT)
        assert transport.exists(SEEDED_FILE)
        assert not transport.exists(PurePosixPath("no-such-file"))


def test_guest_can_read_a_report_with_its_exact_bytes(samba: Samba, put_report: PutReport) -> None:
    report = load_report("recalbox-10.1.1/default-install").encode()
    put_report(report)

    with samba.guest() as transport:
        assert transport.read_bytes(PurePosixPath("missing_bios_report.txt")) == report


def test_password_login_can_write_to_its_share(
    samba: Samba, private_file: PurePosixPath, tmp_path: Path
) -> None:
    data = os.urandom(512)

    with samba.account("private", ACCOUNT_CREDENTIAL) as transport:
        assert transport.upload(local_file(tmp_path, data), private_file) == 512
        assert transport.read_bytes(private_file) == data


def test_guest_cant_use_the_private_share(samba: Samba) -> None:
    with samba.guest("private") as transport, pytest.raises(TransportError, match="private"):
        transport.read_bytes(PurePosixPath("anything"))


def test_wrong_password_is_a_readable_transport_error(samba: Samba) -> None:
    with pytest.raises(TransportError) as error, samba.account("private", BAD_CREDENTIAL):
        pass

    assert error.value.exit_code == 3
    assert f"SMB server {samba.host} refused the login" in str(error.value)
    assert BAD_CREDENTIAL not in str(error.value)


def test_unknown_user_is_a_guest_as_on_recalbox(samba: Samba) -> None:
    # `map to guest = bad user`, the same setting as a real Recalbox.
    with SmbTransport(samba.host, samba.port, "readonly", "beck-test-nobody", "x") as transport:
        assert transport.read_bytes(SEEDED_FILE) == SEEDED_TEXT


def test_unknown_share_is_a_readable_error(samba: Samba) -> None:
    with (
        pytest.raises(TransportError, match="The share no-such doesn't exist"),
        samba.guest("no-such"),
    ):
        pass


def test_unreachable_port_is_a_readable_error(samba: Samba) -> None:
    with (
        pytest.raises(TransportError, match="Error connecting to SMB server"),
        SmbTransport(samba.host, 1, "bios", "", "", timeout=5),
    ):
        pass


# Files and folders


def test_nested_makedirs_upload_and_size(
    samba: Samba, folder: PurePosixPath, tmp_path: Path
) -> None:
    data = os.urandom(4096)
    target = folder / "a b" / "(c)" / "file (1).bin"

    with samba.guest() as transport:
        assert not transport.exists(folder)
        transport.makedirs(target.parent)
        transport.makedirs(target.parent)  # an existing folder is fine
        written = transport.upload(local_file(tmp_path, data), target)

        assert written == len(data)
        assert transport.size(target) == len(data)
        assert transport.exists(target)
        assert transport.read_bytes(target) == data


def test_a_file_larger_than_smb_chunks(samba: Samba, folder: PurePosixPath, tmp_path: Path) -> None:
    data = os.urandom(3 * 1024 * 1024)
    target = folder / "big.bin"

    with samba.guest() as transport:
        transport.makedirs(folder)
        assert transport.upload(local_file(tmp_path, data), target) == len(data)
        assert transport.read_bytes(target) == data


def test_upload_replaces_an_existing_file_completely(
    samba: Samba, folder: PurePosixPath, tmp_path: Path
) -> None:
    target = folder / "a.bin"

    with samba.guest() as transport:
        transport.makedirs(folder)
        transport.upload(local_file(tmp_path, os.urandom(4096)), target)
        transport.upload(local_file(tmp_path, b"short"), target)

        assert transport.read_bytes(target) == b"short"


def test_upload_to_a_missing_folder_is_a_readable_error(
    samba: Samba, folder: PurePosixPath, tmp_path: Path
) -> None:
    with samba.guest() as transport, pytest.raises(TransportError, match="Error uploading"):
        transport.upload(local_file(tmp_path), folder / "no-folder" / "a.bin")


def test_a_file_in_the_way_of_a_folder_is_a_readable_error(
    samba: Samba, folder: PurePosixPath, tmp_path: Path
) -> None:
    blocker = folder / "blocker"

    with samba.guest() as transport:
        transport.makedirs(folder)
        transport.upload(local_file(tmp_path), blocker)
        with pytest.raises(TransportError, match="Error creating folder"):
            transport.makedirs(blocker / "under-a-file")


def test_read_only_share_errors_are_recorded_and_the_run_continues(
    samba: Samba, tmp_path: Path
) -> None:
    first, second = make_bios_file(tmp_path, "a.bin"), make_bios_file(tmp_path, "b.bin")
    report = [make_missing("x.bin", first.md5), make_missing("y.bin", second.md5)]
    before = snapshot(tmp_path)

    with samba.guest("readonly") as transport:
        result = execute(plan(report, scan(tmp_path)), transport, dry_run=False)

        assert not transport.exists(PurePosixPath("x.bin"))

    assert [error.item for error in result.errors] == ["x.bin", "y.bin"]  # it tried both
    assert result.completed == ()
    assert snapshot(tmp_path) == before


def test_direct_tcp_is_chosen_for_port_445_and_works(
    samba: Samba, folder: PurePosixPath, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BECK is told port 445 and chooses direct TCP by itself. Only the TCP port number is
    # redirected, because the test server is published on another port. The rest is real SMB.
    real_connection = socket.create_connection

    def redirect(address: tuple[str, int], *args: Any, **kwargs: Any) -> socket.socket:
        assert address[1] == 445
        return real_connection((address[0], samba.port), *args, **kwargs)

    data = os.urandom(4096)
    target = folder / "direct" / "a.bin"
    transport = SmbTransport(samba.host, 445, "bios", "", "", timeout=20)

    # Only for this block, because the folder fixture connects to the real port to clean up.
    with monkeypatch.context() as patch:
        patch.setattr(socket, "create_connection", redirect)
        with transport:
            assert transport._conn.is_direct_tcp is True
            transport.makedirs(target.parent)
            assert transport.upload(local_file(tmp_path, data), target) == len(data)
            assert transport.read_bytes(target) == data


# End to end, through cli.main


@pytest.fixture
def app(samba: Samba, tmp_path: Path) -> Path:
    folder = tmp_path / "app"
    (folder / "config").mkdir(parents=True)
    (folder / "bios").mkdir()
    (folder / "config" / "config.yml").write_text(samba.config(), encoding="utf-8")
    return folder


def test_end_to_end_files_arrive_under_the_right_names_and_folders(
    samba: Samba,
    app: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bios = app / "bios"
    renamed = make_bios_file(bios, "my-copy.bin")
    nested = make_bios_file(bios, "ps1/nested source.rom")
    shared = make_bios_file(bios, "shared.img")
    make_bios_file(bios, "a-duplicate.bin", renamed.path.read_bytes())
    make_bios_file(bios, "junk.bin")
    make_bios_file(bios, ".keep", b"")
    entries = [
        make_missing(f"{folder}/scph-1001 (U).bin", renamed.md5, system="One"),
        make_missing(f"{folder}/amiga/bios/kick.CD32.ext", nested.md5, system="Two"),
        make_missing(f"{folder}/x/st.img", shared.md5, system="Three"),
        make_missing(f"{folder}/y/tos.img", shared.md5, system="Three"),
        make_missing(f"{folder}/never/filled.bin", "0" * 32, system="Four"),
    ]
    put_report(make_report_text(entries))
    before = snapshot(bios)

    assert cli.main([], base_dir=app) == 0

    assert snapshot(bios) == before
    with samba.guest() as transport:
        for entry, file in zip(entries, (renamed, nested, shared, shared), strict=False):
            assert transport.read_bytes(entry.target) == file.path.read_bytes()
        assert not transport.exists(folder / "never")
    output = capsys.readouterr().out
    assert "There are 5 missing bios in your RECALBOX" in output
    assert "Final result: 4/5 missing entries satisfied, 5 files analysed" in output
    assert "junk.bin: no match, kept" in output
    assert "PLEASE SCAN" in output


def test_end_to_end_running_again_gives_the_same_files(
    samba: Samba, app: Path, folder: PurePosixPath, put_report: PutReport
) -> None:
    file = make_bios_file(app / "bios", "copy.bin")
    target = folder / "ps1" / "a.bin"
    put_report(make_report_text([make_missing(target.as_posix(), file.md5)]))

    assert cli.main([], base_dir=app) == 0
    assert cli.main([], base_dir=app) == 0

    with samba.guest() as transport:
        assert transport.read_bytes(target) == file.path.read_bytes()


def test_end_to_end_an_incorrect_file_is_kept(
    samba: Samba,
    app: Path,
    folder: PurePosixPath,
    tmp_path: Path,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # DEC-54: the file on the server stays, even with a valid local file.
    valid = make_bios_file(app / "bios", "valid.bin")
    target = folder / "b.bin"
    with samba.guest() as transport:
        transport.makedirs(folder)
        transport.upload(local_file(tmp_path, b"the wrong file"), target)
    wrong = make_missing(target.as_posix(), valid.md5, incorrect=True, current_md5="c" * 32)
    put_report(make_report_text([wrong]))

    assert cli.main([], base_dir=app) == 0

    with samba.guest() as transport:
        assert transport.read_bytes(target) == b"the wrong file"
    assert f"INCORRECT: {target} is on the device" in capsys.readouterr().out


def test_end_to_end_an_incorrect_file_is_kept_beside_normal_uploads(
    samba: Samba,
    app: Path,
    folder: PurePosixPath,
    tmp_path: Path,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    valid = make_bios_file(app / "bios", "valid.bin")
    wanted = make_bios_file(app / "bios", "wanted.bin")
    kept, filled = folder / "b.bin", folder / "ok" / "a.bin"
    with samba.guest() as transport:
        transport.makedirs(folder)
        transport.upload(local_file(tmp_path, b"the wrong file"), kept)
    put_report(
        make_report_text(
            [
                make_missing(filled.as_posix(), wanted.md5),
                make_missing(kept.as_posix(), valid.md5, incorrect=True, current_md5="c" * 32),
            ]
        )
    )

    assert cli.main([], base_dir=app) == 0

    with samba.guest() as transport:
        assert transport.read_bytes(kept) == b"the wrong file"
        assert transport.read_bytes(filled) == wanted.path.read_bytes()
    output = capsys.readouterr().out
    assert f"valid.bin: valid for {kept}, which is incorrect on the device, kept" in output
    assert "Final result: 1/1 missing entries satisfied, 2 files analysed" in output


def test_end_to_end_nothing_missing(
    app: Path, put_report: PutReport, capsys: pytest.CaptureFixture[str]
) -> None:
    put_report(make_report_text([]))

    assert cli.main([], base_dir=app) == 0
    assert "No missing bios were found" in capsys.readouterr().out


def test_end_to_end_an_unrecognized_report_is_exit_4(
    app: Path, put_report: PutReport, capsys: pytest.CaptureFixture[str]
) -> None:
    put_report("A FORMAT BECK DOESN'T KNOW\r\n")

    assert cli.main([], base_dir=app) == ReportParseError.exit_code
    assert "doesn't look like a report" in capsys.readouterr().out


def test_end_to_end_no_report_is_exit_4(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([], base_dir=app) == 4

    assert "Generate the report on the device first" in capsys.readouterr().out


def test_end_to_end_wrong_password_is_exit_3_with_no_traceback(
    samba: Samba, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = samba.config(user="beck", password=BAD_CREDENTIAL)
    (app / "config" / "config.yml").write_text(config, encoding="utf-8")

    assert cli.main([], base_dir=app) == 3

    captured = capsys.readouterr()
    assert "refused the login" in captured.out
    assert BAD_CREDENTIAL not in captured.out + captured.err
    assert captured.err == ""


def test_end_to_end_unreachable_server_is_exit_3_with_no_traceback(
    samba: Samba, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = f'smb: {{user: "", passwd: "", server: "{samba.host}", port: 1}}\n'
    (app / "config" / "config.yml").write_text(config, encoding="utf-8")

    assert cli.main([], base_dir=app) == 3

    captured = capsys.readouterr()
    assert "Error connecting to SMB server" in captured.out
    assert captured.err == ""


def test_end_to_end_a_missing_config_is_exit_2(tmp_path: Path) -> None:
    assert cli.main([], base_dir=tmp_path) == ConfigError.exit_code
