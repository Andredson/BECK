"""How BECK shows results: for people in ``console``, and for machines in ``json``.

Output can't change what a run does, or its exit code (DEC-62). So what's written to stdout or
stderr goes through ``print_safely``, and ``cli.main`` ends with ``finish_output``.
"""

import contextlib
import logging
import os
import re
import sys
from typing import TextIO

from beck.models import Plan, PlannedUpload, RunResult

LOGGER_NAME = "beck"

# What can act on a terminal or change how a line reads: control characters, the controls for the
# direction of text, and how Python holds a byte of a file name that isn't valid UTF-8.
UNSAFE_ON_A_TERMINAL = re.compile("[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\udc80-\udcff]")


def _shown(match: re.Match[str]) -> str:
    code = ord(match[0])
    if 0xDC80 <= code <= 0xDCFF:  # the byte that was in the name: 0xff is U+DCFF
        return f"\\x{code - 0xDC00:02x}"
    return f"\\x{code:02x}" if code <= 0xFF else f"\\u{code:04x}"


def escaped_for_terminal(text: str) -> str:
    """Text from outside BECK, safe to show: a name can be anything, and can't act on a terminal.

    ``--json`` doesn't need this, and keeps the exact name.
    """
    return UNSAFE_ON_A_TERMINAL.sub(_shown, text)


def _output_lost(stream: TextIO, error: OSError) -> None:
    """Nobody can read this stream any more, so stop writing to it and carry on.

    A closed pipe is silent, because the reader chose to stop. Nobody chose anything else, such as a
    full disk, so that gets a line on stderr.
    """
    # Its descriptor becomes /dev/null, so that what's buffered can't fail again, even at exit.
    with contextlib.suppress(OSError):  # a stream that isn't a real file has no descriptor
        descriptor = stream.fileno()
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, descriptor)
        os.close(devnull)
    if not isinstance(error, BrokenPipeError):
        logging.getLogger(LOGGER_NAME).warning(
            "BECK's output couldn't be written, so it's lost: %s. The run carries on.",
            error.strerror,
        )


def print_safely(text: str, stream: TextIO | None) -> None:
    """Print to a stream that may be closed or failing. Python's stream is None if it's closed."""
    if stream is None:  # print(file=None) would write to stdout, even when asked for stderr
        return
    try:
        print(text, file=stream)
    except OSError as error:
        _output_lost(stream, error)


def finish_output() -> None:
    """Write out what's buffered, or else Python does at exit, and turns a failure into exit 120."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.flush()
            except OSError as error:
                _output_lost(stream, error)


def distinct_targets(plan: Plan) -> int:
    """How many targets the run set out to fill. One listed in several systems counts once."""
    return len({u.target for u in plan.uploads} | {e.target for e in plan.still_missing})


def upload_errors(result: RunResult) -> dict[str, str]:
    """What went wrong on the target, by target. A failed delete is about a local file instead,
    and that file can have the same name as a target.
    """
    return {e.item: e.message for e in result.errors if e.code != "delete_failed"}


def upload_status(upload: PlannedUpload, result: RunResult) -> str:
    """What happened to an upload. People and machines must be told the same, so both use this.

    These are the values of ``uploads[].status`` in the JSON output, a public contract.
    """
    if upload in result.kept:
        return "kept"
    if upload in result.completed:
        return "replaced" if upload in result.replaced else "uploaded"
    if upload.target.as_posix() in upload_errors(result):
        return "failed"
    return "planned" if result.dry_run else "skipped"


def extension_warning(upload: PlannedUpload) -> str:
    source = upload.source.relative.as_posix()
    return (
        f"{source} has a different extension from {upload.target}. The MD5 matches, but an "
        "emulator may not be able to read it."
    )
