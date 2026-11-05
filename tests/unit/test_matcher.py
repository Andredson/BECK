"""The matcher: ported from the stage 03 matching tests (D3, step 03.12a), now with plain data."""

import hashlib
import itertools
import os
from pathlib import Path, PurePosixPath

from beck.frontends.recalbox import RecalboxAdapter
from beck.hashing import scan
from beck.matcher import plan
from beck.models import Duplicate, LocalFile, MissingBios, Plan
from tests.conftest import REAL_REPORT, load_report

A, B, C = "a" * 32, "b" * 32, "c" * 32


def entry(target: str, *md5s: str, system: str | None = None) -> MissingBios:
    path = PurePosixPath(target)
    return MissingBios(name=path.name, target=path, md5s=frozenset(md5s), system=system)


def local(relative: str, md5: str) -> LocalFile:
    return LocalFile(
        path=Path("/bios", relative), relative=PurePosixPath(relative), md5=md5, size=1
    )


def filled(result: Plan) -> dict[str, str]:
    """Which target gets which local file."""
    return {u.target.as_posix(): u.source.relative.as_posix() for u in result.uploads}


def test_nothing_in_gives_an_empty_plan() -> None:
    assert plan([], []) == Plan()


def test_one_file_two_entries_gives_two_uploads() -> None:
    result = plan([entry("a.bin", A), entry("ps1/b.bin", A)], [local("my-copy.bin", A)])

    assert filled(result) == {"a.bin": "my-copy.bin", "ps1/b.bin": "my-copy.bin"}
    assert result.already_filled == ()


def test_two_identical_files_give_one_upload_and_a_duplicate() -> None:
    first, second = local("a-first.bin", A), local("b-second.bin", A)

    result = plan([entry("target.bin", A)], [second, first])

    assert filled(result) == {"target.bin": "a-first.bin"}
    assert result.duplicates == (Duplicate(file=second, of=first),)


def test_same_target_in_several_entries_uploads_once() -> None:
    report = [entry("pcengine/gexpress.pce", A, system=name) for name in ("x", "y", "z")]

    result = plan(report, [local("game.pce", A)])

    assert filled(result) == {"pcengine/gexpress.pce": "game.pce"}
    assert result.still_missing == ()


def test_second_different_file_does_not_overwrite_a_filled_target() -> None:
    second = local("b.img", B)

    result = plan([entry("atarist/tos.img", A, B)], [local("a.img", A), second])

    assert filled(result) == {"atarist/tos.img": "a.img"}
    assert result.already_filled == (second,)


def test_entries_for_one_target_with_different_lists_are_all_satisfied() -> None:
    result = plan([entry("x.bin", A), entry("x.bin", B)], [local("copy.bin", B)])

    assert filled(result) == {"x.bin": "copy.bin"}
    assert result.still_missing == ()


def test_file_named_like_the_target_beats_an_earlier_file() -> None:
    # On the real report, falcon.img sorted first and took the place of the user's real tos.img.
    falcon = local("falcon.img", A)

    result = plan([entry("atarist/tos.img", A, B)], [falcon, local("tos.img", B)])

    assert filled(result) == {"atarist/tos.img": "tos.img"}
    assert result.already_filled == (falcon,)


def test_a_name_in_a_sub_folder_counts_too() -> None:
    result = plan([entry("tos.img", A, B)], [local("a.img", A), local("z/tos.img", B)])

    assert filled(result) == {"tos.img": "z/tos.img"}


def test_identical_copy_named_like_the_target_is_the_one_uploaded() -> None:
    copy, named = local("a-copy.img", A), local("tos.img", A)

    result = plan([entry("tos.img", A)], [copy, named])

    assert filled(result) == {"tos.img": "tos.img"}
    assert result.duplicates == (Duplicate(file=copy, of=named),)


def test_a_file_does_not_take_a_target_from_the_file_named_like_it() -> None:
    # a.img also fits target b.img, and comes first, but the local b.img must fill that target.
    report = [entry("a.img", A), entry("b.img", A, B)]

    result = plan(report, [local("a.img", A), local("b.img", B)])

    assert filled(result) == {"a.img": "a.img", "b.img": "b.img"}


def test_file_named_like_a_target_still_fills_its_other_targets() -> None:
    result = plan([entry("st.img", A), entry("tos.img", A)], [local("tos.img", A)])

    assert filled(result) == {"st.img": "tos.img", "tos.img": "tos.img"}


