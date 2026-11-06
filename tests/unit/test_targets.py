"""Parsing --target URLs: valid forms, and refusing passwords and paths that leave the share."""

from pathlib import PurePosixPath

import pytest

from beck.errors import UsageError
from beck.targets import SmbTarget, parse_smb_url

ROOT = PurePosixPath(".")
CREDENTIAL = "beck-test-password"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("smb://recalbox/bios", SmbTarget("recalbox", 445, "bios")),
        ("smb://recalbox.local/bios/", SmbTarget("recalbox.local", 445, "bios")),
        ("SMB://recalbox/bios", SmbTarget("recalbox", 445, "bios")),
        ("smb://192.168.1.20/bios", SmbTarget("192.168.1.20", 445, "bios")),
        ("smb://recalbox:4450/bios", SmbTarget("recalbox", 4450, "bios")),
        ("smb://beck@recalbox/bios", SmbTarget("recalbox", 445, "bios", ROOT, "beck")),
        ("smb://beck@recalbox:4450/bios", SmbTarget("recalbox", 4450, "bios", ROOT, "beck")),
        ("smb://recalbox/share/bios", SmbTarget("recalbox", 445, "share", PurePosixPath("bios"))),
        (
            "smb://recalbox/share/a/b/",
            SmbTarget("recalbox", 445, "share", PurePosixPath("a/b")),
        ),
        ("smb://[::1]:4450/bios", SmbTarget("::1", 4450, "bios")),
        (
            "smb://recalbox/roms%20(internal)/a%20b",
            SmbTarget("recalbox", 445, "roms (internal)", PurePosixPath("a b")),
        ),
        ("smb://me%40home@recalbox/bios", SmbTarget("recalbox", 445, "bios", ROOT, "me@home")),
    ],
)
def test_valid_urls(url: str, expected: SmbTarget) -> None:
    assert parse_smb_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        f"smb://beck:{CREDENTIAL}@recalbox/bios",
        f"smb://beck:{CREDENTIAL}@recalbox:4450/bios",
        f"smb://:{CREDENTIAL}@recalbox/bios",
        "smb://beck:@recalbox/bios",
    ],
)
def test_a_password_is_refused_and_never_repeated(url: str) -> None:
    with pytest.raises(UsageError) as error:
        parse_smb_url(url)

    assert "can't contain a password" in str(error.value)
    assert CREDENTIAL not in str(error.value)
    assert error.value.exit_code == 2


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://recalbox/bios", "must start with smb://"),
        ("recalbox/bios", "must start with smb://"),
        ("", "must start with smb://"),
        ("smb:///bios", "has no host"),
        ("smb://recalbox", "has no share"),
        ("smb://recalbox/", "has no share"),
        ("smb://recalbox:notaport/bios", "isn't a valid URL"),
        ("smb://recalbox:99999/bios", "isn't a valid URL"),
        ("smb://recalbox:0/bios", "isn't a valid URL"),
        ("smb://recalbox/bios?x=1", "query or fragment"),
        ("smb://recalbox/bios#x", "query or fragment"),
    ],
)
def test_invalid_urls_are_usage_errors(url: str, message: str) -> None:
    with pytest.raises(UsageError, match=message) as error:
        parse_smb_url(url)

    assert "smb://[user@]host[:port]/share[/sub/path]" in str(error.value)


@pytest.mark.parametrize(
    "path",
    [
        "..",
        "bios/..",
        "bios/../..",
        "bios/.",
        "%2e%2e",
        "bios/%2e%2e",
        "a%2fb",
        "bios/a%5cb",
        "a\\b",
    ],
)
def test_paths_that_could_climb_out_are_refused(path: str) -> None:
    with pytest.raises(UsageError, match="path can't contain"):
        parse_smb_url(f"smb://recalbox/{path}")


def test_an_error_in_a_url_with_a_password_never_repeats_it() -> None:
    for url in (
        f"http://beck:{CREDENTIAL}@recalbox/bios",
        f"smb://beck:{CREDENTIAL}@recalbox:notaport/bios",
    ):
        with pytest.raises(UsageError) as error:
            parse_smb_url(url)
        assert CREDENTIAL not in str(error.value)
