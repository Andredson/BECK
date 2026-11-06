# SPDX-License-Identifier: GPL-3.0-only
"""Where an SMB password comes from: the environment or a prompt, and nowhere else (DEC-10)."""

import getpass
import json
import sys
import warnings
from pathlib import Path
from typing import Any, NoReturn

import pytest

from beck import cli, credentials
from beck.credentials import password_for
from beck.errors import ConfigError
from tests.factories import make_report_text, settings_text
from tests.fakes import FakeSMBServer, install_fake_smb

SENTINEL = "beck-test-password-sentinel"
USER_URL = "smb://beck-test-user@beck-test-server/bios"
GUEST_URL = "smb://beck-test-server/bios"


def must_not_ask(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("this must not ask for a password")


def answer(text: str, asked: list[str] | None = None) -> Any:
    def ask(prompt: str = "") -> str:
        if asked is not None:
            asked.append(prompt)
        return text

    return ask


def raising(error: BaseException) -> Any:
    def ask(prompt: str = "") -> NoReturn:
        raise error

    return ask


class Terminal:
    """A terminal on stdin. BECK never reads the password from here: getpass does."""

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        raise AssertionError("a password isn't read from stdin")


@pytest.fixture
def on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", Terminal())


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeSMBServer:
    fake = install_fake_smb(monkeypatch)
    fake.files[("bios", "missing_bios_report.txt")] = make_report_text([]).encode()
    return fake


# The four cases


def test_no_user_is_a_guest_with_no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getpass", must_not_ask)

    assert password_for("", "host", "", can_ask=True) == ""


def test_a_guest_never_sends_the_password_it_was_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getpass", must_not_ask)

    assert password_for("", "host", SENTINEL, can_ask=True) == ""


def test_a_user_with_a_password_set_uses_it_and_asks_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(getpass, "getpass", must_not_ask)

    assert password_for("user", "host", SENTINEL, can_ask=True) == SENTINEL
    assert password_for("user", "host", SENTINEL, can_ask=False) == SENTINEL


def test_a_user_with_no_password_is_asked_on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getpass", answer(SENTINEL))

    assert password_for("user", "host", "", can_ask=True) == SENTINEL


def test_a_user_with_no_password_and_no_terminal_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(getpass, "getpass", must_not_ask)

    with pytest.raises(ConfigError) as error:
        password_for("user", "host", "", can_ask=False)

    assert error.value.exit_code == 2
    assert "BECK_SMB_PASSWORD" in str(error.value)
    assert "user" not in str(error.value).replace("A user", "")


# Asking


def test_the_prompt_says_who_and_where(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    monkeypatch.setattr(getpass, "getpass", answer("x", asked))

    password_for("me", "recalbox.local", "", can_ask=True)

    assert asked == ["Password for me on recalbox.local: "]


def test_the_prompt_can_not_act_on_the_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both come from settings, which can hold anything, and this goes to the terminal (D24)."""
    asked: list[str] = []
    monkeypatch.setattr(getpass, "getpass", answer("x", asked))

    password_for("me\x1b[2J", "host\x07", "", can_ask=True)

    assert asked == ["Password for me\\x1b[2J on host\\x07: "]


def test_an_empty_answer_is_an_empty_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getpass", answer(""))

    assert password_for("user", "host", "", can_ask=True) == ""


@pytest.mark.parametrize(
    "error",
    [EOFError(), KeyboardInterrupt()],
    ids=["ctrl-d", "ctrl-c"],
)
def test_giving_no_answer_is_a_refusal_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: BaseException
) -> None:
    monkeypatch.setattr(getpass, "getpass", raising(error))

    with pytest.raises(ConfigError, match="no password was given"):
        password_for("user", "host", "", can_ask=True)

    assert capsys.readouterr().err == "\n", "the error can't start at the end of the prompt"


@pytest.mark.parametrize(
    "error",
    [
        OSError(5, "Input/output error"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
    ids=["terminal-gone", "bytes-that-are-not-text"],
)
def test_an_answer_that_can_not_be_read_is_a_refusal_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    monkeypatch.setattr(getpass, "getpass", raising(error))

    with pytest.raises(ConfigError, match="BECK_SMB_PASSWORD"):
        password_for("user", "host", "", can_ask=True)


def test_it_refuses_to_ask_if_the_answer_would_show_on_the_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """getpass only warns when it can't turn off the echo, and then reads the password anyway."""

    def echoing(prompt: str = "") -> str:
        warnings.warn("Can not control echo on the terminal.", getpass.GetPassWarning, stacklevel=2)
        raise AssertionError("it went on to read a password that would show")

    monkeypatch.setattr(getpass, "getpass", echoing)

    with pytest.raises(ConfigError, match="BECK_SMB_PASSWORD"):
        password_for("user", "host", "", can_ask=True)


# Through the command


def test_a_url_with_a_user_on_a_terminal_asks_and_connects(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(getpass, "getpass", answer(SENTINEL))

    assert cli.main(["report", "--target", USER_URL], base_dir=tmp_path) == 0

    connection = server.connections[0]
    assert (connection.username, connection.password) == ("beck-test-user", SENTINEL)
    out = capsys.readouterr()
    assert SENTINEL not in out.out + out.err


def test_a_user_in_the_settings_file_asks_too(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
) -> None:
    settings = tmp_path / "settings.toml"
    settings.write_text(settings_text(GUEST_URL, "file-user"), encoding="utf-8")
    monkeypatch.setattr(getpass, "getpass", answer(SENTINEL))

    assert cli.main(["report", "--config", str(settings)], base_dir=tmp_path) == 0

    connection = server.connections[0]
    assert (connection.username, connection.password) == ("file-user", SENTINEL)


def test_a_user_in_the_environment_asks_too(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
) -> None:
    monkeypatch.setenv("BECK_SMB_USER", "env-user")
    monkeypatch.setattr(getpass, "getpass", answer(SENTINEL))

    assert cli.main(["report", "--target", GUEST_URL], base_dir=tmp_path) == 0

    connection = server.connections[0]
    assert (connection.username, connection.password) == ("env-user", SENTINEL)


def test_it_asks_once_for_a_whole_run(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(getpass, "getpass", answer(SENTINEL, asked))
    source = tmp_path / "source"
    source.mkdir()

    assert cli.main(["check", "--source", str(source), "--target", USER_URL]) == 0

    assert len(asked) == 1


def test_a_dry_run_asks_too_because_it_connects(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(getpass, "getpass", answer(SENTINEL, asked))
    source = tmp_path / "source"
    source.mkdir()

    arguments = ["check", "--dry-run", "--source", str(source), "--target", USER_URL]
    assert cli.main(arguments) == 0

    assert len(asked) == 1


def test_a_variable_means_it_does_not_ask(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
) -> None:
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)
    monkeypatch.setattr(getpass, "getpass", must_not_ask)

    assert cli.main(["report", "--target", USER_URL], base_dir=tmp_path) == 0

    assert server.connections[0].password == SENTINEL


def test_an_empty_variable_counts_as_not_set_so_it_asks(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
) -> None:
    monkeypatch.setenv("BECK_SMB_PASSWORD", "")
    monkeypatch.setattr(getpass, "getpass", answer(SENTINEL))

    assert cli.main(["report", "--target", USER_URL], base_dir=tmp_path) == 0

    assert server.connections[0].password == SENTINEL


def test_a_guest_on_a_terminal_is_not_asked(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
) -> None:
    monkeypatch.setattr(getpass, "getpass", must_not_ask)

    assert cli.main(["report", "--target", GUEST_URL], base_dir=tmp_path) == 0


def test_a_folder_needs_no_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on_a_terminal: None
) -> None:
    monkeypatch.setattr(getpass, "getpass", must_not_ask)
    monkeypatch.setenv("BECK_SMB_USER", "env-user")
    (tmp_path / "missing_bios_report.txt").write_text(make_report_text([]), encoding="utf-8")

    assert cli.main(["report", "--target-dir", str(tmp_path)]) == 0


@pytest.mark.parametrize(
    "arguments",
    [["config", "show"], ["config", "path"], ["report", "--report-file", "{report}"]],
    ids=["config-show", "config-path", "report-file"],
)
def test_what_does_not_connect_does_not_ask(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
    arguments: list[str],
) -> None:
    monkeypatch.setenv("BECK_TARGET", USER_URL)
    monkeypatch.setattr(getpass, "getpass", must_not_ask)
    report = tmp_path / "report.txt"
    report.write_text(make_report_text([]), encoding="utf-8")
    filled = [argument.replace("{report}", str(report)) for argument in arguments]

    assert cli.main(filled, base_dir=tmp_path) == 0

    assert server.connections == []


def test_no_terminal_exits_2_and_never_connects(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(getpass, "getpass", must_not_ask)

    assert cli.main(["report", "--target", USER_URL], base_dir=tmp_path) == 2

    assert "BECK_SMB_PASSWORD" in capsys.readouterr().out
    assert server.connections == []


def test_json_never_asks_even_on_a_terminal(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(getpass, "getpass", must_not_ask)

    assert cli.main(["--json", "report", "--target", USER_URL], base_dir=tmp_path) == 2

    document = json.loads(capsys.readouterr().out)
    assert document["errors"][0]["code"] == "config"
    assert "BECK_SMB_PASSWORD" in document["errors"][0]["message"]
    assert server.connections == []


def test_json_with_the_variable_needs_no_terminal(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)

    assert cli.main(["--json", "report", "--target", USER_URL], base_dir=tmp_path) == 0

    assert SENTINEL not in capsys.readouterr().out


def test_ctrl_c_at_the_prompt_exits_2_with_no_traceback(
    server: FakeSMBServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_terminal: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(getpass, "getpass", raising(KeyboardInterrupt()))

    assert cli.main(["report", "--target", USER_URL], base_dir=tmp_path) == 2

    out = capsys.readouterr()
    assert "no password was given" in out.out
    assert "Traceback" not in out.err
    assert server.connections == []


def test_the_module_keeps_no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getpass", answer(SENTINEL))

    password_for("user", "host", "", can_ask=True)

    for name, value in vars(credentials).items():
        assert value != SENTINEL, name