def test_the_name_only_counts_when_the_md5_fits_that_target() -> None:
    # A local tos.img whose MD5 isn't on the tos.img entry gets no priority for that target.
    report = [entry("tos.img", A), entry("st.img", B)]

    result = plan(report, [local("falcon.img", A), local("tos.img", B)])

    assert filled(result) == {"tos.img": "falcon.img", "st.img": "tos.img"}


def test_paths_compare_as_text_like_stage_03() -> None:
    # As text, a-b/ sorts before a/. A folder-by-folder comparison would pick a/x.bin.
    result = plan([entry("t.bin", A, B)], [local("a/x.bin", A), local("a-b/x.bin", B)])

    assert filled(result) == {"t.bin": "a-b/x.bin"}


def test_files_with_no_match_are_listed() -> None:
    other = local("junk.bin", B)

    result = plan([entry("a.bin", A)], [local("copy.bin", A), other])

    assert result.unmatched == (other,)


def test_targets_nobody_filled_are_still_missing() -> None:
    gone = entry("dc/naomi.zip", B)

    result = plan([entry("a.bin", A), gone], [local("copy.bin", A)])

    assert result.still_missing == (gone,)


def test_every_entry_for_an_unfilled_target_is_listed() -> None:
    report = [entry("x.pce", A, system="one"), entry("x.pce", A, system="two")]

    assert plan(report, []).still_missing == tuple(report)


def test_directories_are_the_folders_uploads_need() -> None:
    report = [
        entry("root.bin", A),
        entry("amiga/bios/kick.rom", A),
        entry("amiga/bios/other.rom", A),
        entry("ps1/scph.bin", A),
        entry("never/filled.bin", B),
    ]

    result = plan(report, [local("copy.bin", A)])

    assert result.directories == (PurePosixPath("amiga/bios"), PurePosixPath("ps1"))


def test_the_plan_does_not_depend_on_input_order() -> None:
    report = [
        entry("a.img", A),
        entry("b.img", A, B),
        entry("shared.pce", B, system="one"),
        entry("shared.pce", C, system="two"),
        entry("never.bin", "d" * 32),
    ]
    files = [
        local("a.img", A),
        local("b.img", B),
        local("copy.img", A),
        local("z/other.bin", C),
        local("junk.bin", "e" * 32),
    ]

    plans = {
        plan(list(entries), list(found))
        for entries in itertools.permutations(report)
        for found in itertools.permutations(files)
    }

    assert len(plans) == 1


def test_which_entry_a_target_records_does_not_depend_on_input_order() -> None:
    one, two = entry("shared.pce", A, system="one"), entry("shared.pce", A, system="two")
    files = [local("copy.pce", A)]

    assert plan([one, two], files) == plan([two, one], files)
    assert plan([one, two], []) == plan([two, one], [])
    assert plan([two, one], files).uploads[0].entry == one


def test_identical_copy_in_a_sub_folder_named_like_the_target_is_the_one_uploaded() -> None:
    copy, named = local("a-copy.img", A), local("z/tos.img", A)

    result = plan([entry("tos.img", A)], [copy, named])

    assert filled(result) == {"tos.img": "z/tos.img"}
    assert result.duplicates == (Duplicate(file=copy, of=named),)


def test_real_report_shared_md5_and_repeated_target() -> None:
    # Hashes come from the real report; no file content is involved.
    report = RecalboxAdapter().parse_report(load_report(REAL_REPORT))

    shared = plan(report, [local("copy.bin", "c87a52c277f7952b41c639fc7bf0a43b")])
    repeated = plan(report, [local("copy.bin", "6d2cb14fc3e1f65ceb135633d1694122")])

    assert {"atarist/tos.img", "atarist/st.img"} == set(filled(shared))
    assert set(filled(repeated)) == {"pcengine/gexpress.pce"}


def test_real_report_with_no_files_leaves_every_target_missing() -> None:
    report = RecalboxAdapter().parse_report(load_report(REAL_REPORT))

    result = plan(report, [])

    assert len(result.still_missing) == 238
    assert len({e.target for e in result.still_missing}) == 232


def test_the_plan_only_references_files_in_the_scanned_folder(tmp_path: Path) -> None:
    data = os.urandom(64)
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    (tmp_path / "ps1").mkdir()
    (tmp_path / "ps1" / "copy.bin").write_bytes(data)
    (tmp_path / "other.bin").write_bytes(data)
    (tmp_path / "junk.bin").write_bytes(os.urandom(64))

    result = plan([entry("t.bin", md5)], scan(tmp_path))

    found = [u.source for u in result.uploads] + list(result.unmatched)
    found += [d.file for d in result.duplicates] + [d.of for d in result.duplicates]
    assert len(found) == 4
    for file in found:
        assert file.path.resolve().is_relative_to(tmp_path.resolve())
