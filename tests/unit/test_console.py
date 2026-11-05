"""The console renderer: when to use color, and what each outcome looks like."""

import ctypes
import io
import logging
import sys
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from beck.models import Duplicate, ItemError, LocalFile, Plan, PlannedUpload, RunResult
from beck.output import console
from beck.output.console import ConsoleRenderer, configure_logging, enable_windows_ansi, wants_color
from tests.factories import make_local_file, make_missing

A, B, C, D = "a" * 32, "b" * 32, "c" * 32, "d" * 32


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def upload(file: LocalFile, target: str) -> PlannedUpload:
    return PlannedUpload(file, PurePosixPath(target), make_missing(target, file.md5))


def rendered(result: RunResult, *, color: bool = False) -> list[str]:
    stream = io.StringIO()
    ConsoleRenderer(stream, {"FORCE_COLOR": "1"} if color else {}).result(result)
    return stream.getvalue().splitlines()


@pytest.mark.parametrize(
    ("environ", "terminal", "expected"),
    [
        ({}, True, True),
        ({}, False, False),
        ({"NO_COLOR": "1"}, True, False),
        ({"NO_COLOR": "0"}, True, False),
        ({"NO_COLOR": ""}, True, True),
        ({"FORCE_COLOR": "1"}, False, True),
        ({"FORCE_COLOR": "0"}, False, True),
        ({"FORCE_COLOR": ""}, False, False),
        ({"NO_COLOR": "1", "FORCE_COLOR": "1"}, True, False),
        ({"NO_COLOR": "1", "FORCE_COLOR": "1"}, False, False),
    ],
)
def test_when_color_is_used(environ: dict[str, str], terminal: bool, expected: bool) -> None:
    stream = Terminal() if terminal else io.StringIO()

    assert wants_color(stream, environ) is expected


def test_a_terminal_that_cannot_show_color_gets_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console, "enable_windows_ansi", lambda: False)

    assert wants_color(Terminal(), {}) is False


def test_the_environment_is_read_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert ConsoleRenderer(io.StringIO()).color is True


def test_stdout_is_the_default_stream(capsys: pytest.CaptureFixture[str]) -> None:
    ConsoleRenderer(environ={}).nothing_missing()

    captured = capsys.readouterr()
    assert captured.out == "No missing bios were found in your RECALBOX!\n"
    assert captured.err == ""


class FakeKernel32:
    def __init__(self, *, get_mode_works: bool = True, set_mode_works: bool = True) -> None:
        self.get_mode_works = get_mode_works
        self.set_mode_works = set_mode_works
        self.mode_set: int | None = None

    def GetStdHandle(self, number: int) -> int:
        assert number == -11
        return 7

    def GetConsoleMode(self, handle: int, mode: Any) -> int:
        assert handle == 7
        mode._obj.value = 0x0001
        return int(self.get_mode_works)

    def SetConsoleMode(self, handle: int, mode: int) -> int:
        self.mode_set = mode
        return int(self.set_mode_works)


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    monkeypatch.setattr(sys, "platform", "win32")
    yield monkeypatch


def test_other_systems_need_nothing_enabled() -> None:
    assert enable_windows_ansi() is True


def test_windows_turns_on_virtual_terminal_keeping_the_mode(
    on_windows: pytest.MonkeyPatch,
) -> None:
    kernel32 = FakeKernel32()
    on_windows.setattr(ctypes, "windll", type("W", (), {"kernel32": kernel32}), raising=False)

    assert enable_windows_ansi() is True
    assert kernel32.mode_set == 0x0005


@pytest.mark.parametrize(
    "kernel32",
    [FakeKernel32(get_mode_works=False), FakeKernel32(set_mode_works=False)],
    ids=["not-a-console", "refused"],
)
def test_windows_falls_back_to_no_color(
    on_windows: pytest.MonkeyPatch, kernel32: FakeKernel32
) -> None:
    on_windows.setattr(ctypes, "windll", type("W", (), {"kernel32": kernel32}), raising=False)

    assert enable_windows_ansi() is False


def test_windows_without_the_library_falls_back_to_no_color(on_windows: pytest.MonkeyPatch) -> None:
    on_windows.delattr(ctypes, "windll", raising=False)

    assert enable_windows_ansi() is False


