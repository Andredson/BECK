"""The console renderer: when to use color, and what each outcome looks like."""

import ctypes
import io
import json
import logging
import os
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from beck import cli
from beck.errors import TransportError
from beck.frontends.recalbox import RecalboxAdapter
from beck.models import (
    Duplicate,
    ItemError,
    LocalFile,
    MissingBios,
    Plan,
    PlannedUpload,
    RunResult,
    Unreadable,
)
from beck.output import console, escaped_for_terminal, upload_status
from beck.output.console import ConsoleRenderer, configure_logging, enable_windows_ansi, wants_color
from beck.output.json import JsonRenderer
from beck.transports.local import LocalTransport
from tests.factories import (
    make_bios_file,
    make_local_file,
    make_missing,
    make_report_text,
    settings_text,
)
from tests.fakes import FakeSMBServer, install_fake_smb

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


def test_a_file_already_on_the_device_is_shown_as_kept_with_a_hint() -> None:
    kept = upload(make_local_file("a.bin", A), "x/a.bin")
    copied = upload(make_local_file("b.bin", B), "y/b.bin")
    plan = Plan(uploads=(kept, copied))

    assert rendered(RunResult(plan=plan, completed=(copied,), kept=(kept,))) == [
        "FOUND: b.bin -> y/b.bin",
        "a.bin: already on the device, kept -> x/a.bin",
        "b.bin: copied -> y/b.bin",
        "1 files were already on the device, and were kept. If the report is out of date, generate "
        "a new one. To replace them, use --overwrite.",
        "Final result: 1/2 missing entries satisfied, 2 files analysed",
        "*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***",
    ]


def test_a_replaced_file_says_replaced() -> None:
    swapped = upload(make_local_file("a.bin", A), "x/a.bin")
    plan = Plan(uploads=(swapped,))

    lines = rendered(RunResult(plan=plan, completed=(swapped,), replaced=(swapped,)))

    assert "a.bin: replaced -> x/a.bin" in lines


def test_a_replacement_that_failed_says_failed() -> None:
    swapped = upload(make_local_file("a.bin", A), "x/a.bin")
    plan = Plan(uploads=(swapped,))
    result = RunResult(plan=plan, errors=(ItemError(item="x/a.bin", message="boom"),))

    assert "a.bin: failed -> x/a.bin" in rendered(result)


def test_a_dry_run_says_what_it_would_replace_and_keep() -> None:
    new = upload(make_local_file("new.bin", A), "new.bin")
    swapped = upload(make_local_file("swap.bin", B), "swap.bin")
    kept = upload(make_local_file("kept.bin", C), "kept.bin")
    plan = Plan(uploads=(new, swapped, kept))
    result = RunResult(
        plan=plan, skipped=(new, swapped), kept=(kept,), replaced=(swapped,), dry_run=True
    )

    lines = rendered(result)

    assert "new.bin: would copy -> new.bin" in lines
    assert "swap.bin: would replace -> swap.bin" in lines
    assert "kept.bin: already on the device, kept -> kept.bin" in lines


