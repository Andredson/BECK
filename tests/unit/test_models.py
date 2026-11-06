# SPDX-License-Identifier: GPL-3.0-only
"""The domain models: frozen, typed, and impossible to build in an invalid state."""

import dataclasses
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from beck.models import (
    Duplicate,
    ItemError,
    LocalFile,
    MissingBios,
    Plan,
    PlannedUpload,
    RunResult,
    ScanResult,
    Unreadable,
)

MD5_A = "a" * 32
MD5_B = "b" * 32


def missing(target: str = "ps1/scph.bin", md5s: tuple[str, ...] = (MD5_A,)) -> MissingBios:
    return MissingBios(
        name=PurePosixPath(target).name, target=PurePosixPath(target), md5s=frozenset(md5s)
    )


def local(relative: str = "copy.bin", md5: str = MD5_A) -> LocalFile:
    return LocalFile(
        path=Path("/bios") / relative, relative=PurePosixPath(relative), md5=md5, size=4
    )


def upload(target: str = "ps1/scph.bin", relative: str = "copy.bin") -> PlannedUpload:
    return PlannedUpload(
        source=local(relative), target=PurePosixPath(target), entry=missing(target)
    )


@pytest.mark.parametrize(
    "instance",
    [
        missing(),
        local(),
        upload(),
        Duplicate(file=local("b.bin"), of=local("a.bin")),
        Plan(),
        ItemError(item="a.bin", message="failed"),
        Unreadable(relative=PurePosixPath("a.bin"), reason="broken symlink"),
        ScanResult(),
        RunResult(plan=Plan()),
    ],
    ids=lambda instance: type(instance).__name__,
)
def test_models_are_frozen_slotted_and_hashable(instance: Any) -> None:
    field = dataclasses.fields(instance)[0].name

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, field, None)
    assert not hasattr(instance, "__dict__")
    assert hash(instance) == hash(dataclasses.replace(instance))


def test_missing_bios_defaults_say_the_report_gave_no_detail() -> None:
    entry = missing()

    assert entry.required is None
    assert entry.system is None


@pytest.mark.parametrize("md5", ["A" * 32, "a" * 31, "a" * 33, "g" * 32, "", f"{'a' * 32}\n"])
def test_invalid_md5s_are_rejected(md5: str) -> None:
    with pytest.raises(ValueError, match="Not a lowercase MD5"):
        local(md5=md5)
    with pytest.raises(ValueError, match="Not a lowercase MD5"):
        missing(md5s=(MD5_A, md5))


@pytest.mark.parametrize("path", ["/recalbox/share/bios/a.bin", "../a.bin", "ps1/../../a.bin", "."])
def test_paths_must_be_relative_files(path: str) -> None:
    pure = PurePosixPath(path)

    with pytest.raises(ValueError, match="Not a relative file path"):
        MissingBios(name=pure.name, target=pure, md5s=frozenset({MD5_A}))
    with pytest.raises(ValueError, match="Not a relative file path"):
        LocalFile(path=Path("/bios/a.bin"), relative=pure, md5=MD5_A, size=1)


def test_target_must_end_in_the_entry_name() -> None:
    with pytest.raises(ValueError, match="doesn't end in"):
        MissingBios(name="other.bin", target=PurePosixPath("ps1/a.bin"), md5s=frozenset({MD5_A}))


def test_an_entry_needs_at_least_one_md5() -> None:
    with pytest.raises(ValueError, match="No MD5"):
        missing(md5s=())


def test_local_file_size_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="Negative size"):
        LocalFile(path=Path("/bios/a"), relative=PurePosixPath("a"), md5=MD5_A, size=-1)


def test_an_upload_must_go_to_its_entry_target() -> None:
    with pytest.raises(ValueError, match="isn't the entry's"):
        PlannedUpload(source=local(), target=PurePosixPath("other.bin"), entry=missing())


def test_an_upload_source_must_have_a_listed_md5() -> None:
    with pytest.raises(ValueError, match="has no MD5 listed"):
        PlannedUpload(source=local(md5=MD5_B), target=missing().target, entry=missing())


def test_a_current_md5_needs_an_incorrect_entry() -> None:
    path = PurePosixPath("a.bin")

    with pytest.raises(ValueError, match="isn't incorrect"):
        MissingBios(name="a.bin", target=path, md5s=frozenset({MD5_A}), current_md5=MD5_B)


def test_a_current_md5_must_be_a_valid_md5() -> None:
    path = PurePosixPath("a.bin")

    with pytest.raises(ValueError, match="Not a lowercase MD5"):
        MissingBios(
            name="a.bin", target=path, md5s=frozenset({MD5_A}), incorrect=True, current_md5="BAD"
        )


def test_plan_is_empty_by_default() -> None:
    plan = Plan()

    assert dataclasses.astuple(plan) == ((), (), (), (), (), (), (), ())


def test_plan_sorts_every_field_whatever_the_input_order() -> None:
    a, b = local("a.bin"), local("b.bin")
    first = upload("a/x.bin")
    second = upload("b/x.bin")
    gone, later = missing("a/y.bin"), missing("b/y.bin")
    dup_a, dup_b = Duplicate(file=a, of=b), Duplicate(file=b, of=a)
    folder_a, folder_b = PurePosixPath("a"), PurePosixPath("b")

    forward = Plan(
        uploads=(first, second),
        directories=(folder_a, folder_b),
        duplicates=(dup_a, dup_b),
        unmatched=(a, b),
        already_filled=(a, b),
        still_missing=(gone, later),
    )
    backward = Plan(
        uploads=(second, first),
        directories=(folder_b, folder_a),
        duplicates=(dup_b, dup_a),
        unmatched=(b, a),
        already_filled=(b, a),
        still_missing=(later, gone),
    )

    assert forward == backward
    assert backward.uploads == (first, second)
    assert backward.directories == (folder_a, folder_b)
    assert backward.duplicates == (dup_a, dup_b)
    assert backward.unmatched == (a, b)
    assert backward.already_filled == (a, b)
    assert backward.still_missing == (gone, later)


def test_plan_sorts_incorrect_entries() -> None:
    first = MissingBios(
        name="a.bin", target=PurePosixPath("a.bin"), md5s=frozenset({MD5_A}), incorrect=True
    )
    second = MissingBios(
        name="b.bin", target=PurePosixPath("b.bin"), md5s=frozenset({MD5_A}), incorrect=True
    )

    assert Plan(incorrect=(second, first)).incorrect == (first, second)


def test_uploads_to_one_target_are_ordered_by_source() -> None:
    late, early = upload("a.bin", "z.bin"), upload("a.bin", "b.bin")

    assert Plan(uploads=(late, early)).uploads == (early, late)


def test_local_paths_sort_as_text_like_stage_03() -> None:
    slash, dash = local("a/x.bin"), local("a-b/x.bin")

    plan = Plan(
        duplicates=(Duplicate(file=slash, of=dash), Duplicate(file=dash, of=slash)),
        unmatched=(slash, dash),
        already_filled=(slash, dash),
    )

    assert plan.unmatched == plan.already_filled == (dash, slash)
    assert plan.duplicates[0].file == dash


def test_run_result_defaults_to_a_real_run_with_nothing_done() -> None:
    result = RunResult(plan=Plan())

    assert result.dry_run is False
    assert not (result.completed or result.skipped or result.errors)
