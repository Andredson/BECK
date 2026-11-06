"""The settings file: what it can say, and how it's refused, without ever repeating a secret."""

import logging
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from beck.config import SCHEMA_VERSION, Config, load
from beck.errors import ConfigError

SENTINEL = "beck-test-password-sentinel"
FULL = """\
schema_version = 1

[target]
frontend = "recalbox"
url = "smb://recalbox.local/bios"

[smb]
user = "beck-test-user"
timeout = 10

[source]
dir = "/srv/beck/bios"
"""


def config_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def versioned(body: str) -> str:
    return f"schema_version = 1\n{body}"


def refused(tmp_path: Path, text: str) -> str:
    """The message of the error this file gets."""
    with pytest.raises(ConfigError) as error:
        load(config_file(tmp_path, text))
    return str(error.value)


# What it can say


def test_a_full_file(tmp_path: Path) -> None:
    assert load(config_file(tmp_path, FULL)) == Config(
        frontend="recalbox",
        target_url="smb://recalbox.local/bios",
        smb_user="beck-test-user",
        smb_timeout=10,
        source_dir=Path("/srv/beck/bios"),
    )


def test_a_file_with_only_its_version_says_nothing_else(tmp_path: Path) -> None:
    assert load(config_file(tmp_path, "schema_version = 1\n")) == Config()


def test_nothing_it_leaves_out_has_a_value_so_something_else_can_decide() -> None:
    config = Config()

    assert config.frontend is None
    assert config.target_url is None
    assert config.target_dir is None
    assert config.smb_user is None
    assert config.smb_timeout is None
    assert config.source_dir is None


def test_a_target_can_be_a_folder(tmp_path: Path) -> None:
    config = load(config_file(tmp_path, versioned('[target]\ndir = "/media/user/RECALBOX/bios"\n')))

    assert config.target_dir == Path("/media/user/RECALBOX/bios")
    assert config.target_url is None


def test_an_empty_user_means_a_guest_and_is_not_the_same_as_no_user(tmp_path: Path) -> None:
    assert load(config_file(tmp_path, versioned('[smb]\nuser = ""\n'))).smb_user == ""


@pytest.mark.parametrize(("section", "field"), [("source", "source_dir"), ("target", "target_dir")])
def test_a_folder_can_start_from_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, section: str, field: str
) -> None:
    monkeypatch.setenv("HOME", "/home/beck-test")

    config = load(config_file(tmp_path, versioned(f'[{section}]\ndir = "~/beck/bios"\n')))

    assert getattr(config, field) == Path("/home/beck-test/beck/bios")


def test_a_config_cannot_be_changed_once_read() -> None:
    with pytest.raises(FrozenInstanceError):
        Config().frontend = "recalbox"  # type: ignore[misc]


def test_the_version_this_reads_is_1() -> None:
    assert SCHEMA_VERSION == 1


# The file itself


def test_a_file_that_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "nope.toml"

    with pytest.raises(ConfigError, match="not found") as error:
        load(missing)

    assert str(missing) in str(error.value)


def test_a_folder_instead_of_a_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Can't read"):
        load(tmp_path)


def test_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b'schema_version = 1\n[smb]\nuser = "' + SENTINEL.encode() + b'\xff"\n')

    with pytest.raises(ConfigError, match="UTF-8") as error:
        load(path)

    assert SENTINEL not in str(error.value)


@pytest.mark.parametrize(
    "text",
    [
        "this is not toml",
        f'schema_version = 1\n[smb]\nuser = "{SENTINEL}\n',
        f"schema_version = 1\n[smb]\nuser = {SENTINEL}\n",
        f'[smb]\nuser = "{SENTINEL}"\nuser = "{SENTINEL}"\n',
    ],
    ids=["text", "unclosed-string", "bare-value", "repeated-key"],
)
def test_a_file_that_is_not_toml_says_where_and_repeats_no_value(tmp_path: Path, text: str) -> None:
    message = refused(tmp_path, text)

    assert "isn't valid TOML" in message
    assert "line" in message
    assert SENTINEL not in message


def test_a_file_nested_too_deeply_for_python(tmp_path: Path) -> None:
    message = refused(tmp_path, f"a = {'[' * 200_000}")

    assert "isn't valid TOML" in message


# schema_version


def test_a_file_with_no_version(tmp_path: Path) -> None:
    assert "schema_version: missing, expected 1" in refused(tmp_path, '[smb]\nuser = ""\n')


