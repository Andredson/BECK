"""The matcher: ported from the stage 03 matching tests (D3, step 03.12a), now with plain data."""

import itertools
import random
from pathlib import Path, PurePosixPath

from beck.frontends.recalbox import RecalboxAdapter
from beck.hashing import scan
from beck.matcher import plan
from beck.models import Duplicate, LocalFile, MissingBios, Plan
from tests.conftest import REAL_REPORT, load_report
from tests.factories import make_bios_file, make_local_file, make_missing

A, B, C = "a" * 32, "b" * 32, "c" * 32


def filled(result: Plan) -> dict[str, str]:
    """Which target gets which local file."""
    return {u.target.as_posix(): u.source.relative.as_posix() for u in result.uploads}


def test_nothing_in_gives_an_empty_plan() -> None:
    assert plan([], []) == Plan()


def test_nothing_matches() -> None:
    report = [make_missing("a.bin", A), make_missing("ps1/b.bin", B)]
    junk = make_local_file("junk.bin", C)

    result = plan(report, [junk])

    assert result == Plan(unmatched=(junk,), still_missing=tuple(report))


def test_no_files_leaves_everything_missing() -> None:
    report = [make_missing("a.bin", A)]

    assert plan(report, []) == Plan(still_missing=tuple(report))


def test_no_report_entries_leaves_every_file_unmatched() -> None:
    file = make_local_file("a.bin", A)

    assert plan([], [file]) == Plan(unmatched=(file,))


def test_everything_matches() -> None:
    report = [make_missing("a.bin", A), make_missing("ps1/b.bin", B), make_missing("x/y/c.bin", C)]
    files = [make_local_file("1", A), make_local_file("2", B), make_local_file("3", C)]

    result = plan(report, files)

    assert filled(result) == {"a.bin": "1", "ps1/b.bin": "2", "x/y/c.bin": "3"}
    assert not (result.unmatched or result.duplicates or result.already_filled)
    assert not result.still_missing


def test_many_files_for_one_entry_fill_it_once() -> None:
    files = [make_local_file(name, md5) for name, md5 in (("1", A), ("2", B), ("3", C))]

    result = plan([make_missing("t.bin", A, B, C)], files)

    assert filled(result) == {"t.bin": "1"}
    assert [file.relative.name for file in result.already_filled] == ["2", "3"]


def test_one_file_two_entries_gives_two_uploads() -> None:
    result = plan(
        [make_missing("a.bin", A), make_missing("ps1/b.bin", A)],
        [make_local_file("my-copy.bin", A)],
    )

    assert filled(result) == {"a.bin": "my-copy.bin", "ps1/b.bin": "my-copy.bin"}
    assert result.already_filled == ()


def test_two_identical_files_give_one_upload_and_a_duplicate() -> None:
    first, second = make_local_file("a-first.bin", A), make_local_file("b-second.bin", A)

    result = plan([make_missing("target.bin", A)], [second, first])

    assert filled(result) == {"target.bin": "a-first.bin"}
    assert result.duplicates == (Duplicate(file=second, of=first),)


def test_same_target_in_several_entries_uploads_once() -> None:
    report = [make_missing("pcengine/gexpress.pce", A, system=name) for name in ("x", "y", "z")]

    result = plan(report, [make_local_file("game.pce", A)])

    assert filled(result) == {"pcengine/gexpress.pce": "game.pce"}
    assert result.still_missing == ()


def test_second_different_file_does_not_overwrite_a_filled_target() -> None:
    second = make_local_file("b.img", B)

    result = plan([make_missing("atarist/tos.img", A, B)], [make_local_file("a.img", A), second])

    assert filled(result) == {"atarist/tos.img": "a.img"}
    assert result.already_filled == (second,)


def test_entries_for_one_target_with_different_lists_are_all_satisfied() -> None:
    result = plan(
        [make_missing("x.bin", A), make_missing("x.bin", B)], [make_local_file("copy.bin", B)]
    )

    assert filled(result) == {"x.bin": "copy.bin"}
    assert result.still_missing == ()


def test_file_named_like_the_target_beats_an_earlier_file() -> None:
    # On the real report, falcon.img sorted first and took the place of the user's real tos.img.
    falcon = make_local_file("falcon.img", A)

    result = plan([make_missing("atarist/tos.img", A, B)], [falcon, make_local_file("tos.img", B)])

    assert filled(result) == {"atarist/tos.img": "tos.img"}
    assert result.already_filled == (falcon,)


def test_a_name_in_a_sub_folder_counts_too() -> None:
    result = plan(
        [make_missing("tos.img", A, B)],
        [make_local_file("a.img", A), make_local_file("z/tos.img", B)],
    )

    assert filled(result) == {"tos.img": "z/tos.img"}


def test_identical_copy_named_like_the_target_is_the_one_uploaded() -> None:
    copy, named = make_local_file("a-copy.img", A), make_local_file("tos.img", A)

    result = plan([make_missing("tos.img", A)], [copy, named])

    assert filled(result) == {"tos.img": "tos.img"}
    assert result.duplicates == (Duplicate(file=copy, of=named),)


