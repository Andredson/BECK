# SPDX-License-Identifier: GPL-3.0-only
"""--dry-run, --move, --clean-unmatched and --yes: nothing goes unless asked for and proven."""

import io
from pathlib import Path, PurePosixPath

import pytest

from beck import cli
from beck.errors import TransportError
from beck.executor import execute
from beck.hashing import scan
from beck.matcher import plan
from beck.transports.local import LocalTransport
from tests.factories import make_bios_file, make_missing, make_report_text, snapshot

C = "c" * 32


class Keyboard(io.StringIO):
    """Standard input on a terminal, with these lines typed."""

    def isatty(self) -> bool:
        return True


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "source"
    folder.mkdir()
    return folder


@pytest.fixture
def device(tmp_path: Path) -> Path:
    folder = tmp_path / "device"
    folder.mkdir()
    return folder


def put_report(device: Path, *entries: object) -> None:
    (device / "missing_bios_report.txt").write_text(
        make_report_text(entries),  # type: ignore[arg-type]
        encoding="utf-8",
        newline="",
    )


def beck(source: Path, device: Path, *flags: str) -> int:
    arguments = ["check", "--source", str(source), "--target-dir", str(device), *flags]
    return cli.main(arguments)


def not_on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


def typing(monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    monkeypatch.setattr("sys.stdin", Keyboard(answer))


def names(folder: Path) -> set[str]:
    return {path.name for path in folder.rglob("*") if path.is_file()}


# Dry runs


@pytest.mark.parametrize(
    "flags", [[], ["--move"], ["--clean-unmatched"], ["--move", "--clean-unmatched", "--overwrite"]]
)
def test_a_dry_run_changes_nothing_on_either_side(
    source: Path, device: Path, flags: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    not_on_a_terminal(monkeypatch)  # and it needs no --yes
    good = make_bios_file(source, "good.bin")
    make_bios_file(source, "junk.bin")
    (device / "existing.bin").write_bytes(b"old")
    put_report(device, make_missing("ps1/a.bin", good.md5), make_missing("existing.bin", good.md5))
    before = snapshot(source), snapshot(device)

    assert beck(source, device, "--dry-run", *flags) == 0

    assert (snapshot(source), snapshot(device)) == before
    assert not (device / "ps1").exists()


def test_a_dry_run_lists_what_it_would_do(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_bios_file(source, "good.bin")
    make_bios_file(source, "junk.bin")
    put_report(device, make_missing("ps1/a.bin", good.md5))

    assert beck(source, device, "--dry-run", "--move", "--clean-unmatched") == 0

    output = capsys.readouterr().out
    assert "good.bin: would copy -> ps1/a.bin" in output
    assert "good.bin: would be deleted" in output
    assert "junk.bin: no match, would be deleted" in output
    assert "Dry run: 1/1 missing entries would be satisfied, 2 files analysed" in output
    assert "would delete 2 local files" in output
    assert "PLEASE SCAN" not in output


def test_a_dry_run_warns_about_what_unmatched_means(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # DEC-56: after an upload and a rescan, good files aren't in the report any more.
    make_bios_file(source, "good.bin")
    put_report(device, make_missing("a.bin", C))

    assert beck(source, device, "--dry-run", "--clean-unmatched") == 0

    assert "That doesn't mean they're junk" in capsys.readouterr().out


def test_no_warning_when_clean_would_delete_nothing(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_bios_file(source, "good.bin")
    put_report(device, make_missing("a.bin", good.md5))

    assert beck(source, device, "--dry-run", "--clean-unmatched") == 0

    assert "junk" not in capsys.readouterr().out


def test_a_plain_dry_run_doesnt_mention_deleting(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_bios_file(source, "good.bin")
    put_report(device, make_missing("a.bin", good.md5))

    assert beck(source, device, "--dry-run") == 0

    assert "delet" not in capsys.readouterr().out


# Nothing is deleted without being asked


def test_with_no_flags_nothing_local_is_deleted(source: Path, device: Path) -> None:
    good = make_bios_file(source, "good.bin")
    make_bios_file(source, "junk.bin")
    put_report(device, make_missing("a.bin", good.md5))
    before = snapshot(source)

    assert beck(source, device) == 0

    assert snapshot(source) == before


def test_yes_alone_deletes_nothing(source: Path, device: Path) -> None:
    good = make_bios_file(source, "good.bin")
    make_bios_file(source, "junk.bin")
    put_report(device, make_missing("a.bin", good.md5))
    before = snapshot(source)

    assert beck(source, device, "--yes") == 0

    assert snapshot(source) == before


# Confirmation


@pytest.mark.parametrize("flag", ["--move", "--clean-unmatched"])
def test_off_a_terminal_it_refuses_without_yes_and_changes_nothing(
    source: Path,
    device: Path,
    flag: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    not_on_a_terminal(monkeypatch)
    good = make_bios_file(source, "good.bin")
    make_bios_file(source, "junk.bin")
    put_report(device, make_missing("a.bin", good.md5))
    before = snapshot(source), snapshot(device)

    assert beck(source, device, flag) == 2

    assert (snapshot(source), snapshot(device)) == before  # not even the upload
    output = capsys.readouterr().out
    assert "--yes" in output
    assert "--dry-run" in output


def test_off_a_terminal_with_nothing_to_delete_it_needs_no_yes(
    source: Path, device: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    not_on_a_terminal(monkeypatch)
    good = make_bios_file(source, "good.bin")
    put_report(device, make_missing("a.bin", good.md5))

    assert beck(source, device, "--clean-unmatched") == 0

    assert (device / "a.bin").exists()
    assert (source / "good.bin").exists()


def test_with_yes_it_deletes_off_a_terminal(
    source: Path, device: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    not_on_a_terminal(monkeypatch)
    good = make_bios_file(source, "good.bin")
    make_bios_file(source, "junk.bin")
    put_report(device, make_missing("a.bin", good.md5))

    assert beck(source, device, "--move", "--clean-unmatched", "--yes") == 0

    assert names(source) == set()
    assert (device / "a.bin").exists()


@pytest.mark.parametrize("answer", ["y\n", "Y\n", "yes\n", "YES\n", " y \n"])
def test_on_a_terminal_yes_goes_ahead(
    source: Path,
    device: Path,
    answer: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    typing(monkeypatch, answer)
    make_bios_file(source, "junk.bin")
    make_bios_file(source, "sub/other.bin")
    put_report(device, make_missing("a.bin", C))

    assert beck(source, device, "--clean-unmatched") == 0

    assert names(source) == set()
    captured = capsys.readouterr()
    assert "Delete 2 files? [y/N]" in captured.err
    assert "junk.bin" in captured.err
    assert "sub/other.bin" in captured.err
    assert "junk.bin: no match, deleted" in captured.out


@pytest.mark.parametrize("answer", ["n\n", "\n", "", "no\n", "maybe\n", "yy\n"])
def test_on_a_terminal_anything_else_changes_nothing_and_exits_2(
    source: Path,
    device: Path,
    answer: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    typing(monkeypatch, answer)
    good = make_bios_file(source, "good.bin")
    put_report(device, make_missing("a.bin", good.md5))
    before = snapshot(source), snapshot(device)

    assert beck(source, device, "--move") == 2

    assert (snapshot(source), snapshot(device)) == before
    assert "Nothing was changed" in capsys.readouterr().out


def test_the_prompt_warns_about_what_unmatched_means(
    source: Path,
    device: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    typing(monkeypatch, "n\n")
    make_bios_file(source, "junk.bin")
    put_report(device, make_missing("a.bin", C))

    beck(source, device, "--clean-unmatched")

    assert "That doesn't mean they're junk" in capsys.readouterr().err


def test_the_prompt_for_move_has_no_such_warning(
    source: Path,
    device: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    typing(monkeypatch, "n\n")
    good = make_bios_file(source, "good.bin")
    put_report(device, make_missing("a.bin", good.md5))

    beck(source, device, "--move")

    assert "junk" not in capsys.readouterr().err


# --move


def test_move_deletes_a_file_after_all_its_targets(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_bios_file(source, "good.bin")
    data = good.path.read_bytes()
    put_report(device, make_missing("a.bin", good.md5), make_missing("ps1/b.bin", good.md5))

    assert beck(source, device, "--move", "--yes") == 0

    assert not good.path.exists()
    assert (device / "a.bin").read_bytes() == data
    assert (device / "ps1" / "b.bin").read_bytes() == data
    output = capsys.readouterr().out
    assert "good.bin: deleted" in output
    assert "Deleted 1 local files." in output


def test_move_leaves_everything_it_didnt_upload(source: Path, device: Path) -> None:
    good = make_bios_file(source, "a-good.bin")
    copy = make_bios_file(source, "b-copy.bin", good.path.read_bytes())
    first = make_bios_file(source, "c-first.bin")
    second = make_bios_file(source, "d-second.bin")
    junk = make_bios_file(source, "e-junk.bin")
    put_report(
        device, make_missing("a.bin", good.md5), make_missing("t.bin", first.md5, second.md5)
    )

    assert beck(source, device, "--move", "--yes") == 0

    assert not good.path.exists()
    assert not first.path.exists()
    assert copy.path.exists()  # a duplicate
    assert second.path.exists()  # its target was already filled
    assert junk.path.exists()  # matched nothing


def test_move_keeps_a_file_if_any_of_its_uploads_failed(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_bios_file(source, "good.bin")
    (device / "blocked").mkdir()
    (device / "blocked" / "b.bin").mkdir()  # uploading over a folder fails
    put_report(device, make_missing("a.bin", good.md5), make_missing("blocked/b.bin", good.md5))

    assert beck(source, device, "--move", "--yes", "--overwrite") == 3

    assert good.path.exists()
    assert "good.bin: deleted" not in capsys.readouterr().out


def test_move_keeps_a_file_if_a_folder_could_not_be_created(source: Path, device: Path) -> None:
    good = make_bios_file(source, "good.bin")
    (device / "blocked").write_bytes(b"a file where a folder should go")
    put_report(device, make_missing("a.bin", good.md5), make_missing("blocked/b.bin", good.md5))

    assert beck(source, device, "--move", "--yes") == 3

    assert good.path.exists()


def test_move_keeps_a_file_whose_target_was_already_there(source: Path, device: Path) -> None:
    # Nothing was uploaded there, so nothing proves that the file on the device is good.
    good = make_bios_file(source, "good.bin")
    (device / "a.bin").write_bytes(b"already here")
    put_report(device, make_missing("a.bin", good.md5), make_missing("b.bin", good.md5))

    assert beck(source, device, "--move", "--yes") == 0

    assert good.path.exists()
    assert (device / "b.bin").exists()


def test_move_keeps_a_file_whose_remote_size_differs(source: Path, device: Path) -> None:
    class Truncating(LocalTransport):
        def upload(self, local: Path, remote: PurePosixPath) -> int:
            written = super().upload(local, remote)
            self._resolve(remote).write_bytes(b"short")
            return written

    good = make_bios_file(source, "good.bin")
    built = plan([make_missing("a.bin", good.md5)], scan(source).files)

    with Truncating(device) as transport:
        result = execute(built, transport, dry_run=False, move=True)

    assert good.path.exists()
    assert result.deleted == ()
    assert "has 5 bytes on the target, not 64" in result.errors[0].message


def test_move_keeps_a_file_if_its_size_cant_be_checked(source: Path, device: Path) -> None:
    class NoSize(LocalTransport):
        def size(self, path: PurePosixPath) -> int:
            raise TransportError("can't check")

    good = make_bios_file(source, "good.bin")
    built = plan([make_missing("a.bin", good.md5)], scan(source).files)

    with NoSize(device) as transport:
        result = execute(built, transport, dry_run=False, move=True)

    assert good.path.exists()
    assert [error.message for error in result.errors] == ["can't check"]


def test_move_with_overwrite_deletes_after_replacing(source: Path, device: Path) -> None:
    good = make_bios_file(source, "good.bin")
    (device / "a.bin").write_bytes(b"old")
    put_report(device, make_missing("a.bin", good.md5))
    data = good.path.read_bytes()

    assert beck(source, device, "--move", "--overwrite", "--yes") == 0

    assert not good.path.exists()
    assert (device / "a.bin").read_bytes() == data


def test_a_dry_run_of_move_only_lists_files_that_would_really_go(
    source: Path, device: Path
) -> None:
    good = make_bios_file(source, "good.bin")
    there = make_bios_file(source, "there.bin")
    (device / "b.bin").write_bytes(b"already here")
    report = [make_missing("a.bin", good.md5), make_missing("b.bin", there.md5)]
    built = plan(report, scan(source).files)

    with LocalTransport(device) as transport:
        result = execute(built, transport, dry_run=True, move=True)

    assert [file.relative.name for file in result.deleted] == ["good.bin"]
    assert good.path.exists()


# --clean-unmatched


def test_clean_deletes_only_what_matched_nothing(source: Path, device: Path) -> None:
    good = make_bios_file(source, "a-good.bin")
    copy = make_bios_file(source, "b-copy.bin", good.path.read_bytes())
    first = make_bios_file(source, "c-first.bin")
    second = make_bios_file(source, "d-second.bin")
    junk = make_bios_file(source, "sub/e-junk.bin")
    make_bios_file(source, ".keep", b"")
    put_report(
        device, make_missing("a.bin", good.md5), make_missing("t.bin", first.md5, second.md5)
    )

    assert beck(source, device, "--clean-unmatched", "--yes") == 0

    assert not junk.path.exists()
    assert good.path.exists()  # uploaded, and no --move
    assert copy.path.exists()  # a duplicate
    assert first.path.exists()
    assert second.path.exists()  # its target was already filled
    assert (source / ".keep").exists()  # hidden files aren't scanned


def test_clean_keeps_a_file_valid_for_an_incorrect_target(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # DEC-59: it's the fix for the file on the device.
    valid = make_bios_file(source, "valid.bin")
    junk = make_bios_file(source, "junk.bin")
    wanted = make_bios_file(source, "wanted.bin")
    put_report(
        device,
        make_missing("two/b.bin", valid.md5, incorrect=True, current_md5=C),
        make_missing("a.bin", wanted.md5),
    )

    assert beck(source, device, "--clean-unmatched", "--yes") == 0

    assert valid.path.exists()
    assert not junk.path.exists()
    assert "valid.bin: valid for two/b.bin" in capsys.readouterr().out


def test_clean_deletes_a_known_bad_file(source: Path, device: Path) -> None:
    bad = make_bios_file(source, "bad-dump.bin")
    wanted = make_bios_file(source, "wanted.bin")
    put_report(
        device,
        make_missing("two/b.bin", "d" * 32, incorrect=True, current_md5=bad.md5),
        make_missing("a.bin", wanted.md5),
    )

    assert beck(source, device, "--clean-unmatched", "--yes") == 0

    assert not bad.path.exists()


def test_clean_deletes_nothing_after_any_failure(source: Path, device: Path) -> None:
    good = make_bios_file(source, "good.bin")
    junk = make_bios_file(source, "junk.bin")
    (device / "blocked").write_bytes(b"a file where a folder should go")
    put_report(device, make_missing("blocked/a.bin", good.md5))

    assert beck(source, device, "--clean-unmatched", "--yes") == 3

    assert junk.path.exists()


def test_clean_deletes_nothing_when_nothing_is_missing(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    junk = make_bios_file(source, "junk.bin")
    put_report(device)

    assert beck(source, device, "--clean-unmatched", "--yes") == 0

    assert junk.path.exists()
    assert "No missing bios" in capsys.readouterr().out


def test_clean_deletes_nothing_when_only_incorrect_files_are_listed(
    source: Path, device: Path
) -> None:
    junk = make_bios_file(source, "junk.bin")
    put_report(device, make_missing("two/b.bin", C, incorrect=True))

    assert beck(source, device, "--clean-unmatched", "--yes") == 0

    assert junk.path.exists()


def test_clean_after_a_failure_to_read_the_report_deletes_nothing(
    source: Path, device: Path
) -> None:
    junk = make_bios_file(source, "junk.bin")
    (device / "missing_bios_report.txt").write_text(
        "A FORMAT BECK DOESN'T KNOW\n", encoding="utf-8"
    )

    assert beck(source, device, "--clean-unmatched", "--yes") == 4

    assert junk.path.exists()


def test_a_file_that_cant_be_deleted_is_recorded_and_the_rest_continue(
    source: Path, device: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = make_bios_file(source, "a.bin"), make_bios_file(source, "b.bin")
    put_report(device, make_missing("x.bin", C))
    real_unlink = Path.unlink

    def fail_for_a(self: Path, *args: object, **kwargs: object) -> None:
        if self == a.path:
            raise PermissionError(13, "Permission denied")
        real_unlink(self)

    monkeypatch.setattr(Path, "unlink", fail_for_a)

    assert beck(source, device, "--clean-unmatched", "--yes") == 3

    assert a.path.exists()
    assert not b.path.exists()
    output = capsys.readouterr().out
    assert "Couldn't delete a.bin: Permission denied" in output
    assert "a.bin: no match, kept" in output
    assert "b.bin: no match, deleted" in output


def test_an_unreadable_file_is_never_deleted(
    source: Path, device: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (source / "broken.bin").symlink_to(source / "no-such-target")
    make_bios_file(source, "good.bin")
    put_report(device, make_missing("x.bin", C))

    assert beck(source, device, "--clean-unmatched", "--yes") == 0

    assert (source / "broken.bin").is_symlink()


def test_moving_a_symlink_removes_the_link_not_what_it_points_to(
    source: Path, device: Path, tmp_path: Path
) -> None:
    real = make_bios_file(tmp_path / "elsewhere", "real.bin")
    (source / "link.bin").symlink_to(real.path)
    put_report(device, make_missing("a.bin", real.md5))

    assert beck(source, device, "--move", "--yes") == 0

    assert not (source / "link.bin").is_symlink()
    assert real.path.exists()
    assert (device / "a.bin").read_bytes() == real.path.read_bytes()
