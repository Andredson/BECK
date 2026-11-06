# SPDX-License-Identifier: GPL-3.0-only
"""What the built wheel and source archive really hold: PyPI shows this, and it can't be changed."""

import email
import os
import shutil
import subprocess
import tarfile
import zipfile
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UV = shutil.which("uv")

pytestmark = pytest.mark.skipif(UV is None, reason="building the package needs uv")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    assert UV is not None
    out = tmp_path_factory.mktemp("dist")
    # Offline, because tests never touch the network: uv_build is built into uv.
    subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [UV, "build", "--quiet", "--out-dir", str(out)],
        cwd=ROOT,
        check=True,
        env={**os.environ, "UV_OFFLINE": "1"},
    )
    return next(out.glob("*.whl")), next(out.glob("*.tar.gz"))


@pytest.fixture(scope="module")
def metadata(built: tuple[Path, Path]) -> Message:
    with zipfile.ZipFile(built[0]) as wheel:
        name = next(n for n in wheel.namelist() if n.endswith(".dist-info/METADATA"))
        return email.message_from_bytes(wheel.read(name))


def test_the_name_and_the_license_are_the_agreed_ones(metadata: Message) -> None:
    assert metadata["Name"] == "beck-bios"
    assert metadata["License-Expression"] == "GPL-3.0-only"
    assert metadata["License-File"] == "LICENSE"
    assert metadata["Requires-Python"] == ">=3.11"


def test_no_license_classifier_goes_with_the_license_expression(metadata: Message) -> None:
    # PEP 639 doesn't allow both, and PyPI refuses the upload.
    assert not [c for c in metadata.get_all("Classifier", []) if c.startswith("License ::")]


def test_the_author_is_a_name_with_no_email_address(metadata: Message) -> None:
    assert metadata["Author"]
    assert metadata["Author-email"] is None
    assert metadata["Maintainer-email"] is None
    assert "@" not in metadata.as_string().split("\n\n", 1)[0]


@pytest.mark.parametrize("version", ["3.11", "3.12", "3.13", "3.14"])
def test_every_python_ci_tests_is_listed(metadata: Message, version: str) -> None:
    assert f"Programming Language :: Python :: {version}" in metadata.get_all("Classifier", [])


def test_the_classifiers_the_package_promises(metadata: Message) -> None:
    classifiers = metadata.get_all("Classifier", [])

    assert "Programming Language :: Python :: 3 :: Only" in classifiers
    assert "Typing :: Typed" in classifiers
    assert "Environment :: Console" in classifiers


def test_the_links_are_all_there(metadata: Message) -> None:
    links = dict(url.split(", ", 1) for url in metadata.get_all("Project-URL", []))

    assert set(links) == {"Homepage", "Source", "Issues", "Changelog", "Documentation"}
    assert all(url.startswith("https://github.com/Andredson/BECK") for url in links.values())


def test_the_wheel_holds_the_license_and_the_typing_marker(built: tuple[Path, Path]) -> None:
    with zipfile.ZipFile(built[0]) as wheel:
        names = wheel.namelist()

    assert "beck/py.typed" in names
    assert [n for n in names if n.endswith(".dist-info/licenses/LICENSE")]


def test_the_source_archive_holds_the_license(built: tuple[Path, Path]) -> None:
    with tarfile.open(built[1]) as archive:
        names = archive.getnames()

    assert [n for n in names if n.endswith("/LICENSE")]
    assert [n for n in names if n.endswith("/src/beck/py.typed")]