def test_a_file_does_not_take_a_target_from_the_file_named_like_it() -> None:
    # a.img also fits target b.img, and comes first, but the local b.img must fill that target.
    report = [make_missing("a.img", A), make_missing("b.img", A, B)]

    result = plan(report, [make_local_file("a.img", A), make_local_file("b.img", B)])

    assert filled(result) == {"a.img": "a.img", "b.img": "b.img"}


def test_file_named_like_a_target_still_fills_its_other_targets() -> None:
    result = plan(
        [make_missing("st.img", A), make_missing("tos.img", A)], [make_local_file("tos.img", A)]
    )

    assert filled(result) == {"st.img": "tos.img", "tos.img": "tos.img"}


def test_the_name_only_counts_when_the_md5_fits_that_target() -> None:
    # A local tos.img whose MD5 isn't on the tos.img entry gets no priority for that target.
    report = [make_missing("tos.img", A), make_missing("st.img", B)]

    result = plan(report, [make_local_file("falcon.img", A), make_local_file("tos.img", B)])

    assert filled(result) == {"tos.img": "falcon.img", "st.img": "tos.img"}


def test_paths_compare_as_text_like_stage_03() -> None:
    # As text, a-b/ sorts before a/. A folder-by-folder comparison would pick a/x.bin.
    result = plan(
        [make_missing("t.bin", A, B)],
        [make_local_file("a/x.bin", A), make_local_file("a-b/x.bin", B)],
    )

    assert filled(result) == {"t.bin": "a-b/x.bin"}


def test_files_with_no_match_are_listed() -> None:
    other = make_local_file("junk.bin", B)

    result = plan([make_missing("a.bin", A)], [make_local_file("copy.bin", A), other])

    assert result.unmatched == (other,)


def test_targets_nobody_filled_are_still_missing() -> None:
    gone = make_missing("dc/naomi.zip", B)

    result = plan([make_missing("a.bin", A), gone], [make_local_file("copy.bin", A)])

    assert result.still_missing == (gone,)


def test_every_entry_for_an_unfilled_target_is_listed() -> None:
    report = [make_missing("x.pce", A, system="one"), make_missing("x.pce", A, system="two")]

    assert plan(report, []).still_missing == tuple(report)


def test_directories_are_the_folders_uploads_need() -> None:
    report = [
        make_missing("root.bin", A),
        make_missing("amiga/bios/kick.rom", A),
        make_missing("amiga/bios/other.rom", A),
        make_missing("ps1/scph.bin", A),
        make_missing("never/filled.bin", B),
    ]

    result = plan(report, [make_local_file("copy.bin", A)])

    assert result.directories == (PurePosixPath("amiga/bios"), PurePosixPath("ps1"))


def test_the_plan_does_not_depend_on_input_order() -> None:
    report = [
        make_missing("a.img", A),
        make_missing("b.img", A, B),
        make_missing("shared.pce", B, system="one"),
        make_missing("shared.pce", C, system="two"),
        make_missing("never.bin", "d" * 32),
    ]
    files = [
        make_local_file("a.img", A),
        make_local_file("b.img", B),
        make_local_file("copy.img", A),
        make_local_file("z/other.bin", C),
        make_local_file("junk.bin", "e" * 32),
    ]

    plans = {
        plan(list(entries), list(found))
        for entries in itertools.permutations(report)
        for found in itertools.permutations(files)
    }

    assert len(plans) == 1


def test_which_entry_a_target_records_does_not_depend_on_input_order() -> None:
    one, two = (
        make_missing("shared.pce", A, system="one"),
        make_missing("shared.pce", A, system="two"),
    )
    files = [make_local_file("copy.pce", A)]

    assert plan([one, two], files) == plan([two, one], files)
    assert plan([one, two], []) == plan([two, one], [])
    assert plan([two, one], files).uploads[0].entry == one


def test_identical_copy_in_a_sub_folder_named_like_the_target_is_the_one_uploaded() -> None:
    copy, named = make_local_file("a-copy.img", A), make_local_file("z/tos.img", A)

    result = plan([make_missing("tos.img", A)], [copy, named])

    assert filled(result) == {"tos.img": "z/tos.img"}
    assert result.duplicates == (Duplicate(file=copy, of=named),)


def _real_report_and_files() -> tuple[list[MissingBios], list[LocalFile]]:
    report = RecalboxAdapter().parse_report(load_report(REAL_REPORT))
    md5s = sorted(md5 for entry in report for md5 in entry.md5s)[::3]
    files = [make_local_file(f"{i % 5}/f{i}.bin", md5) for i, md5 in enumerate(md5s)]
    return report, [*files, make_local_file("junk.bin", "e" * 32)]