@pytest.mark.parametrize(
    ("value", "got"),
    [
        ('"one"', 'got "one"'),
        ("0", "got 0"),
        ("-1", "got -1"),
        ("1.0", "got 1.0"),
        ("true", "got true"),
        ("[1]", "got a list"),
    ],
)
def test_a_version_that_makes_no_sense(tmp_path: Path, value: str, got: str) -> None:
    assert f"schema_version: expected 1, {got}" in refused(tmp_path, f"schema_version = {value}\n")


def test_a_file_from_a_newer_beck_says_to_upgrade_and_nothing_else(tmp_path: Path) -> None:
    message = refused(tmp_path, "schema_version = 2\n[smb]\ntimeout = 5\nnew_setting = true\n")

    assert "schema_version 2" in message
    assert "reads up to 1" in message
    assert "Upgrade BECK" in message
    assert "new_setting" not in message


def test_a_file_from_a_newer_beck_warns_about_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    refused(tmp_path, "schema_version = 2\n[smb]\nnew_setting = true\n")

    assert caplog.records == []


# Every setting, with values it refuses


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ('[smb]\ntimeout = "ten"\n', 'smb.timeout: expected a positive integer, got "ten"'),
        ("[smb]\ntimeout = 0\n", "smb.timeout: expected a positive integer, got 0"),
        ("[smb]\ntimeout = -5\n", "smb.timeout: expected a positive integer, got -5"),
        ("[smb]\ntimeout = 1.5\n", "smb.timeout: expected a positive integer, got 1.5"),
        ("[smb]\ntimeout = true\n", "smb.timeout: expected a positive integer, got true"),
        ("[smb]\ntimeout = [1]\n", "smb.timeout: expected a positive integer, got a list"),
        ("[smb]\ntimeout = {a = 1}\n", "smb.timeout: expected a positive integer, got a table"),
        ("[smb]\ntimeout = 2026-11-06\n", "smb.timeout: expected a positive integer, got a date"),
        ("[smb]\nuser = 1234\n", "smb.user: expected text, got a number"),
        ("[smb]\nuser = 1.5\n", "smb.user: expected text, got a number"),
        ("[smb]\nuser = false\n", "smb.user: expected text, got true or false"),
        ("[target]\nfrontend = 1\n", "target.frontend: expected text, got a number"),
        ("[target]\nurl = 1\n", "target.url: expected text, got a number"),
        ("[target]\ndir = 1\n", "target.dir: expected text, got a number"),
        ("[source]\ndir = 1\n", "source.dir: expected text, got a number"),
        ('[source]\ndir = ""\n', "source.dir: expected an absolute path or one starting with ~"),
        ('[target]\ndir = ""\n', "target.dir: expected an absolute path or one starting with ~"),
        (
            '[source]\ndir = "bios"\n',
            "source.dir: expected an absolute path or one starting with ~",
        ),
        ('[target]\ndir = "./a"\n', "target.dir: expected an absolute path or one starting with ~"),
        ('[source]\ndir = "/a\\u0000b"\n', "source.dir: can't hold a NUL character"),
        ('[target]\ndir = "/a\\u0000b"\n', "target.dir: can't hold a NUL character"),
        ('[target]\nfrontend = "nope"\n', "target.frontend: that isn't a frontend BECK knows"),
        ('[target]\nurl = "http://a/b"\n', "target.url: The target must start with smb://"),
        ('[target]\nurl = ""\n', "target.url: The target must start with smb://"),
        ('[target]\nurl = "smb://host"\n', "target.url: The target has no share"),
        ('target = "smb://a/b"\n', "target: expected a table, got text"),
        ("smb = 1\n", "smb: expected a table, got a number"),
        ("source = [1]\n", "source: expected a table, got a list"),
    ],
)
def test_each_setting_says_what_is_wrong_with_it(tmp_path: Path, body: str, problem: str) -> None:
    assert problem in refused(tmp_path, versioned(body))


def test_a_url_and_a_folder_can_not_both_be_the_target(tmp_path: Path) -> None:
    message = refused(tmp_path, versioned('[target]\nurl = "smb://a/b"\ndir = "/c"\n'))

    assert "target: use url or dir, not both" in message


def test_a_home_that_cannot_be_found_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    message = refused(tmp_path, versioned('[source]\ndir = "~beck-test-no-such-user/bios"\n'))

    assert "source.dir: can't find that home folder" in message


def test_every_problem_is_reported_at_once_on_one_line(tmp_path: Path) -> None:
    path = config_file(
        tmp_path,
        """\
[target]
url = "http://a/b"
frontend = 1

[smb]
timeout = "ten"
user = 1
password = "x"

[source]
dir = "relative"
""",
    )

    with pytest.raises(ConfigError) as error:
        load(path)

    message = str(error.value)
    assert str(path) in message
    for key in (
        "schema_version:",
        "target.url:",
        "target.frontend:",
        "smb.timeout:",
        "smb.user:",
        "smb.password:",
        "source.dir:",
    ):
        assert key in message
    assert "\n" not in message, "a line break would show as \\x0a (06.11a)"


