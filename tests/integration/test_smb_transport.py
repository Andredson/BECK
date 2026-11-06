"""BECK against a real Samba server: what the fake SMB server can only assume (DEC-33).

Run with BECK_TEST_SMB_HOST=127.0.0.1 BECK_TEST_SMB_PORT=4450 uv run pytest -m integration
"""

import contextlib
import json
import os
import pty
import select
import signal
import socket
import subprocess
import sys
import termios
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
from tests.factories import make_bios_file, make_missing, make_report_text, md5_of, snapshot
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
        result = execute(plan(report, scan(tmp_path).files), transport, dry_run=False)

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
def app(samba: Samba, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "app"
    (folder / "bios").mkdir(parents=True)
    (folder / "settings.toml").write_text(samba.settings(), encoding="utf-8")
    (folder / "settings.toml").chmod(0o600)
    monkeypatch.setenv("BECK_CONFIG", str(folder / "settings.toml"))
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

    assert cli.main(["check"], base_dir=app) == 0

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


def test_end_to_end_an_unreadable_file_doesnt_stop_the_upload(
    samba: Samba,
    app: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    good = make_bios_file(app / "bios", "good.bin")
    (app / "bios" / "broken.bin").symlink_to(app / "no-such-target")
    target = folder / "a.bin"
    put_report(make_report_text([make_missing(target.as_posix(), good.md5)]))

    assert cli.main(["check"], base_dir=app) == 0

    with samba.guest() as transport:
        assert transport.read_bytes(target) == good.path.read_bytes()
    captured = capsys.readouterr()
    assert "broken.bin: can't be read, skipped: broken symlink" in captured.out
    assert captured.err == ""


def test_end_to_end_a_dry_run_changes_nothing_on_the_server(
    samba: Samba,
    app: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    file = make_bios_file(app / "bios", "copy.bin")
    target = folder / "ps1" / "a.bin"
    put_report(make_report_text([make_missing(target.as_posix(), file.md5)]))
    before = snapshot(app / "bios")

    assert cli.main(["check", "--dry-run", "--move"], base_dir=app) == 0

    assert snapshot(app / "bios") == before
    with samba.guest() as transport:
        assert not transport.exists(folder)
    assert f"copy.bin: would copy -> {target}" in capsys.readouterr().out


def test_end_to_end_move_checks_the_size_on_a_real_server_then_deletes(
    samba: Samba, app: Path, folder: PurePosixPath, put_report: PutReport
) -> None:
    file = make_bios_file(app / "bios", "copy.bin", os.urandom(3 * 1024 * 1024))
    data = file.path.read_bytes()
    first, second = folder / "a" / "x.bin", folder / "b" / "y.bin"
    entries = [make_missing(first.as_posix(), file.md5), make_missing(second.as_posix(), file.md5)]
    put_report(make_report_text(entries))

    assert cli.main(["check", "--move", "--yes"], base_dir=app) == 0

    assert not file.path.exists()
    with samba.guest() as transport:
        assert transport.read_bytes(first) == data
        assert transport.read_bytes(second) == data


def test_end_to_end_move_keeps_a_file_when_the_read_only_share_refuses(
    samba: Samba, tmp_path: Path
) -> None:
    file = make_bios_file(tmp_path, "copy.bin")
    built = plan([make_missing("x.bin", file.md5)], scan(tmp_path).files)

    with samba.guest("readonly") as transport:
        result = execute(built, transport, dry_run=False, move=True)

    assert file.path.exists()
    assert result.deleted == ()
    assert [error.item for error in result.errors] == ["x.bin"]


def test_end_to_end_with_a_target_url_and_no_config(
    samba: Samba, tmp_path: Path, folder: PurePosixPath, put_report: PutReport
) -> None:
    app = tmp_path / "no-config"
    good = make_bios_file(app / "bios", "good.bin")
    target = folder / "a.bin"
    put_report(make_report_text([make_missing(target.as_posix(), good.md5)]))
    url = f"smb://{samba.host}:{samba.port}/bios"

    assert cli.main(["check", "--target", url], base_dir=app) == 0

    with samba.guest() as transport:
        assert transport.read_bytes(target) == good.path.read_bytes()


def test_end_to_end_a_name_that_is_not_valid_utf8_reaches_a_real_server(
    samba: Samba,
    app: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = os.urandom(64)
    (app / "bios" / os.fsdecode(b"bad-\xff.bin")).write_bytes(data)
    target = folder / "a.bin"
    put_report(make_report_text([make_missing(target.as_posix(), md5_of(data))]))

    assert cli.main(["check"], base_dir=app) == 0

    with samba.guest() as transport:
        assert transport.read_bytes(target) == data
    output = capsys.readouterr().out
    assert f"bad-\\xff.bin: copied -> {target}" in output
    assert "PLEASE SCAN" in output


@pytest.mark.parametrize("flags", [(), ("--json",)], ids=["human", "json"])
def test_end_to_end_a_closed_pipe_changes_nothing_on_a_real_server(
    samba: Samba,
    tmp_path: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    flags: tuple[str, ...],
) -> None:
    source = tmp_path / "source"
    good = make_bios_file(source, "good.bin")
    for number in range(800):  # more than a buffer holds, in any supported Python
        (source / f"{'x' * 200}{number}.bin").write_bytes(number.to_bytes(4, "big"))
    target = folder / "a.bin"
    put_report(make_report_text([make_missing(target.as_posix(), good.md5)]))
    url = f"smb://{samba.host}:{samba.port}/bios"
    read_end, write_end = os.pipe()
    os.close(read_end)

    result = subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [sys.executable, "-m", "beck", *flags, "check", "--source", str(source), "--target", url],
        stdout=write_end,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        check=False,
        timeout=120,
        cwd=tmp_path,
    )
    os.close(write_end)

    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    with samba.guest() as transport:
        assert transport.read_bytes(target) == good.path.read_bytes()


def test_end_to_end_json_on_a_real_server(
    samba: Samba,
    tmp_path: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = tmp_path / "no-config"
    good = make_bios_file(app / "bios", "good.bin")
    target = folder / "a.zip"
    put_report(make_report_text([make_missing(target.as_posix(), good.md5)]))
    url = f"smb://{samba.host}:{samba.port}/bios"

    assert cli.main(["--json", "check", "--target", url], base_dir=app) == 0

    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is True
    assert doc["target"] == url
    assert [(u["target"], u["status"]) for u in doc["uploads"]] == [(target.as_posix(), "uploaded")]
    assert doc["uploads"][0]["warning"]
    with samba.guest() as transport:
        assert transport.read_bytes(target) == good.path.read_bytes()


def test_end_to_end_fail_if_missing_on_a_real_server(
    samba: Samba,
    tmp_path: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = tmp_path / "no-config"
    good = make_bios_file(app / "bios", "good.bin")
    target = folder / "good.bin"
    gone = folder / "gone.bin"
    entries = [make_missing(target.as_posix(), good.md5), make_missing(gone.as_posix(), "0" * 32)]
    put_report(make_report_text(entries))
    url = f"smb://{samba.host}:{samba.port}/bios"

    code = cli.main(["--json", "check", "--target", url, "--fail-if-missing"], base_dir=app)

    assert code == 5
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is False
    assert doc["errors"] == []
    assert [item["target"] for item in doc["still_missing"]] == [gone.as_posix()]
    with samba.guest() as transport:
        assert transport.read_bytes(target) == good.path.read_bytes()


def test_end_to_end_v_never_shows_the_credentials_on_a_real_server(
    samba: Samba,
    tmp_path: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "settings.toml").write_text(samba.settings("beck"), encoding="utf-8")
    monkeypatch.setenv("BECK_CONFIG", str(tmp_path / "settings.toml"))
    monkeypatch.setenv("BECK_SMB_PASSWORD", ACCOUNT_CREDENTIAL)
    good = make_bios_file(tmp_path / "bios", "good.bin")
    target = (folder / "good.bin").as_posix()
    put_report(make_report_text([make_missing(target, good.md5)]))

    assert cli.main(["-v", "check"], base_dir=tmp_path) == 0

    out = capsys.readouterr()
    assert f"Uploaded {target}" in out.err
    assert ACCOUNT_CREDENTIAL not in out.out + out.err
    assert "with a user name" in out.err
    with samba.guest() as transport:
        assert transport.read_bytes(PurePosixPath(target)) == good.path.read_bytes()


@pytest.mark.parametrize("mode", [[], ["-v"], ["--json"], ["--json", "-v"]], ids=str)
@pytest.mark.parametrize(
    ("password", "code"), [(ACCOUNT_CREDENTIAL, 0), (BAD_CREDENTIAL, 3)], ids=["right", "wrong"]
)
def test_end_to_end_no_output_holds_the_password_on_a_real_server(
    samba: Samba,
    tmp_path: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    mode: list[str],
    password: str,
    code: int,
) -> None:
    monkeypatch.setenv("BECK_SMB_PASSWORD", password)
    monkeypatch.setenv("BECK_CONFIG", str(tmp_path / "settings.toml"))
    (tmp_path / "settings.toml").write_text(samba.settings("beck"), encoding="utf-8")
    (tmp_path / "settings.toml").chmod(0o600)
    good = make_bios_file(tmp_path / "bios", "good.bin")
    put_report(make_report_text([make_missing((folder / "good.bin").as_posix(), good.md5)]))

    assert cli.main([*mode, "check"], base_dir=tmp_path) == code

    out = capsys.readouterr()
    assert password not in out.out + out.err
    assert "beck-test-password" not in out.out + out.err


@pytest.mark.parametrize("name", ["{folder}\\sideways.bin", "..\\climbed.bin"], ids=["into", "out"])
def test_end_to_end_a_backslash_can_not_reach_another_folder_on_a_real_server(
    samba: Samba, tmp_path: Path, folder: PurePosixPath, name: str
) -> None:
    """Before 07.6, the first of these wrote into that folder: SMB takes it as a separator."""
    good = make_bios_file(tmp_path / "bios", "a.bin")
    report = tmp_path / "report.txt"
    target = name.format(folder=folder)
    report.write_text(
        f"MISSING BIOS REPORT\n  MISSING REQUIRED BIOS: {target}\n"
        f"    Path: /recalbox/share/bios/{target}\n    Possible MD5 List:\n      {good.md5}\n",
        encoding="utf-8",
    )
    url = f"smb://{samba.host}:{samba.port}/bios"
    arguments = ["check", "--target", url, "--report-file", str(report)]

    assert cli.main(arguments, base_dir=tmp_path) == 3

    with samba.guest() as transport:
        assert not transport.exists(folder / "sideways.bin")


def at_a_real_prompt(
    arguments: list[str], *, typed: bytes = b"", interrupted: bool = False
) -> tuple[int, bytes, bytes]:
    """Run BECK on a pseudo-terminal, and answer once the prompt is up: exit code, stderr and echo.

    In its own session, so that getpass can't open the terminal of whoever runs these tests, and
    wait for them. With no terminal of its own, it uses stdin and prompts on stderr. That's also why
    Ctrl-C is a signal here: only a controlling terminal turns the key into one.
    """
    master, slave = pty.openpty()
    settings_before = termios.tcgetattr(master)
    process = subprocess.Popen(  # noqa: S603 - fixed arguments, no external input
        [sys.executable, "-m", "beck", *arguments],
        stdin=slave,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    os.close(slave)
    try:
        assert process.stderr is not None
        seen = b""
        while b": " not in seen:
            ready, _, _ = select.select([process.stderr], [], [], 20)
            assert ready, f"no prompt: {seen!r}"
            seen += os.read(process.stderr.fileno(), 1024)
        if interrupted:
            process.send_signal(signal.SIGINT)
        else:
            os.write(master, typed)
        _, rest = process.communicate(timeout=30)
        assert termios.tcgetattr(master) == settings_before, "the terminal wasn't left as it was"
        echoed = b""
        os.set_blocking(master, False)
        with contextlib.suppress(OSError):  # Linux reports the closed end as an I/O error
            echoed = os.read(master, 4096)
        return process.returncode, seen + rest, echoed
    finally:
        process.kill()
        process.wait()
        os.close(master)


def test_a_real_prompt_logs_in_to_a_real_server_and_shows_nothing_typed(samba: Samba) -> None:
    url = f"smb://beck@{samba.host}:{samba.port}/private"

    code, stderr, echoed = at_a_real_prompt(
        ["report", "--target", url], typed=ACCOUNT_CREDENTIAL.encode() + b"\n"
    )

    assert code == 4, stderr  # logged in, and that share has no report
    assert b"Password for beck on" in stderr
    assert ACCOUNT_CREDENTIAL.encode() not in stderr + echoed


def test_a_wrong_answer_at_a_real_prompt_is_exit_3(samba: Samba) -> None:
    url = f"smb://beck@{samba.host}:{samba.port}/private"

    code, stderr, echoed = at_a_real_prompt(
        ["report", "--target", url], typed=BAD_CREDENTIAL.encode() + b"\n"
    )

    assert code == 3, stderr
    assert BAD_CREDENTIAL.encode() not in stderr + echoed


def test_ctrl_d_at_a_real_prompt_is_exit_2(samba: Samba) -> None:
    url = f"smb://beck@{samba.host}:{samba.port}/private"

    code, stderr, _ = at_a_real_prompt(["report", "--target", url], typed=b"\x04")

    assert code == 2, stderr
    assert b"Traceback" not in stderr


def test_ctrl_c_at_a_real_prompt_is_exit_2_and_leaves_the_terminal_as_it_was(samba: Samba) -> None:
    url = f"smb://beck@{samba.host}:{samba.port}/private"

    code, stderr, _ = at_a_real_prompt(["report", "--target", url], interrupted=True)

    assert code == 2, stderr
    assert b"Traceback" not in stderr


def test_end_to_end_an_empty_user_is_a_guest_on_a_real_server(
    samba: Samba, tmp_path: Path, put_report: PutReport, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "settings.toml").write_text(samba.settings(""), encoding="utf-8")
    monkeypatch.setenv("BECK_CONFIG", str(tmp_path / "settings.toml"))
    monkeypatch.setenv("BECK_SMB_PASSWORD", BAD_CREDENTIAL)  # a guest doesn't send it
    put_report(make_report_text([]))

    assert cli.main(["report"], base_dir=tmp_path) == 0


def test_a_refused_connection_is_a_json_document(
    samba: Samba, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"smb://{samba.host}:{samba.port}/no-such-share"

    assert cli.main(["--json", "report", "--target", url], base_dir=tmp_path) == 3

    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is False
    assert doc["target"] == url
    assert doc["errors"][0]["code"] == "transport"


def test_end_to_end_with_a_sub_path_in_the_target_url(
    samba: Samba, tmp_path: Path, folder: PurePosixPath
) -> None:
    # Like smb://recalbox/share/bios: the report and the targets are inside a folder of the share.
    app = tmp_path / "no-config"
    good = make_bios_file(app / "bios", "good.bin")
    report = tmp_path / "report.txt"
    report.write_bytes(make_report_text([make_missing("ps1/a.bin", good.md5)]).encode())
    with samba.guest() as transport:
        transport.makedirs(folder)
        transport.upload(report, folder / "missing_bios_report.txt")
    url = f"smb://{samba.host}:{samba.port}/bios/{folder}"

    assert cli.main(["check", "--target", url], base_dir=app) == 0

    with samba.guest() as transport:
        assert transport.read_bytes(folder / "ps1" / "a.bin") == good.path.read_bytes()
        assert not transport.exists(PurePosixPath("ps1"))


def test_report_reads_a_real_server_and_writes_nothing(
    samba: Samba,
    tmp_path: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = folder / "ps1" / "a.bin"
    put_report(make_report_text([make_missing(target.as_posix(), "0" * 32)]))
    url = f"smb://{samba.host}:{samba.port}/bios"

    assert cli.main(["report", "--target", url], base_dir=tmp_path) == 0

    with samba.guest() as transport:
        assert not transport.exists(folder)
    assert "  a.bin (required)" in capsys.readouterr().out


def test_end_to_end_running_again_keeps_the_file(
    samba: Samba,
    app: Path,
    folder: PurePosixPath,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    file = make_bios_file(app / "bios", "copy.bin")
    target = folder / "ps1" / "a.bin"
    put_report(make_report_text([make_missing(target.as_posix(), file.md5)]))

    assert cli.main(["check"], base_dir=app) == 0
    assert cli.main(["check"], base_dir=app) == 0

    with samba.guest() as transport:
        assert transport.read_bytes(target) == file.path.read_bytes()
    assert f"copy.bin: already on the device, kept -> {target}" in capsys.readouterr().out


def test_end_to_end_a_name_differing_only_in_case_counts_as_there(
    samba: Samba,
    app: Path,
    folder: PurePosixPath,
    tmp_path: Path,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Samba treats A.BIN and a.bin as one file, so uploading would overwrite it.
    file = make_bios_file(app / "bios", "copy.bin")
    with samba.guest() as transport:
        transport.makedirs(folder)
        transport.upload(local_file(tmp_path, b"already here"), folder / "a.bin")
    put_report(make_report_text([make_missing(f"{folder}/A.BIN", file.md5)]))

    assert cli.main(["check"], base_dir=app) == 0

    with samba.guest() as transport:
        assert transport.read_bytes(folder / "a.bin") == b"already here"
    assert "already on the device, kept" in capsys.readouterr().out


def test_end_to_end_overwrite_replaces_files(
    samba: Samba,
    app: Path,
    folder: PurePosixPath,
    tmp_path: Path,
    put_report: PutReport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stale, bad = make_bios_file(app / "bios", "stale.bin"), make_bios_file(app / "bios", "bad.bin")
    stale_target, bad_target = folder / "stale.bin", folder / "bad.bin"
    with samba.guest() as transport:
        transport.makedirs(folder)
        transport.upload(local_file(tmp_path, b"an old file"), stale_target)
        transport.upload(local_file(tmp_path, b"a bad dump"), bad_target)
    put_report(
        make_report_text(
            [
                make_missing(stale_target.as_posix(), stale.md5),
                make_missing(bad_target.as_posix(), bad.md5, incorrect=True, current_md5="c" * 32),
            ]
        )
    )

    assert cli.main(["check", "--overwrite"], base_dir=app) == 0

    with samba.guest() as transport:
        assert transport.read_bytes(stale_target) == stale.path.read_bytes()
        assert transport.read_bytes(bad_target) == bad.path.read_bytes()
    output = capsys.readouterr().out
    assert f"stale.bin: replaced -> {stale_target}" in output
    assert f"bad.bin: replaced -> {bad_target}" in output


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

    assert cli.main(["check"], base_dir=app) == 0

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

    assert cli.main(["check"], base_dir=app) == 0

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

    assert cli.main(["check"], base_dir=app) == 0
    assert "No missing bios were found" in capsys.readouterr().out


def test_end_to_end_an_unrecognized_report_is_exit_4(
    app: Path, put_report: PutReport, capsys: pytest.CaptureFixture[str]
) -> None:
    put_report("A FORMAT BECK DOESN'T KNOW\r\n")

    assert cli.main(["check"], base_dir=app) == ReportParseError.exit_code
    assert "doesn't look like a report" in capsys.readouterr().out


def test_end_to_end_no_report_is_exit_4(app: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["check"], base_dir=app) == 4

    assert "Generate the report on the device first" in capsys.readouterr().out


def test_end_to_end_wrong_password_is_exit_3_with_no_traceback(
    samba: Samba, app: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (app / "settings.toml").write_text(samba.settings("beck"), encoding="utf-8")
    monkeypatch.setenv("BECK_SMB_PASSWORD", BAD_CREDENTIAL)

    assert cli.main(["check"], base_dir=app) == 3

    captured = capsys.readouterr()
    assert "refused the login" in captured.out
    assert BAD_CREDENTIAL not in captured.out + captured.err
    assert captured.err == ""


def test_end_to_end_unreachable_server_is_exit_3_with_no_traceback(
    samba: Samba, app: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (app / "settings.toml").write_text(samba.settings(port=1), encoding="utf-8")

    assert cli.main(["check"], base_dir=app) == 3

    captured = capsys.readouterr()
    assert "Error connecting to SMB server" in captured.out
    assert captured.err == ""


def test_end_to_end_a_missing_config_is_exit_2(tmp_path: Path) -> None:
    assert cli.main(["check"], base_dir=tmp_path) == ConfigError.exit_code