def test_deleted_files_are_listed_and_counted() -> None:
    moved = upload(make_local_file("moved.bin", A), "x/moved.bin")
    junk = make_local_file("junk.bin", B)
    plan = Plan(uploads=(moved,), unmatched=(junk,))
    result = RunResult(plan=plan, completed=(moved,), deleted=(moved.source, junk))

    assert rendered(result) == [
        "FOUND: moved.bin -> x/moved.bin",
        "junk.bin: no match, deleted",
        "moved.bin: copied -> x/moved.bin",
        "moved.bin: deleted",
        "Final result: 1/1 missing entries satisfied, 2 files analysed",
        "Deleted 2 local files.",
        "*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***",
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


EXTENSION_WARNING = (
    "Warning: neocd.bin has a different extension from neocdz.zip. "
    "The MD5 matches, but an emulator may not be able to read it."
)


def test_an_extension_change_is_warned_about_below_its_upload() -> None:
    same = upload(make_local_file("neocd.bin", A), "neocd/neocd.bin")
    changed = upload(make_local_file("neocd.bin", A), "neocdz.zip")
    plan = Plan(uploads=(same, changed))
    result = RunResult(plan=plan, completed=(same, changed), extension_changes=(changed,))

    assert rendered(result)[2:5] == [
        "neocd.bin: copied -> neocd/neocd.bin",
        "neocd.bin: copied -> neocdz.zip",
        EXTENSION_WARNING,
    ]


def test_a_dry_run_warns_about_an_extension_change_too() -> None:
    changed = upload(make_local_file("neocd.bin", A), "neocdz.zip")
    plan = Plan(uploads=(changed,))
    result = RunResult(plan=plan, skipped=(changed,), extension_changes=(changed,), dry_run=True)

    assert rendered(result)[:2] == ["neocd.bin: would copy -> neocdz.zip", EXTENSION_WARNING]


def test_no_extension_warning_without_an_extension_change() -> None:
    planned = upload(make_local_file("neocd.bin", A), "neocdz.zip")
    result = RunResult(plan=Plan(uploads=(planned,)), completed=(planned,))

    assert EXTENSION_WARNING not in rendered(result)


def test_the_extension_warning_is_yellow_when_colored() -> None:
    changed = upload(make_local_file("neocd.bin", A), "neocdz.zip")
    result = RunResult(
        plan=Plan(uploads=(changed,)), completed=(changed,), extension_changes=(changed,)
    )

    assert f"\033[93mWarning\033[0m{EXTENSION_WARNING.removeprefix('Warning')}" in rendered(
        result, color=True
    )


# What a stream can't encode (D18), and failed checks in a dry run (D19)

BAD_NAME = os.fsdecode(b"bad-\xff.bin")
BAD_NAME_SHOWN = "bad-\\xff.bin"


def strict_stream(encoding: str) -> tuple[io.TextIOWrapper, io.BytesIO]:
    """A stream like a real stdout: it raises UnicodeEncodeError on what it can't encode."""
    raw = io.BytesIO()
    return io.TextIOWrapper(raw, encoding=encoding, errors="strict", newline="\n"), raw


def rendered_on(encoding: str, result: RunResult) -> str:
    stream, raw = strict_stream(encoding)
    ConsoleRenderer(stream, {}).result(result)
    stream.flush()
    return raw.getvalue().decode(encoding)


def unmatched_file_run(name: str) -> RunResult:
    return RunResult(plan=Plan(unmatched=(make_local_file(name, A),)))


def test_a_name_that_is_not_valid_utf8_is_shown_escaped() -> None:
    output = rendered_on("utf-8", unmatched_file_run(BAD_NAME))

    assert f"{BAD_NAME_SHOWN}: no match, kept\n" in output
    assert "Final result:" in output


def test_a_name_that_is_not_valid_utf8_is_escaped_with_no_encoding_too() -> None:
    assert rendered(unmatched_file_run(BAD_NAME))[0] == f"{BAD_NAME_SHOWN}: no match, kept"


@pytest.mark.parametrize(
    ("encoding", "name", "shown"),
    [
        ("ascii", "é.bin", "\\xe9.bin"),
        ("ascii", "日本.bin", "\\u65e5\\u672c.bin"),
        ("ascii", BAD_NAME, BAD_NAME_SHOWN),
        ("utf-8", os.fsdecode(b"low-\x80.bin"), "low-\\x80.bin"),
        ("latin-1", "é.bin", "é.bin"),
        ("latin-1", "日本.bin", "\\u65e5\\u672c.bin"),
        ("cp1252", "é.bin", "é.bin"),
        ("utf-8", "é.bin", "é.bin"),
        ("utf-8", "日本.bin", "日本.bin"),
        ("utf-8", "a\ud800.bin", "a\\ud800.bin"),
    ],
)
def test_a_stream_shows_what_it_can_encode_and_escapes_the_rest(
    encoding: str, name: str, shown: str
) -> None:
    assert f"{shown}: no match, kept\n" in rendered_on(encoding, unmatched_file_run(name))


def test_a_real_backslash_in_a_name_is_left_as_it_is() -> None:
    assert "a\\xff.bin: no match, kept\n" in rendered_on("utf-8", unmatched_file_run("a\\xff.bin"))


def test_every_kind_of_line_survives_a_stream_that_cannot_encode() -> None:
    name, other = "é.bin", "ñ.bin"
    moved = make_local_file(name, A)
    upload_one = PlannedUpload(moved, PurePosixPath("ü/ß.zip"), make_missing("ü/ß.zip", A))
    plan = Plan(
        uploads=(upload_one,),
        duplicates=(Duplicate(make_local_file(other, A), moved),),
        already_filled=(make_local_file("ç.bin", B),),
        unmatched=(make_local_file("ø.bin", C),),
        incorrect=(make_missing("ÿ.bin", C, incorrect=True, current_md5=D),),
    )
    result = RunResult(
        plan=plan,
        completed=(upload_one,),
        errors=(ItemError(item="ü/ß.zip", message="couldn't copy é.bin"),),
        deleted=(moved,),
        extension_changes=(upload_one,),
    )
    stream, raw = strict_stream("ascii")
    renderer = ConsoleRenderer(stream, {})

    renderer.result(result)
    renderer.error("the folder é doesn't exist")
    renderer.no_files(Path("é"))
    renderer.unreadable((Unreadable(PurePosixPath("é.bin"), "broken symlink"),))
    renderer.incorrect([make_missing("é.bin", A, incorrect=True)])
    renderer.report([make_missing("ü/é.bin", A)])

    stream.flush()
    output = raw.getvalue().decode("ascii")
    assert "\\xe9.bin: copied -> \\xfc/\\xdf.zip" in output
    assert "\\xf1.bin: duplicate of \\xe9.bin, kept" in output
    assert "Warning: \\xe9.bin has a different extension from \\xfc/\\xdf.zip" in output
    assert "\\xfc/\n  \\xe9.bin (required)" in output
    assert "Final result:" in output


@pytest.mark.parametrize(
    ("encoding", "name", "shown"),
    [("utf-8", BAD_NAME, BAD_NAME_SHOWN), ("ascii", "é.bin", "\\xe9.bin")],
)
def test_the_prompt_shows_a_name_it_cannot_encode(
    encoding: str, name: str, shown: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream, raw = strict_stream(encoding)
    monkeypatch.setattr(sys, "stderr", stream)
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))
    preview = RunResult(plan=Plan(), deleted=(make_local_file(name, A),), dry_run=True)

    assert ConsoleRenderer(io.StringIO(), {}).confirm_deletion(preview) is True

    stream.flush()
    assert f"  {shown}\n" in raw.getvalue().decode(encoding)


def test_a_dry_run_with_a_failed_check_says_failed() -> None:
    planned = upload(make_local_file("copy.bin", A), "a.bin")
    failure = ItemError(item="a.bin", message="the network went away")
    result = RunResult(plan=Plan(uploads=(planned,)), errors=(failure,), dry_run=True)

    lines = rendered(result)

    assert lines[0] == "copy.bin: failed -> a.bin"
    assert not any("would" in line and "copy.bin" in line for line in lines)
    assert "Error: the network went away" in lines