@pytest.mark.parametrize(
    ("call", "plain", "painted"),
    [
        (
            lambda r: r.missing_count(232),
            "There are 232 missing bios in your RECALBOX",
            "There are \033[35m232\033[0m missing bios in your RECALBOX",
        ),
        (
            lambda r: r.nothing_missing(),
            "No missing bios were found in your RECALBOX!",
            "\033[36mNo missing bios were found in your RECALBOX!\033[0m",
        ),
        (
            lambda r: r.files_found(3),
            "There are 3 possible bios to be analysed in your system",
            "There are \033[35m3\033[0m possible bios to be analysed in your system",
        ),
        (
            lambda r: r.no_files(Path("bios")),
            "No BIOS files found in bios",
            "\033[36mNo BIOS files found in bios\033[0m",
        ),
        (lambda r: r.error("boom"), "Error: boom", "\033[91mError\033[0m: boom"),
    ],
    ids=["missing-count", "nothing-missing", "files-found", "no-files", "error"],
)
def test_messages_match_stage_03(call: Any, plain: str, painted: str) -> None:
    for environ, expected in (({}, plain), ({"FORCE_COLOR": "1"}, painted)):
        stream = io.StringIO()
        call(ConsoleRenderer(stream, environ))
        assert stream.getvalue() == f"{expected}\n"


def test_a_normal_run_reads_like_stage_03() -> None:
    copy, dup, full, junk = (
        make_local_file("copy.bin", A),
        make_local_file("dup.bin", A),
        make_local_file("full.bin", B),
        make_local_file("x", C),
    )
    first, second = upload(copy, "a.bin"), upload(copy, "ps1/b.bin")
    plan = Plan(
        uploads=(first, second),
        duplicates=(Duplicate(file=dup, of=copy),),
        unmatched=(junk,),
        already_filled=(full,),
        still_missing=(make_missing("gone.bin", D),),
    )

    lines = rendered(RunResult(plan=plan, completed=(first, second)))

    assert lines == [
        "FOUND: a.bin -> a.bin",
        "FOUND: b.bin -> ps1/b.bin",
        "copy.bin: copied -> a.bin",
        "copy.bin: copied -> ps1/b.bin",
        "dup.bin: duplicate of copy.bin, kept",
        "full.bin: target already filled, kept",
        "x: no match, kept",
        "Final result: 2/3 missing entries satisfied, 4 files analysed",
        "*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***",
    ]


def test_colors_match_stage_03() -> None:
    first = upload(make_local_file("copy.bin", A), "a.bin")

    lines = rendered(RunResult(plan=Plan(uploads=(first,)), completed=(first,)), color=True)

    assert lines == [
        "\033[92mFOUND:\033[0m a.bin -> a.bin",
        "copy.bin: copied -> a.bin",
        "Final result: \033[92m1\033[0m/\033[94m1\033[0m missing entries satisfied, "
        "1 files analysed",
        "\033[35m*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***\033[0m",
    ]


def test_file_lines_are_sorted_by_path_as_text() -> None:
    slash, dash = make_local_file("a/x.bin", A), make_local_file("a-b/x.bin", B)

    lines = rendered(RunResult(plan=Plan(unmatched=(slash, dash))))

    assert lines[:2] == ["a-b/x.bin: no match, kept", "a/x.bin: no match, kept"]


def test_nothing_uploaded_has_no_scan_message() -> None:
    lines = rendered(
        RunResult(
            plan=Plan(unmatched=(make_local_file("x", C),), still_missing=(make_missing("a", B),))
        )
    )

    assert lines == [
        "x: no match, kept",
        "Final result: 0/1 missing entries satisfied, 1 files analysed",
    ]


def test_entries_for_one_target_count_once_in_the_summary() -> None:
    gone = (make_missing("x.pce", A), make_missing("x.pce", B), make_missing("y.pce", C))

    assert rendered(RunResult(plan=Plan(still_missing=gone)))[-1] == (
        "Final result: 0/2 missing entries satisfied, 0 files analysed"
    )