# Passwords


@pytest.mark.parametrize(
    ("body", "key"),
    [
        (f'[smb]\npassword = "{SENTINEL}"\n', "smb.password"),
        (f'[smb]\npasswd = "{SENTINEL}"\n', "smb.passwd"),
        (f'[smb]\nPassword = "{SENTINEL}"\n', "smb.Password"),
        (f'[smb]\nPASSWD = "{SENTINEL}"\n', "smb.PASSWD"),
        (f'password = "{SENTINEL}"\n', "password"),
        (f'[target]\npassword = "{SENTINEL}"\n', "target.password"),
        (f'[source]\npasswd = "{SENTINEL}"\n', "source.passwd"),
        (f'[other]\npassword = "{SENTINEL}"\n', "other.password"),
        (f'[other.deeper]\npassword = "{SENTINEL}"\n', "other.deeper.password"),
        (f'[[other]]\npassword = "{SENTINEL}"\n', "other[].password"),
        ("password = 1234\n", "password"),
    ],
)
def test_a_password_in_the_file_is_refused_and_never_repeated(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, body: str, key: str
) -> None:
    message = refused(tmp_path, versioned(body))

    assert f"{key}: passwords can't be in this file" in message
    assert "BECK_SMB_PASSWORD" in message
    assert SENTINEL not in message
    assert SENTINEL not in caplog.text


def test_a_password_in_the_url_is_refused_and_never_repeated(tmp_path: Path) -> None:
    url = f"smb://beck-test-user:{SENTINEL}@host/bios"

    message = refused(tmp_path, versioned(f'[target]\nurl = "{url}"\n'))

    assert "target.url: The target can't contain a password" in message
    assert SENTINEL not in message
    assert "beck-test-user" not in message


@pytest.mark.parametrize(
    "body",
    [
        f"[smb]\nuser = [{SENTINEL!r}]\n",
        f"[target]\nurl = [{SENTINEL!r}]\n",
        f"[source]\ndir = [{SENTINEL!r}]\n",
        f'[source]\ndir = "{SENTINEL}"\n',
        f'[target]\ndir = "{SENTINEL}"\n',
    ],
    ids=["user", "url", "source-dir", "relative-source", "relative-target"],
)
def test_a_value_in_the_wrong_place_is_not_repeated_in_case_it_is_a_password(
    tmp_path: Path, body: str
) -> None:
    assert SENTINEL not in refused(tmp_path, versioned(body))


# Settings it doesn't know


@pytest.mark.parametrize(
    ("body", "key"),
    [
        ('[smb]\nusr = "x"\n', "smb.usr"),
        ('[target]\nulr = "x"\n', "target.ulr"),
        ('[source]\ndirectory = "x"\n', "source.directory"),
        ('color = "x"\n', "color"),
        ('[other]\na = "x"\n', "other"),
    ],
)
def test_an_unknown_setting_is_a_warning_with_its_path(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, body: str, key: str
) -> None:
    path = config_file(tmp_path, versioned(body))

    with caplog.at_level(logging.WARNING, logger="beck"):
        assert load(path) == Config()

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert key in caplog.text
    assert str(path) in caplog.text


def test_an_unknown_setting_does_not_repeat_its_value(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    load(config_file(tmp_path, versioned(f'[smb]\npwd = "{SENTINEL}"\n')))

    assert "smb.pwd" in caplog.text
    assert SENTINEL not in caplog.text


def test_a_known_setting_gets_no_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    load(config_file(tmp_path, FULL))

    assert caplog.records == []


def test_an_unknown_setting_is_reported_beside_a_problem(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    refused(tmp_path, versioned('[smb]\nusr = "x"\ntimeout = 0\n'))

    assert "smb.usr" in caplog.text


@pytest.mark.parametrize(
    "body",
    ['password = "x"\n', 'PASSWD = "x"\n', '[smb]\npassword = "x"\n', '[smb]\nPasswd = "x"\n'],
)
def test_a_password_is_an_error_and_not_an_unknown_setting_too(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, body: str
) -> None:
    refused(tmp_path, versioned(body))

    assert caplog.records == []


def test_the_same_password_key_in_a_list_is_listed_once(tmp_path: Path) -> None:
    body = '[[other]]\npassword = "x"\n[[other]]\npassword = "y"\n'

    assert refused(tmp_path, versioned(body)).count("other[].password") == 1