@pytest.mark.parametrize(
    ("status", "words", "fields"),
    [
        ("planned", "would copy", {"skipped": True, "dry_run": True}),
        ("planned", "would replace", {"skipped": True, "replaced": True, "dry_run": True}),
        ("uploaded", "copied", {"completed": True}),
        ("replaced", "replaced", {"completed": True, "replaced": True}),
        ("kept", "already on the device, kept", {"kept": True}),
        ("kept", "already on the device, kept", {"kept": True, "dry_run": True}),
        ("failed", "failed", {"errors": True}),
        ("failed", "failed", {"errors": True, "dry_run": True}),
        ("skipped", "skipped", {"skipped": True}),
    ],
)
def test_people_and_machines_are_told_the_same_about_an_upload(
    status: str, words: str, fields: dict[str, bool]
) -> None:
    """One function decides, so that D19 can't come back: the two outputs used to disagree."""
    planned = upload(make_local_file("copy.bin", A), "a.bin")
    planned_only = (planned,)
    failure = ItemError(item="a.bin", message="it went wrong")
    result = RunResult(
        plan=Plan(uploads=planned_only),
        completed=planned_only if fields.get("completed") else (),
        skipped=planned_only if fields.get("skipped") else (),
        kept=planned_only if fields.get("kept") else (),
        replaced=planned_only if fields.get("replaced") else (),
        errors=(failure,) if fields.get("errors") else (),
        dry_run=fields.get("dry_run", False),
    )

    assert upload_status(planned, result) == status
    assert f"copy.bin: {words} -> a.bin" in rendered(result)


def test_a_failed_delete_does_not_fail_an_upload_with_the_same_name() -> None:
    waiting = upload(make_local_file("z.bin", A), "b/a.bin")
    failure = ItemError(item="b/a.bin", message="can't delete", code="delete_failed")
    result = RunResult(plan=Plan(uploads=(waiting,)), errors=(failure,))

    assert upload_status(waiting, result) == "skipped"
    assert "z.bin: skipped -> b/a.bin" in rendered(result)


# -v and -q, on real runs through the command

SENTINEL = "beck-test-password-sentinel"
ACCOUNT_USER = "beck-test-user-sentinel"
ACCOUNT = settings_text("smb://beck-test-server/bios", ACCOUNT_USER)


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    source, device = tmp_path / "source", tmp_path / "device"
    source.mkdir()
    device.mkdir()
    return source, device


