"""A stream that fails can't change a run (DEC-62): the same work, and the same exit code.

Most of these run real processes with real pipes, because these failures depend on real buffers, and
on what the interpreter does when it exits.
"""

import errno
import io
import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import pytest

from beck import cli
from beck.output import finish_output, print_safely
from beck.output.console import ConsoleRenderer
from beck.output.json import JsonRenderer
from tests.conftest import REAL_REPORT, REPORTS
from tests.factories import make_missing, make_report_text, md5_of, snapshot

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="needs sh and POSIX descriptors")

# Enough long lines to overflow stdout's buffer in any supported Python: 8 KiB in 3.11 to 3.13, and
# 128 KiB in 3.14. test_lots_of_output_is_more_than_a_buffer checks that this stays true.
LOTS = 800
LONG_NAME = "a-file-that-matches-nothing-".ljust(200, "x")
GOOD = os.urandom(64)
SHIM = Path(__file__).resolve().parents[2] / "check_bios.py"
FULL_DISK = Path("/dev/full")

MODES = {"human": (), "json": ("--json",)}
STDOUTS = ("readable", "closed pipe", "full disk", "closed")
BROKEN_STDOUTS = ("closed pipe", "full disk", "closed")


# Real processes


def run_process(
    command: Sequence[str],
    *,
    stdout: str = "readable",
    stderr: Any = subprocess.PIPE,
    stdin: Any = subprocess.DEVNULL,
    close: str = "",
    strict_stdin: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    """Run a command with this stdout. ``close`` is what the shell closes first, like ``<&-``."""
    if "full disk" in (stdout, stderr) and not FULL_DISK.exists():
        pytest.skip("this system has no /dev/full")
    arguments = list(command)
    redirects = f"{close} >&-" if stdout == "closed" else close
    if redirects:
        arguments = ["sh", "-c", f'exec "$0" "$@" {redirects}', *arguments]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8:strict"} if strict_stdin else None
    to_close: list[int] = []
    target: Any = subprocess.PIPE
    if stdout == "closed pipe":
        read_end, target = os.pipe()
        os.close(read_end)
        to_close.append(target)
    elif stdout == "full disk":
        target = os.open(FULL_DISK, os.O_WRONLY)
        to_close.append(target)
    error_target = stderr
    if stderr == "full disk":
        error_target = os.open(FULL_DISK, os.O_WRONLY)
        to_close.append(error_target)
    try:
        return subprocess.run(  # noqa: S603 - fixed arguments, no external input
            arguments,
            stdout=target,
            stderr=error_target,
            stdin=stdin,
            check=False,
            timeout=120,
            env=env,
        )
    finally:
        for descriptor in to_close:
            os.close(descriptor)


def run_beck(*arguments: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
    return run_process([sys.executable, "-m", "beck", *arguments], **kwargs)


def on_a_terminal(
    *arguments: str, typed: bytes, **kwargs: Any
) -> subprocess.CompletedProcess[bytes]:
    """Run BECK with a real pseudo-terminal on stdin, where these bytes were typed."""
    import pty  # here because it doesn't exist on Windows

    master, slave = pty.openpty()
    try:
        os.write(master, typed)
        return run_beck(*arguments, stdin=slave, strict_stdin=True, **kwargs)
    finally:
        os.close(slave)
        os.close(master)


def assert_no_crash(result: subprocess.CompletedProcess[bytes]) -> None:
    assert b"Traceback" not in result.stderr
    assert b"Exception ignored" not in result.stderr


def write_report(device: Path, *entries: Any) -> None:
    (device / "missing_bios_report.txt").write_text(
        make_report_text(entries), encoding="utf-8", newline=""
    )


@dataclass(frozen=True)
class Sources:
    """Local folders that make BECK print little, or a lot before or after the uploads."""

    little: Path
    after: Path
    before: Path


@pytest.fixture(scope="module")
def sources(tmp_path_factory: pytest.TempPathFactory) -> Sources:
    root = tmp_path_factory.mktemp("sources")
    little, after, before = root / "little", root / "after", root / "before"
    for folder in (little, after, before):
        folder.mkdir()
        (folder / "good.bin").write_bytes(GOOD)
    for number in range(LOTS):
        name = f"{LONG_NAME}{number:05}.bin"
        (after / name).write_bytes(number.to_bytes(4, "big"))
        (before / name).symlink_to(before / "nowhere")
    return Sources(little, after, before)


@pytest.fixture
def device(tmp_path: Path) -> Path:
    folder = tmp_path / "device"
    folder.mkdir()
    write_report(folder, make_missing("good.bin", md5_of(GOOD)))
    return folder


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "source"
    folder.mkdir()
    (folder / "good.bin").write_bytes(GOOD)
    return folder


def assert_stderr_for(stdout: str, result: subprocess.CompletedProcess[bytes]) -> None:
    """A full disk says so in one line, and everything else stays quiet."""
    if stdout == "full disk":
        lines = result.stderr.decode().splitlines()
        assert len(lines) == 1, result.stderr
        assert "No space left on device" in lines[0]
        assert "output" in lines[0]
    else:
        assert result.stderr == b""


def test_lots_of_output_is_more_than_a_buffer(sources: Sources, device: Path) -> None:
    """Otherwise the tests below wouldn't reach the failure that happens in the middle of a run."""
    write_report(device, make_missing("good.bin", md5_of(GOOD)))
    target = ["--target-dir", str(device), "--dry-run"]

    before = run_beck("check", "--source", str(sources.before), *target).stdout
    after = run_beck("check", "--source", str(sources.after), *target).stdout
    document = run_beck("--json", "check", "--source", str(sources.after), *target).stdout

    # Unreadable files are listed before the uploads, and each file's result after them.
    assert before.index(b"would copy") > io.DEFAULT_BUFFER_SIZE
    assert len(after) > io.DEFAULT_BUFFER_SIZE
    assert before.count(b"can't be read") == after.count(b"no match, kept") == LOTS
    assert len(document) > io.DEFAULT_BUFFER_SIZE


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("stdout", STDOUTS)
@pytest.mark.parametrize("output", ["little", "after", "before"])
def test_the_same_work_and_exit_code_whatever_happens_to_stdout(
    sources: Sources, device: Path, mode: str, stdout: str, output: str
) -> None:
    folder = getattr(sources, output)
    before = sorted(path.name for path in folder.iterdir())

    result = run_beck(
        *MODES[mode], "check", "--source", str(folder), "--target-dir", str(device), stdout=stdout
    )

    assert result.returncode == 0, result.stderr
    assert_no_crash(result)
    assert_stderr_for(stdout, result)
    assert (device / "good.bin").read_bytes() == GOOD
    assert sorted(path.name for path in folder.iterdir()) == before
    if stdout == "readable":
        if mode == "json":
            assert json.loads(result.stdout)["ok"] is True
        else:
            assert b"Final result: 1/1" in result.stdout


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("stdout", STDOUTS)
def test_a_failed_upload_still_exits_with_3(
    sources: Sources, tmp_path: Path, mode: str, stdout: str
) -> None:
    device = tmp_path / "device"
    device.mkdir()
    (device / "blocked").write_bytes(b"a file, not a folder")
    write_report(device, make_missing("blocked/good.bin", md5_of(GOOD)))

    result = run_beck(
        *MODES[mode],
        "check",
        "--source",
        str(sources.after),
        "--target-dir",
        str(device),
        stdout=stdout,
    )

    assert result.returncode == 3, result.stderr
    assert_no_crash(result)
    assert_stderr_for(stdout, result)
    assert (device / "blocked").read_bytes() == b"a file, not a folder"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("stdout", STDOUTS)
def test_move_deletes_the_same_files_whatever_happens_to_stdout(
    sources: Sources, tmp_path: Path, device: Path, mode: str, stdout: str
) -> None:
    folder = tmp_path / "copy"
    shutil.copytree(sources.after, folder)

    result = run_beck(
        *MODES[mode],
        "check",
        "--source",
        str(folder),
        "--target-dir",
        str(device),
        "--move",
        "--yes",
        stdout=stdout,
    )

    assert result.returncode == 0, result.stderr
    assert_no_crash(result)
    assert (device / "good.bin").read_bytes() == GOOD
    assert not (folder / "good.bin").exists()
    assert sum(1 for _ in folder.iterdir()) == LOTS


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("stdout", BROKEN_STDOUTS)
def test_a_run_that_stops_keeps_its_exit_code(
    tmp_path: Path, source: Path, mode: str, stdout: str
) -> None:
    empty = tmp_path / "no-report"
    empty.mkdir()

    result = run_beck(
        *MODES[mode], "check", "--source", str(source), "--target-dir", str(empty), stdout=stdout
    )

    assert result.returncode == 4, result.stderr
    assert_no_crash(result)
    assert_stderr_for(stdout, result)


@pytest.mark.parametrize("stdout", BROKEN_STDOUTS)
def test_a_rejected_command_line_keeps_its_exit_code(stdout: str) -> None:
    result = run_beck("--json", "check", "--no-such-flag", stdout=stdout)

    assert result.returncode == 2, result.stderr
    assert_no_crash(result)
    assert_stderr_for(stdout, result)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("stdout", BROKEN_STDOUTS)
def test_report_keeps_its_exit_code(mode: str, stdout: str) -> None:
    report = REPORTS / f"{REAL_REPORT}.txt"

    result = run_beck(*MODES[mode], "report", "--report-file", str(report), stdout=stdout)

    assert result.returncode == 0, result.stderr
    assert_no_crash(result)
    assert_stderr_for(stdout, result)


@pytest.mark.parametrize("stdout", BROKEN_STDOUTS)
def test_scan_keeps_its_exit_code(sources: Sources, stdout: str) -> None:
    result = run_beck("--json", "scan", "--source", str(sources.after), stdout=stdout)

    assert result.returncode == 0, result.stderr
    assert_no_crash(result)
    assert_stderr_for(stdout, result)


@pytest.mark.parametrize("flag", ["--help", "--version"])
@pytest.mark.parametrize("stdout", ["closed pipe", "full disk"])
def test_help_and_version_keep_their_exit_code(flag: str, stdout: str) -> None:
    result = run_beck(flag, stdout=stdout)

    assert result.returncode == 0, result.stderr
    assert_no_crash(result)
    assert_stderr_for(stdout, result)


# What happens to stderr


@pytest.mark.parametrize("stderr", ["full disk", "closed"])
def test_a_failing_stderr_changes_nothing(stderr: str, source: Path, device: Path) -> None:
    arguments = ["check", "--source", str(source), "--target-dir", str(device)]
    streams: dict[str, Any] = {"close": "2>&-"} if stderr == "closed" else {"stderr": "full disk"}

    good = run_beck(*arguments, **streams)
    rejected = run_beck("check", "--no-such-flag", **streams)

    assert good.returncode == 0
    assert b"Final result: 1/1" in good.stdout
    assert (device / "good.bin").read_bytes() == GOOD
    assert rejected.returncode == 2


@pytest.mark.parametrize("stderr", ["full disk", "closed"])
def test_the_shim_notice_cannot_change_the_run(stderr: str, source: Path, device: Path) -> None:
    streams: dict[str, Any] = {"close": "2>&-"} if stderr == "closed" else {"stderr": "full disk"}

    result = run_process(
        [sys.executable, str(SHIM), "--json", "--source", str(source), "--target-dir", str(device)],
        **streams,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["ok"] is True, "print(file=None) would write the notice here"
    assert (device / "good.bin").read_bytes() == GOOD


# A prompt that can't get an answer


def move_arguments(source: Path, device: Path) -> list[str]:
    return ["check", "--source", str(source), "--target-dir", str(device), "--move"]


def assert_nothing_changed(
    source: Path, device: Path, before: tuple[Any, Any], result: subprocess.CompletedProcess[bytes]
) -> None:
    assert result.returncode == 2, result.stderr
    assert_no_crash(result)
    assert (snapshot(source), snapshot(device)) == before


def test_invalid_bytes_typed_at_the_prompt_count_as_no(source: Path, device: Path) -> None:
    before = snapshot(source), snapshot(device)

    result = on_a_terminal(*move_arguments(source, device), typed=b"\xff\n")

    assert_nothing_changed(source, device, before, result)
    assert b"you didn't confirm" in result.stdout


def test_a_closed_stdin_cannot_be_asked(source: Path, device: Path) -> None:
    before = snapshot(source), snapshot(device)

    result = run_beck(*move_arguments(source, device), close="<&-")

    assert_nothing_changed(source, device, before, result)
    assert b"can't ask" in result.stdout
    assert b"--yes" in result.stdout


def test_a_closed_stderr_cannot_ask(source: Path, device: Path) -> None:
    before = snapshot(source), snapshot(device)

    result = on_a_terminal(*move_arguments(source, device), typed=b"y\n", close="2>&-")

    assert_nothing_changed(source, device, before, result)
    assert b"can't ask" in result.stdout


def test_a_stderr_that_fails_while_asking_cannot_ask(source: Path, device: Path) -> None:
    before = snapshot(source), snapshot(device)

    result = on_a_terminal(*move_arguments(source, device), typed=b"y\n", stderr="full disk")

    assert result.returncode == 2
    assert (snapshot(source), snapshot(device)) == before
    assert b"can't ask" in result.stdout


def test_a_terminal_still_works_when_it_can_ask(source: Path, device: Path) -> None:
    result = on_a_terminal(*move_arguments(source, device), typed=b"y\n")

    assert result.returncode == 0, result.stderr
    assert not (source / "good.bin").exists()
    assert (device / "good.bin").read_bytes() == GOOD


def test_a_terminal_still_takes_no_for_an_answer(source: Path, device: Path) -> None:
    before = snapshot(source), snapshot(device)

    result = on_a_terminal(*move_arguments(source, device), typed=b"n\n")

    assert_nothing_changed(source, device, before, result)
    assert b"you didn't confirm" in result.stdout


def test_a_closed_stdout_can_still_be_asked(source: Path, device: Path) -> None:
    result = on_a_terminal(*move_arguments(source, device), typed=b"y\n", stdout="closed")

    assert result.returncode == 0, result.stderr
    assert not (source / "good.bin").exists()


# In this process: each branch on its own


class Failing(io.StringIO):
    """A stream that raises this error whenever it's written or flushed."""

    def __init__(self, error: OSError) -> None:
        super().__init__()
        self.error = error

    def write(self, _text: str) -> NoReturn:
        raise self.error

    def flush(self) -> NoReturn:
        raise self.error


DISK_FULL = OSError(errno.ENOSPC, "No space left on device")


def test_a_closed_stream_prints_nowhere(capsys: pytest.CaptureFixture[str]) -> None:
    print_safely("the notice", None)

    assert capsys.readouterr().out == ""


def test_a_closed_pipe_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    print_safely("text", Failing(BrokenPipeError(errno.EPIPE, "Broken pipe")))

    assert caplog.records == []


def test_any_other_failure_is_logged_with_its_reason(caplog: pytest.LogCaptureFixture) -> None:
    print_safely("text", Failing(DISK_FULL))

    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert "No space left on device" in caplog.text


def test_a_real_pipe_stops_failing_after_the_first_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    read_end, write_end = os.pipe()
    os.close(read_end)
    stream = os.fdopen(write_end, "w")
    monkeypatch.setattr(sys, "stdout", stream)
    stream.write("buffered")

    finish_output()  # would raise BrokenPipeError
    print_safely("later", stream)
    finish_output()

    stream.close()  # would raise too, if anything were left that could fail
    assert caplog.records == []


def test_no_descriptor_is_left_open(monkeypatch: pytest.MonkeyPatch) -> None:
    read_end, write_end = os.pipe()
    os.close(read_end)
    stream = os.fdopen(write_end, "w")
    monkeypatch.setattr(sys, "stdout", stream)
    stream.write("buffered")
    before = sum(1 for _ in Path("/dev/fd").iterdir())

    finish_output()

    assert sum(1 for _ in Path("/dev/fd").iterdir()) == before
    stream.close()


def test_finish_output_handles_closed_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    finish_output()


@pytest.mark.parametrize("name", ["stdout", "stderr"])
def test_finish_output_handles_a_stream_that_fails(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(sys, name, Failing(BrokenPipeError(errno.EPIPE, "Broken pipe")))

    finish_output()


@pytest.mark.parametrize("flags", MODES.values(), ids=MODES)
@pytest.mark.parametrize(
    "stdout",
    [None, Failing(BrokenPipeError(errno.EPIPE, "Broken pipe")), Failing(DISK_FULL)],
    ids=["closed", "closed-pipe", "full-disk"],
)
def test_a_run_in_this_process_ignores_a_failing_stdout(
    source: Path,
    device: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: io.StringIO | None,
    flags: tuple[str, ...],
) -> None:
    monkeypatch.setattr(sys, "stdout", stdout)

    code = cli.main([*flags, "check", "--source", str(source), "--target-dir", str(device)])

    assert code == 0
    assert (device / "good.bin").read_bytes() == GOOD


def test_a_renderer_with_no_stdout_has_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)

    assert ConsoleRenderer(environ={"FORCE_COLOR": "1"}).color is False


class Keyboard:
    """A terminal on stdin. It raises this error when read, or else gives what was typed."""

    def __init__(self, typed: str = "", error: Exception | None = None) -> None:
        self.typed = typed
        self.error = error

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        if self.error is not None:
            raise self.error
        return self.typed


@pytest.mark.parametrize(
    ("stdin", "stderr", "expected"),
    [
        (None, io.StringIO(), False),
        (Keyboard(), None, False),
        (io.StringIO(), io.StringIO(), False),
        (Keyboard(), io.StringIO(), True),
    ],
    ids=["closed-stdin", "closed-stderr", "no-terminal", "terminal"],
)
def test_it_can_ask_only_with_a_terminal_and_a_stderr(
    monkeypatch: pytest.MonkeyPatch, stdin: Any, stderr: Any, expected: bool
) -> None:
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stderr", stderr)

    assert ConsoleRenderer(io.StringIO(), {}).can_ask() is expected


def test_json_never_can_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", Keyboard())

    assert JsonRenderer("check", frontend="recalbox", dry_run=False).can_ask() is False


def run_with_a_prompt(source: Path, device: Path) -> int:
    return cli.main(move_arguments(source, device))


def test_a_read_that_fails_cannot_ask(
    source: Path,
    device: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "stdin", Keyboard(error=OSError(errno.EIO, "Input/output error")))
    before = snapshot(source), snapshot(device)

    assert run_with_a_prompt(source, device) == 2

    assert "can't ask" in capsys.readouterr().out
    assert (snapshot(source), snapshot(device)) == before


def test_a_stderr_that_fails_cannot_ask_in_this_process(
    source: Path,
    device: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "stdin", Keyboard("y\n"))
    monkeypatch.setattr(sys, "stderr", Failing(DISK_FULL))
    before = snapshot(source), snapshot(device)

    assert run_with_a_prompt(source, device) == 2

    assert "can't ask" in capsys.readouterr().out
    assert (snapshot(source), snapshot(device)) == before


def test_an_answer_that_is_not_text_is_no(
    source: Path,
    device: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    monkeypatch.setattr(sys, "stdin", Keyboard(error=error))
    before = snapshot(source), snapshot(device)

    assert run_with_a_prompt(source, device) == 2

    assert "you didn't confirm" in capsys.readouterr().out
    assert (snapshot(source), snapshot(device)) == before
