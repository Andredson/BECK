# SPDX-License-Identifier: GPL-3.0-only
"""Zip-aware matching against the Samba test server (step 11.4). Every archive is random bytes."""

import json
import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import pytest

from beck import cli
from tests.factories import contents_md5, make_missing, make_report_text, make_zip, md5_of
from tests.integration.conftest import Samba

pytestmark = pytest.mark.integration


def test_a_member_and_a_whole_zip_reach_the_share(
    samba: Samba,
    folder: PurePosixPath,
    tmp_path: Path,
    put_report: Callable[[str | bytes], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    bios = os.urandom(4096)
    make_zip(source, "psx.zip", {"bios/scph1001.bin": bios, "readme.txt": b"text"})
    neogeo = {"000-lo.lo": os.urandom(4096), "sp-s2.sp1": os.urandom(4096)}
    mine = make_zip(source, "my-neogeo.zip", neogeo)
    put_report(
        make_report_text(
            [
                make_missing(f"{folder}/ps1/scph1001.bin", md5_of(bios)),
                make_missing(f"{folder}/neogeo.zip", contents_md5(neogeo)),
            ]
        )
    )
    url = f"smb://{samba.host}:{samba.port}/bios"

    exit_code = cli.main(["--json", "check", "--source", str(source), "--target", url, "--verify"])

    document = json.loads(capsys.readouterr().out)
    assert exit_code == 0, document["errors"]
    assert {(u["member"], u["status"]) for u in document["uploads"]} == {
        (None, "uploaded"),
        ("bios/scph1001.bin", "uploaded"),
    }
    with samba.guest() as transport:
        assert transport.read_bytes(folder / "ps1" / "scph1001.bin") == bios
        assert transport.read_bytes(folder / "neogeo.zip") == mine.read_bytes()