@pytest.fixture
def account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder with settings for a user whose password must never appear anywhere."""
    folder = tmp_path / "app"
    (folder / "bios").mkdir(parents=True)
    (folder / "settings.toml").write_text(ACCOUNT, encoding="utf-8")
    (folder / "settings.toml").chmod(0o600)
    monkeypatch.setenv("BECK_CONFIG", str(folder / "settings.toml"))
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)
    return folder


def put_report(device: Path, *entries: MissingBios) -> None:
    (device / "missing_bios_report.txt").write_text(
        make_report_text(entries), encoding="utf-8", newline=""
    )


def check(folders: tuple[Path, Path], *flags: str) -> list[str]:
    source, device = folders
    return ["check", "--source", str(source), "--target-dir", str(device), *flags]


def a_normal_run(folders: tuple[Path, Path]) -> LocalFile:
    source, device = folders
    file = make_bios_file(source, "good.bin")
    make_bios_file(source, "junk.bin")
    (source / "broken").symlink_to(source / "nowhere")
    put_report(device, make_missing("good.bin", file.md5), make_missing("gone.bin", A))
    return file


@pytest.mark.parametrize("arguments", [["-v", "check"], ["check", "-v"]], ids=["before", "after"])
def test_v_adds_debug_logs_on_stderr_and_leaves_stdout_alone(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str], arguments: list[str]
) -> None:
    source, device = folders
    a_normal_run(folders)
    plain = check(folders, "--dry-run")
    assert cli.main(plain) == 0
    normal = capsys.readouterr()
    assert normal.err == ""
    target = ["--source", str(source), "--target-dir", str(device), "--dry-run"]

    assert cli.main([*arguments, *target]) == 0

    out = capsys.readouterr()
    assert out.out == normal.out
    for detail in (
        device.as_uri(),
        "Report: 2 entries",
        "Scanned",
        "2 files",
        "1 can't be read",
        "Plan: 1 uploads",
        "good.bin -> good.bin",
        "Ran in",
    ):
        assert detail in out.err


def test_v_shows_each_step_of_a_connection(
    account: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    server = install_fake_smb(monkeypatch)
    data = make_bios_file(account / "bios", "good.bin")
    server.files[("bios", "missing_bios_report.txt")] = make_report_text(
        [make_missing("ps1/good.bin", data.md5)]
    ).encode()

    assert cli.main(["-v", "check"], base_dir=account) == 0

    err = capsys.readouterr().err
    for step in (
        "Connecting to beck-test-server:445",
        "Connected",
        "Reading missing_bios_report.txt",
        "Creating folder ps1",
        "Uploaded ps1/good.bin",
    ):
        assert step in err


def test_v_shows_each_step_on_a_folder(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_normal_run(folders)

    assert cli.main(["-v", *check(folders)]) == 0

    err = capsys.readouterr().err
    assert "Using folder" in err
    assert "Copied good.bin" in err


def test_no_flag_logs_no_details(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_normal_run(folders)

    assert cli.main(check(folders)) == 0

    assert capsys.readouterr().err == ""


def test_v_leaves_the_logs_of_other_libraries_alone(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """pysmb's own debug logs show what crosses the network, which isn't for a log."""
    a_normal_run(folders)

    assert cli.main(["-v", *check(folders)]) == 0

    assert not logging.getLogger("SMB.SMBConnection").isEnabledFor(logging.DEBUG)
    assert not logging.getLogger().isEnabledFor(logging.DEBUG)


def verbose_success(server: FakeSMBServer, account: Path) -> list[str]:
    data = make_bios_file(account / "bios", "good.bin")
    server.files[("bios", "missing_bios_report.txt")] = make_report_text(
        [make_missing("ps1/good.bin", data.md5), make_missing("gone.bin", A)]
    ).encode()
    return ["check"]


def verbose_refused_login(server: FakeSMBServer, account: Path) -> list[str]:
    server.login_succeeds = False
    return ["check"]


def verbose_report(server: FakeSMBServer, account: Path) -> list[str]:
    server.files[("bios", "missing_bios_report.txt")] = make_report_text(
        [make_missing("gone.bin", A)]
    ).encode()
    return ["report"]


def verbose_no_report(server: FakeSMBServer, account: Path) -> list[str]:
    return ["check"]


def verbose_config_it_cannot_parse(server: FakeSMBServer, account: Path) -> list[str]:
    (account / "settings.toml").write_text(f'{ACCOUNT}broken = "{SENTINEL}', encoding="utf-8")
    return ["check"]


def verbose_password_that_is_not_text(server: FakeSMBServer, account: Path) -> list[str]:
    config = f'{ACCOUNT}password = ["{SENTINEL}"]\n'
    (account / "settings.toml").write_text(config, encoding="utf-8")
    return ["check"]


def verbose_url_with_a_password(server: FakeSMBServer, account: Path) -> list[str]:
    return ["check", "--target", f"smb://{ACCOUNT_USER}:{SENTINEL}@beck-test-server/bios"]


def verbose_url_with_a_user(server: FakeSMBServer, account: Path) -> list[str]:
    server.files[("bios", "missing_bios_report.txt")] = make_report_text([]).encode()
    return ["check", "--target", f"smb://{ACCOUNT_USER}@beck-test-server/bios"]


@pytest.mark.parametrize(
    "scenario",
    [
        verbose_success,
        verbose_refused_login,
        verbose_report,
        verbose_no_report,
        verbose_config_it_cannot_parse,
        verbose_password_that_is_not_text,
        verbose_url_with_a_password,
        verbose_url_with_a_user,
    ],
)
@pytest.mark.parametrize("mode", [[], ["--json"]], ids=["human", "json"])
def test_v_never_shows_the_password_or_the_user_name(
    account: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    scenario: Callable[[FakeSMBServer, Path], list[str]],
    mode: list[str],
) -> None:
    server = install_fake_smb(monkeypatch)
    arguments = scenario(server, account)

    cli.main(["-v", *mode, *arguments], base_dir=account)

    out = capsys.readouterr()
    assert SENTINEL not in out.out + out.err
    assert ACCOUNT_USER not in out.out + out.err
    assert server.connections or "Connecting" not in out.err


def test_v_says_how_it_logs_in_without_saying_who(
    account: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    server = install_fake_smb(monkeypatch)
    verbose_success(server, account)

    assert cli.main(["-v", "check"], base_dir=account) == 0

    assert "with a user name" in capsys.readouterr().err


def test_v_says_when_it_logs_in_as_a_guest(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server = install_fake_smb(monkeypatch)
    server.files[("bios", "missing_bios_report.txt")] = make_report_text([]).encode()
    url = "smb://beck-test-server/bios"

    assert cli.main(["-v", "report", "--target", url], base_dir=tmp_path) == 0

    assert "as a guest" in capsys.readouterr().err


def test_v_with_json_keeps_stdout_a_document(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_normal_run(folders)

    assert cli.main(["-v", "--json", *check(folders)]) == 0

    out = capsys.readouterr()
    assert json.loads(out.out)["ok"] is True
    assert "Plan: 1 uploads" in out.err


def test_q_prints_only_the_final_summary(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_normal_run(folders)

    assert cli.main(["-q", *check(folders)]) == 0

    out = capsys.readouterr()
    assert out.out.splitlines() == [
        "Final result: 1/2 missing entries satisfied, 2 files analysed",
        "*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***",
    ]
    assert out.err == ""


def test_q_works_after_the_command_too(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_normal_run(folders)

    assert cli.main([*check(folders), "-q"]) == 0

    assert capsys.readouterr().out.startswith("Final result:")


def test_q_a_dry_run_prints_its_summary(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_normal_run(folders)

    assert cli.main(["-q", *check(folders, "--dry-run")]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "Dry run: 1/2 missing entries would be satisfied, 2 files analysed"
    ]


def test_q_still_shows_errors(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    a_normal_run(folders)

    def refuse(*_args: Any, **_kwargs: Any) -> int:
        raise TransportError("the disk is full")

    monkeypatch.setattr(LocalTransport, "upload", refuse)

    assert cli.main(["-q", *check(folders)]) == 3

    assert capsys.readouterr().out.splitlines() == [
        "Error: the disk is full",
        "Final result: 0/2 missing entries satisfied, 2 files analysed",
    ]


def test_q_still_shows_an_error_that_stops_the_run(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["-q", *check(folders)]) == 4

    assert capsys.readouterr().out.startswith("Error: missing_bios_report.txt not found")


@pytest.mark.parametrize(
    ("flags", "line"),
    [
        (("--move", "--yes"), "good.bin: deleted"),
        (("--move", "--dry-run"), "good.bin: would be deleted"),
    ],
    ids=["run", "dry-run"],
)
def test_q_never_hides_a_deletion(
    folders: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    flags: tuple[str, ...],
    line: str,
) -> None:
    a_normal_run(folders)

    assert cli.main(["-q", *check(folders, *flags)]) == 0

    assert capsys.readouterr().out.splitlines()[0] == line


def test_q_a_run_with_nothing_missing_still_says_so(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    put_report(folders[1])

    assert cli.main(["-q", *check(folders)]) == 0

    assert capsys.readouterr().out.splitlines() == ["No missing bios were found in your RECALBOX!"]


def test_q_a_run_with_no_local_files_still_says_so(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, device = folders
    put_report(device, make_missing("gone.bin", A))

    assert cli.main(["-q", *check(folders)]) == 0

    assert capsys.readouterr().out.splitlines() == [f"No BIOS files found in {source}"]


def test_q_still_says_why_fail_if_missing_failed(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    device = folders[1]
    make_bios_file(device, "bad.bin")
    put_report(
        device,
        make_missing("gone.bin", A),
        make_missing("bad.bin", B, incorrect=True),
        make_missing("spare.bin", C, required=False),
    )

    assert cli.main(["-q", *check(folders, "--fail-if-missing")]) == 5

    assert capsys.readouterr().out.splitlines()[-3:] == [
        "MISSING: gone.bin",
        "INCORRECT: bad.bin",
        "Required files still missing or incorrect: 2. Exit code 5, because of --fail-if-missing.",
    ]


def test_q_does_not_shorten_a_report(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The list is what the command is for."""
    device = folders[1]
    put_report(device, make_missing("ps1/gone.bin", A))
    arguments = ["report", "--target-dir", str(device)]
    assert cli.main(arguments) == 0
    normal = capsys.readouterr().out

    assert cli.main(["-q", *arguments]) == 0

    assert capsys.readouterr().out == normal
    assert "gone.bin" in normal