def test_a_shuffled_real_report_gives_the_same_plan() -> None:
    report, files = _real_report_and_files()
    expected = plan(report, files)
    shuffler = random.Random(20261105)  # noqa: S311 - a repeatable test order, not security

    for _ in range(25):
        shuffler.shuffle(report)
        shuffler.shuffle(files)
        assert plan(report, files) == expected
    assert expected.uploads
    assert expected.still_missing


def test_targets_and_folders_stay_relative() -> None:
    report, files = _real_report_and_files()

    result = plan(report, files)

    paths = [upload.target for upload in result.uploads] + list(result.directories)
    assert paths
    for path in paths:
        assert not path.is_absolute()
        assert ".." not in path.parts


def test_real_report_shared_md5_and_repeated_target() -> None:
    # Hashes come from the real report; no file content is involved.
    report = RecalboxAdapter().parse_report(load_report(REAL_REPORT))

    shared = plan(report, [make_local_file("copy.bin", "c87a52c277f7952b41c639fc7bf0a43b")])
    repeated = plan(report, [make_local_file("copy.bin", "6d2cb14fc3e1f65ceb135633d1694122")])

    assert {"atarist/tos.img", "atarist/st.img"} == set(filled(shared))
    assert set(filled(repeated)) == {"pcengine/gexpress.pce"}


def test_an_incorrect_target_is_never_uploaded_to() -> None:
    wrong = make_missing("two/b.bin", B, incorrect=True, current_md5=C)
    valid = make_local_file("b.bin", B)

    result = plan([wrong], [valid])

    assert result == Plan(unmatched=(valid,), incorrect=(wrong,))


def test_the_known_bad_file_is_not_uploaded_either() -> None:
    wrong = make_missing("two/b.bin", B, incorrect=True, current_md5=C)
    bad_dump = make_local_file("bad.bin", C)

    result = plan([wrong], [bad_dump])

    assert result.uploads == ()
    assert result.unmatched == (bad_dump,)


def test_an_incorrect_target_stays_kept_if_another_entry_lists_it_as_missing() -> None:
    wrong = make_missing("x.bin", B, incorrect=True, system="one")
    also = make_missing("x.bin", A, system="two")

    result = plan([also, wrong], [make_local_file("copy.bin", A)])

    assert result.uploads == ()
    assert result.still_missing == ()
    assert result.incorrect == (wrong,)


def test_incorrect_entries_dont_stop_other_uploads() -> None:
    wrong = make_missing("two/b.bin", B, incorrect=True)

    result = plan([wrong, make_missing("a.bin", A)], [make_local_file("copy.bin", A)])

    assert filled(result) == {"a.bin": "copy.bin"}
    assert result.incorrect == (wrong,)


def test_replace_incorrect_fills_a_target_with_a_valid_file() -> None:
    # DEC-61: only with --overwrite. By default, the target is kept (above).
    wrong = make_missing("two/b.bin", B, incorrect=True, current_md5=C)
    valid = make_local_file("valid.bin", B)

    result = plan([wrong], [valid], replace_incorrect=True)

    assert filled(result) == {"two/b.bin": "valid.bin"}
    assert not (result.incorrect or result.unmatched or result.still_missing)


def test_replace_incorrect_leaves_a_target_with_no_valid_file_as_incorrect() -> None:
    wrong = make_missing("two/b.bin", B, incorrect=True, current_md5=C)
    bad_dump = make_local_file("bad.bin", C)

    result = plan([wrong], [bad_dump], replace_incorrect=True)

    assert result.uploads == ()
    assert result.incorrect == (wrong,)
    assert result.still_missing == ()
    assert result.unmatched == (bad_dump,)


def test_replace_incorrect_still_fills_ordinary_targets() -> None:
    wrong = make_missing("two/b.bin", B, incorrect=True)
    report = [wrong, make_missing("a.bin", A), make_missing("gone.bin", C)]

    result = plan(report, [make_local_file("copy.bin", A)], replace_incorrect=True)

    assert filled(result) == {"a.bin": "copy.bin"}
    assert [e.name for e in result.still_missing] == ["gone.bin"]
    assert result.incorrect == (wrong,)


def test_real_report_with_no_files_leaves_every_target_missing() -> None:
    report = RecalboxAdapter().parse_report(load_report(REAL_REPORT))

    result = plan(report, [])

    assert len(result.still_missing) == 238
    assert len({e.target for e in result.still_missing}) == 232


def test_the_plan_only_references_files_in_the_scanned_folder(tmp_path: Path) -> None:
    match = make_bios_file(tmp_path, "ps1/copy.bin")
    make_bios_file(tmp_path, "other.bin", match.path.read_bytes())
    make_bios_file(tmp_path, "junk.bin")

    result = plan([make_missing("t.bin", match.md5)], scan(tmp_path).files)

    found = [u.source for u in result.uploads] + list(result.unmatched)
    found += [d.file for d in result.duplicates] + [d.of for d in result.duplicates]
    assert len(found) == 4
    for file in found:
        assert file.path.resolve().is_relative_to(tmp_path.resolve())