def test_a_file_sent_to_two_targets_counts_once_in_the_summary() -> None:
    copy = make_local_file("copy.bin", A)
    first, second = upload(copy, "a.bin"), upload(copy, "b.bin")
    plan = Plan(uploads=(first, second))

    assert rendered(RunResult(plan=plan, completed=(first, second)))[-2] == (
        "Final result: 2/2 missing entries satisfied, 1 files analysed"
    )


def test_failed_and_skipped_uploads_are_shown() -> None:
    done = upload(make_local_file("a.bin", A), "a.bin")
    failed = upload(make_local_file("b.bin", B), "b.bin")
    skipped = upload(make_local_file("c.bin", C), "blocked/c.bin")
    plan = Plan(uploads=(done, failed, skipped))
    result = RunResult(
        plan=plan,
        completed=(done,),
        skipped=(skipped,),
        errors=(
            ItemError(item="b.bin", message="Error uploading b.bin"),
            ItemError(item="blocked", message="Error creating folder blocked"),
        ),
    )

    assert rendered(result) == [
        "FOUND: a.bin -> a.bin",
        "a.bin: copied -> a.bin",
        "b.bin: failed -> b.bin",
        "c.bin: skipped -> blocked/c.bin",
        "Error: Error uploading b.bin",
        "Error: Error creating folder blocked",
        "Final result: 1/3 missing entries satisfied, 3 files analysed",
        "*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***",
    ]


def test_incorrect_files_get_one_line_per_target() -> None:
    entries = [
        make_missing("two/b.bin", B, incorrect=True),
        make_missing("a.bin", A, incorrect=True),
        make_missing("two/b.bin", C, incorrect=True),
    ]
    stream = io.StringIO()

    ConsoleRenderer(stream, {}).incorrect(entries)

    assert stream.getvalue().splitlines() == [
        "INCORRECT: a.bin is on the device with a wrong MD5, and was kept",
        "INCORRECT: two/b.bin is on the device with a wrong MD5, and was kept",
    ]


def test_incorrect_label_is_painted_red() -> None:
    stream = io.StringIO()

    ConsoleRenderer(stream, {"FORCE_COLOR": "1"}).incorrect(
        [make_missing("a.bin", A, incorrect=True)]
    )

    assert stream.getvalue().startswith("\033[91mINCORRECT:\033[0m a.bin")


def test_a_local_file_that_fits_an_incorrect_target_says_so() -> None:
    valid, junk = make_local_file("valid.bin", B), make_local_file("x", C)
    wrong = make_missing("two/b.bin", B, incorrect=True)
    plan = Plan(unmatched=(valid, junk), incorrect=(wrong,))

    assert rendered(RunResult(plan=plan)) == [
        "valid.bin: valid for two/b.bin, which is incorrect on the device, kept",
        "x: no match, kept",
        "Final result: 0/0 missing entries satisfied, 2 files analysed",
    ]


def test_a_dry_run_says_what_would_happen() -> None:
    planned = upload(make_local_file("copy.bin", A), "a.bin")
    plan = Plan(uploads=(planned,), still_missing=(make_missing("b.bin", B),))

    assert rendered(RunResult(plan=plan, skipped=(planned,), dry_run=True)) == [
        "copy.bin: would copy -> a.bin",
        "Dry run: 1/2 missing entries would be satisfied, 1 files analysed",
    ]


def test_names_without_color_have_no_escape_codes() -> None:
    first = upload(make_local_file("copy.bin", A), "a.bin")

    assert "\033" not in "".join(
        rendered(RunResult(plan=Plan(uploads=(first,)), completed=(first,)))
    )


@pytest.fixture
def clean_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger("beck")
    saved, level = list(logger.handlers), logger.level
    logger.handlers.clear()
    yield logger
    logger.handlers[:] = saved
    logger.setLevel(level)


def test_logs_go_to_stderr_not_stdout(
    clean_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging().warning("a diagnostic")

    captured = capsys.readouterr()
    assert "a diagnostic" in captured.err
    assert captured.out == ""


def test_debug_is_hidden_by_default(
    clean_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging().debug("a detail")

    assert capsys.readouterr().err == ""


def test_configuring_twice_does_not_repeat_each_line(
    clean_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging()
    configure_logging(logging.DEBUG).debug("once")

    assert capsys.readouterr().err.count("once") == 1