def test_q_still_asks_and_lists_what_it_would_delete(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    file = make_local_file("good.bin", A)
    preview = RunResult(plan=Plan(), deleted=(file,))
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))

    assert ConsoleRenderer(io.StringIO(), {}, quiet=True).confirm_deletion(preview) is True

    err = capsys.readouterr().err
    assert "good.bin" in err
    assert "Delete 1 files?" in err


def test_q_hides_the_hint_about_running_with_no_command(
    account: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    server = install_fake_smb(monkeypatch)
    server.files[("bios", "missing_bios_report.txt")] = make_report_text([]).encode()

    assert cli.main(["-q"], base_dir=account) == 0

    assert capsys.readouterr().err == ""


def test_q_does_not_change_a_json_document(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, device = folders
    make_bios_file(source, "junk.bin")
    put_report(device, make_missing("gone.bin", A))
    assert cli.main(["--json", *check(folders)]) == 0
    normal = capsys.readouterr().out

    assert cli.main(["--json", "-q", *check(folders)]) == 0

    assert capsys.readouterr().out == normal


@pytest.mark.parametrize(
    "arguments",
    [["-v", "-q", "check"], ["-vq", "check"], ["-v", "check", "-q"], ["check", "-q", "-v"]],
)
def test_v_and_q_together_are_refused(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(arguments)

    assert stop.value.code == 2
    assert "-v and -q" in capsys.readouterr().err


def test_v_and_q_together_with_json_are_a_rejected_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--json", "-v", "check", "-q"]) == 2

    document = json.loads(capsys.readouterr().out)
    assert document["command"] is None
    assert "-v and -q" in document["errors"][0]["message"]


# The counter while hashing


class FailingTerminal(Terminal):
    def write(self, text: str) -> int:
        raise OSError(5, "Input/output error")


def test_the_counter_shows_on_a_terminal_and_clears_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = Terminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    renderer = ConsoleRenderer(io.StringIO(), {})

    renderer.hashing(1)
    renderer.hashing(2)
    shown = terminal.getvalue()
    renderer.hashing_done()

    assert shown == "\rHashing files: 1\rHashing files: 2"
    width = len("Hashing files: 2")
    assert terminal.getvalue() == f"{shown}\r{' ' * width}\r"


def test_the_counter_stays_off_a_stderr_that_is_no_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    renderer = ConsoleRenderer(io.StringIO(), {})

    renderer.hashing(1)
    renderer.hashing_done()

    assert stream.getvalue() == ""


@pytest.mark.parametrize("options", [{"quiet": True}, {"progress": False}], ids=["-q", "-v"])
def test_the_counter_stays_off_when_asked_for_less_or_for_logs(
    monkeypatch: pytest.MonkeyPatch, options: dict[str, bool]
) -> None:
    terminal = Terminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    renderer = ConsoleRenderer(io.StringIO(), {}, **options)

    renderer.hashing(1)
    renderer.hashing_done()

    assert terminal.getvalue() == ""


def test_nothing_to_clear_if_nothing_was_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = Terminal()
    monkeypatch.setattr(sys, "stderr", terminal)

    ConsoleRenderer(io.StringIO(), {}).hashing_done()

    assert terminal.getvalue() == ""


def test_the_counter_with_stderr_closed_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stderr", None)
    renderer = ConsoleRenderer(io.StringIO(), {})

    renderer.hashing(1)
    renderer.hashing_done()


def test_a_counter_that_cannot_be_written_stops_and_the_run_carries_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = FailingTerminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    renderer = ConsoleRenderer(io.StringIO(), {})

    renderer.hashing(1)
    renderer.hashing(2)
    renderer.hashing_done()

    assert renderer.progress is False


def test_json_shows_no_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = Terminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    renderer = JsonRenderer("check", frontend="recalbox", dry_run=False, stream=io.StringIO())

    renderer.hashing(1)
    renderer.hashing_done()

    assert terminal.getvalue() == ""


def test_a_run_on_a_terminal_counts_then_clears_before_it_prints_the_rest(
    folders: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a_normal_run(folders)
    terminal = Terminal()
    monkeypatch.setattr(sys, "stderr", terminal)

    assert cli.main(check(folders)) == 0

    width = len("Hashing files: 3")
    assert terminal.getvalue() == (
        f"\rHashing files: 1\rHashing files: 2\rHashing files: 3\r{' ' * width}\r"
    )


def test_v_on_a_terminal_has_logs_instead_of_a_counter(
    folders: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a_normal_run(folders)
    terminal = Terminal()
    monkeypatch.setattr(sys, "stderr", terminal)

    assert cli.main(["-v", *check(folders)]) == 0

    shown = terminal.getvalue()
    assert "Plan: 1 uploads" in shown
    assert "Hashing" not in shown


def test_v_says_how_long_the_run_has_taken_on_every_line(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    a_normal_run(folders)

    assert cli.main(["-v", *check(folders)]) == 0

    lines = capsys.readouterr().err.splitlines()
    assert lines
    assert all(re.match(r" *\d+ ms  \S", line) for line in lines), lines


def test_a_warning_without_v_is_only_its_message(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging().warning("a diagnostic")

    assert capsys.readouterr().err == "a diagnostic\n"


def test_q_with_no_command_is_quiet_too(
    account: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    server = install_fake_smb(monkeypatch)
    make_bios_file(account / "bios", "junk.bin")
    server.files[("bios", "missing_bios_report.txt")] = make_report_text(
        [make_missing("gone.bin", A)]
    ).encode()

    assert cli.main(["-q"], base_dir=account) == 0

    assert capsys.readouterr().out.splitlines() == [
        "Final result: 0/1 missing entries satisfied, 1 files analysed"
    ]


def test_q_hides_what_is_neither_an_error_nor_the_summary(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, device = folders
    kept = make_bios_file(source, "kept.bin")
    make_bios_file(device, "kept.bin")
    changes = make_bios_file(source, "changes.bin")
    make_bios_file(device, "bad.bin")
    put_report(
        device,
        make_missing("kept.bin", kept.md5),
        make_missing("changes.zip", changes.md5),
        make_missing("bad.bin", B, incorrect=True),
    )

    assert cli.main(["-q", *check(folders)]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "Final result: 1/2 missing entries satisfied, 2 files analysed",
        "*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***",
    ]


def test_without_q_an_incorrect_file_has_only_its_usual_line(
    folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    device = folders[1]
    make_bios_file(device, "bad.bin")
    put_report(device, make_missing("bad.bin", B, incorrect=True))

    assert cli.main([*check(folders, "--fail-if-missing")]) == 5

    lines = capsys.readouterr().out.splitlines()
    assert "INCORRECT: bad.bin is on the device with a wrong MD5, and was kept" in lines
    assert "INCORRECT: bad.bin" not in lines


# Control characters in names (D24): what comes from outside BECK reaches a terminal escaped

# Clears the screen, sets the title, rings the bell, uses a one-byte escape, moves the cursor back
# to overwrite the line, reverses the text after it, and more. A report can't hold a line break.
HOSTILE = "evil\x1b[2J\x1b]0;title\x07\x9b31m\r\t‮gnp.\x7f"
HOSTILE_SHOWN = "evil\\x1b[2J\\x1b]0;title\\x07\\x9b31m\\x0d\\x09\\u202egnp.\\x7f"
OWN_COLORS = re.compile(r"\x1b\[(?:0|91|92|93|94|35|36)m")
UNSAFE = re.compile("[\x00-\x09\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩\udc80-\udcff]")


@pytest.fixture
def colors(monkeypatch: pytest.MonkeyPatch) -> None:
    """With colors on, BECK's own codes must be the only escape sequences left."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")


def a_frontend_lets_through(
    monkeypatch: pytest.MonkeyPatch, device: Path, *entries: MissingBios
) -> None:
    """Reports refuse these names since 07.6. Showing them safely stays a separate defense."""
    put_report(device)
    monkeypatch.setattr(RecalboxAdapter, "parse_report", lambda _self, _text: list(entries))


def assert_safe(text: str) -> None:
    assert not UNSAFE.search(OWN_COLORS.sub("", text)), repr(text)
    assert "_Painted" not in text, "a colored part was put inside an f-string"


def shown_by(capsys: pytest.CaptureFixture[str]) -> str:
    """What reached stdout and stderr, which must both be safe."""
    out = capsys.readouterr()
    assert_safe(out.out)
    assert_safe(out.err)
    return OWN_COLORS.sub("", out.out + out.err)


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("plain.bin", "plain.bin"),
        ("ü/é-日本語-🎮.bin", "ü/é-日本語-🎮.bin"),
        ("a\nb", "a\\x0ab"),
        ("a\tb", "a\\x09b"),
        ("a\rb", "a\\x0db"),
        ("a\x00b", "a\\x00b"),
        ("a\x1bb", "a\\x1bb"),
        ("a\x1fb", "a\\x1fb"),
        ("a b", "a b"),
        ("a\x7fb", "a\\x7fb"),
        ("a\x80b", "a\\x80b"),
        ("a\x9fb", "a\\x9fb"),
        ("a\xa0b", "a\xa0b"),
        ("a‪b", "a\\u202ab"),
        ("a‮b", "a\\u202eb"),
        ("a⁦b", "a\\u2066b"),
        ("a⁩b", "a\\u2069b"),
        ("a⁥b", "a⁥b"),
        (os.fsdecode(b"a\xffb"), "a\\xffb"),
        (os.fsdecode(b"a\x80b"), "a\\x80b"),
    ],
)
def test_what_gets_escaped(raw: str, shown: str) -> None:
    assert escaped_for_terminal(raw) == shown


def test_a_hostile_name_shows_as_this() -> None:
    assert escaped_for_terminal(HOSTILE) == HOSTILE_SHOWN


def test_check_shows_local_names_escaped_in_every_outcome(
    folders: tuple[Path, Path], colors: None, capsys: pytest.CaptureFixture[str]
) -> None:
    source, device = folders
    good = make_bios_file(source, f"{HOSTILE}.bin")
    make_bios_file(source, f"z-{HOSTILE}-copy.bin", good.path.read_bytes())
    make_bios_file(source, f"junk-{HOSTILE}.bin")
    own = make_bios_file(source, "own.bin")
    other = make_bios_file(source, f"filled-{HOSTILE}.bin")
    fix = make_bios_file(source, f"fix-{HOSTILE}.bin")
    (source / f"broken-{HOSTILE}").symlink_to(source / "nowhere")
    make_bios_file(device, "bad.bin")
    put_report(
        device,
        make_missing("good.zip", good.md5),
        make_missing("own.bin", own.md5, other.md5),
        make_missing("bad.bin", fix.md5, incorrect=True),
    )

    assert cli.main(check(folders)) == 0

    shown = shown_by(capsys)
    for line in (
        f"{HOSTILE_SHOWN}.bin: copied -> good.zip",
        f"z-{HOSTILE_SHOWN}-copy.bin: duplicate of {HOSTILE_SHOWN}.bin, kept",
        f"junk-{HOSTILE_SHOWN}.bin: no match, kept",
        f"filled-{HOSTILE_SHOWN}.bin: target already filled, kept",
        f"fix-{HOSTILE_SHOWN}.bin: valid for bad.bin, which is incorrect on the device, kept",
        f"broken-{HOSTILE_SHOWN}: can't be read, skipped",
        f"Warning: {HOSTILE_SHOWN}.bin has a different extension from good.zip",
    ):
        assert line in shown


def test_check_shows_names_from_the_report_escaped(
    folders: tuple[Path, Path],
    colors: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, device = folders
    file = make_bios_file(source, "good.bin")
    make_bios_file(device, "x")
    a_frontend_lets_through(
        monkeypatch,
        device,
        make_missing(f"up-{HOSTILE}.bin", file.md5),
        make_missing(f"gone-{HOSTILE}.bin", A),
        make_missing(f"bad-{HOSTILE}.bin", B, incorrect=True),
    )

    assert cli.main(check(folders, "--fail-if-missing", "--dry-run")) == 5

    shown = shown_by(capsys)
    assert f"good.bin: would copy -> up-{HOSTILE_SHOWN}.bin" in shown
    assert f"MISSING: gone-{HOSTILE_SHOWN}.bin" in shown
    assert f"INCORRECT: bad-{HOSTILE_SHOWN}.bin is on the device" in shown


def test_a_real_upload_shows_the_name_from_the_report_escaped(
    folders: tuple[Path, Path],
    colors: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, device = folders
    file = make_bios_file(source, "good.bin")
    a_frontend_lets_through(monkeypatch, device, make_missing(f"up-{HOSTILE}.bin", file.md5))

    assert cli.main(check(folders)) == 0

    assert f"FOUND: up-{HOSTILE_SHOWN}.bin -> up-{HOSTILE_SHOWN}.bin" in shown_by(capsys)


@pytest.mark.parametrize(
    ("flags", "line"),
    [
        (("-q", "--move", "--yes"), "deleted"),
        (("-q", "--move", "--dry-run"), "would be deleted"),
        (("--move", "--yes"), "deleted"),
    ],
    ids=["quiet", "quiet-dry-run", "normal"],
)
def test_a_deletion_shows_the_name_escaped(
    folders: tuple[Path, Path],
    colors: None,
    capsys: pytest.CaptureFixture[str],
    flags: tuple[str, ...],
    line: str,
) -> None:
    source, device = folders
    file = make_bios_file(source, f"{HOSTILE}.bin")
    put_report(device, make_missing("good.bin", file.md5))

    assert cli.main(check(folders, *flags)) == 0

    assert f"{HOSTILE_SHOWN}.bin: {line}" in shown_by(capsys)


def test_quiet_shows_names_from_the_report_escaped(
    folders: tuple[Path, Path],
    colors: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = folders[1]
    make_bios_file(folders[0], "junk.bin")
    a_frontend_lets_through(
        monkeypatch,
        device,
        make_missing(f"gone-{HOSTILE}.bin", A),
        make_missing(f"bad-{HOSTILE}.bin", B, incorrect=True),
    )

    assert cli.main(["-q", *check(folders, "--fail-if-missing")]) == 5

    shown = shown_by(capsys)
    assert f"MISSING: gone-{HOSTILE_SHOWN}.bin" in shown
    assert f"INCORRECT: bad-{HOSTILE_SHOWN}.bin" in shown


def test_report_shows_names_escaped(
    folders: tuple[Path, Path],
    colors: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = folders[1]
    a_frontend_lets_through(
        monkeypatch,
        device,
        make_missing(f"ps1-{HOSTILE}/gone-{HOSTILE}.bin", A),
        make_missing(f"bad-{HOSTILE}.bin", B, incorrect=True),
    )

    assert cli.main(["report", "--target-dir", str(device)]) == 0

    shown = shown_by(capsys)
    assert f"ps1-{HOSTILE_SHOWN}/\n" in shown
    assert f"  gone-{HOSTILE_SHOWN}.bin (required)" in shown
    assert f"INCORRECT: bad-{HOSTILE_SHOWN}.bin (required)" in shown


def test_scan_keeps_one_line_per_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], colors: None
) -> None:
    make_bios_file(tmp_path, "new\nline.bin")
    make_bios_file(tmp_path, f"{HOSTILE}.bin")
    (tmp_path / "broken\nlink").symlink_to(tmp_path / "nowhere")

    assert cli.main(["scan", "--source", str(tmp_path)]) == 0

    lines = shown_by(capsys).splitlines()
    assert len(lines) == 4
    assert lines[0].endswith(f"  {HOSTILE_SHOWN}.bin")
    assert lines[1].endswith("  new\\x0aline.bin")
    assert lines[2].startswith("broken\\x0alink: can't be read")


def test_an_error_that_stops_a_run_shows_the_name_escaped(
    folders: tuple[Path, Path], colors: None, capsys: pytest.CaptureFixture[str]
) -> None:
    device = folders[1]
    (device / "missing_bios_report.txt").write_text(
        f"MISSING BIOS REPORT\n  MISSING REQUIRED BIOS: {HOSTILE}\n", encoding="utf-8"
    )

    assert cli.main(["report", "--target-dir", str(device)]) == 4

    assert f"Error: No Path line in report block: MISSING REQUIRED BIOS: {HOSTILE_SHOWN}" in (
        shown_by(capsys)
    )


def test_an_error_about_one_item_shows_the_name_escaped(
    folders: tuple[Path, Path],
    colors: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, device = folders
    file = make_bios_file(source, "good.bin")
    a_frontend_lets_through(monkeypatch, device, make_missing(f"up-{HOSTILE}.bin", file.md5))

    def refuse(_self: LocalTransport, _local: Path, remote: PurePosixPath) -> int:
        raise TransportError(f"Can't write {remote}")

    monkeypatch.setattr(LocalTransport, "upload", refuse)

    assert cli.main(check(folders)) == 3

    assert f"Error: Can't write up-{HOSTILE_SHOWN}.bin" in shown_by(capsys)


def test_a_folder_named_on_the_command_line_shows_escaped(
    tmp_path: Path, colors: None, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / f"folder-{HOSTILE}"
    folder.mkdir()

    assert cli.main(["scan", "--source", str(folder)]) == 0
    assert f"folder-{HOSTILE_SHOWN}" in shown_by(capsys)

    assert cli.main(["scan", "--source", f"{folder}-nope"]) == 2
    assert f"folder-{HOSTILE_SHOWN}-nope" in shown_by(capsys)


def test_a_rejected_command_line_shows_the_argument_escaped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(["check", HOSTILE])

    assert stop.value.code == 2
    assert HOSTILE_SHOWN in shown_by(capsys)


def test_v_logs_show_names_escaped(
    folders: tuple[Path, Path],
    colors: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, device = folders
    file = make_bios_file(source, f"{HOSTILE}.bin")
    a_frontend_lets_through(monkeypatch, device, make_missing(f"up-{HOSTILE}.bin", file.md5))

    assert cli.main(["-v", *check(folders)]) == 0

    out = capsys.readouterr()
    assert_safe(out.err)
    assert f"Plan: {HOSTILE_SHOWN}.bin -> up-{HOSTILE_SHOWN}.bin" in out.err
    assert f"Copied up-{HOSTILE_SHOWN}.bin" in out.err


def test_a_log_line_cannot_pretend_to_be_two(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging().warning("Using %s", "a\nb")

    assert capsys.readouterr().err == "Using a\\x0ab\n"


def test_a_traceback_keeps_its_lines_and_loses_only_what_is_unsafe(
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        raise RuntimeError(f"a bug with {HOSTILE}")
    except RuntimeError:
        configure_logging().exception("Unexpected error")

    err = capsys.readouterr().err
    assert_safe(err)
    assert err.startswith("Unexpected error\nTraceback (most recent call last):\n")
    assert f"RuntimeError: a bug with {HOSTILE_SHOWN}\n" in err


def test_the_prompt_shows_what_it_would_delete_escaped(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    preview = RunResult(plan=Plan(), deleted=(make_local_file(f"{HOSTILE}.bin", A),))
    monkeypatch.setattr(sys, "stdin", io.StringIO("n\n"))

    assert ConsoleRenderer(io.StringIO(), {}).confirm_deletion(preview) is False

    err = capsys.readouterr().err
    assert_safe(err)
    assert f"  {HOSTILE_SHOWN}.bin\n" in err


def test_a_prompt_cannot_list_a_file_as_if_it_were_two(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = "harmless.bin\n  also-harmless.bin"
    preview = RunResult(plan=Plan(), deleted=(make_local_file(fake, A),))
    monkeypatch.setattr(sys, "stdin", io.StringIO("n\n"))

    ConsoleRenderer(io.StringIO(), {}).confirm_deletion(preview)

    assert capsys.readouterr().err.splitlines() == [
        "  harmless.bin\\x0a  also-harmless.bin",
        "Delete 1 files? [y/N] ",
    ]


def test_json_keeps_the_exact_name(
    folders: tuple[Path, Path],
    colors: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, device = folders
    name = f"{HOSTILE}\n.bin"
    make_bios_file(source, name)
    a_frontend_lets_through(monkeypatch, device, make_missing(f"gone-{HOSTILE}.bin", A))

    assert cli.main(["--json", *check(folders)]) == 0

    out = capsys.readouterr().out
    assert_safe(out)
    document = json.loads(out)
    assert document["unmatched"][0]["path"] == name
    assert document["still_missing"][0]["target"] == f"gone-{HOSTILE}.bin"


def test_colors_still_go_on_around_escaped_text(
    tmp_path: Path, colors: None, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / f"empty{HOSTILE}"
    folder.mkdir()

    assert cli.main(["scan", "--source", str(folder)]) == 0

    out = capsys.readouterr().out
    assert out.startswith(console.CYAN)
    assert f"empty{HOSTILE_SHOWN}{console.RESET}\n" in out
