# SPDX-License-Identifier: GPL-3.0-only
"""No password reaches stdout, stderr or a log, on any command, in any mode (07.5)."""

import getpass
import io
import json
import logging
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest

from beck import cli, config
from beck.config import Config, Flags, find_config, resolve
from beck.errors import ConfigError
from beck.models import Plan, RunResult
from beck.output.console import ConsoleRenderer, configure_logging
from beck.redact import add_secret, forget_secrets, redact, without_url_credentials
from beck.targets import URL_FORM
from tests.factories import (
    make_bios_file,
    make_local_file,
    make_missing,
    make_report_text,
    settings_text,
)
from tests.fakes import FakeSMBConnection, FakeSMBServer, install_fake_smb

SENTINEL = "beck-test-password-sentinel"
USER = "beck-test-user-sentinel"
SERVER_URL = "smb://beck-test-server/bios"
URL_WITH_A_PASSWORD = f"smb://{USER}:{SENTINEL}@beck-test-server/bios"


@pytest.fixture(autouse=True)
def no_secrets_from_another_test() -> Iterator[None]:
    forget_secrets()
    yield
    forget_secrets()


# What redact does


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain text", "plain text"),
        ("", ""),
        (URL_WITH_A_PASSWORD, "smb://beck-test-server/bios"),
        (f"smb://{USER}@host/bios", "smb://host/bios"),
        ("smb://u:p@host:4450/bios/sub", "smb://host:4450/bios/sub"),
        ("SMB://u:p@host/bios", "SMB://host/bios"),
        ("https://u:p@example.invalid/x", "https://example.invalid/x"),
        ("smb://u:p%40ss%2Fword@host/bios", "smb://host/bios"),
        ("smb://u:p@ss@host/bios", "smb://host/bios"),
        ("before smb://u:p@a/s after smb://v:q@b/t end", "before smb://a/s after smb://b/t end"),
        ("smb://host/bios", "smb://host/bios"),
        ("smb://host:445/bios", "smb://host:445/bios"),
        ("smb://host/bios/a@b.bin", "smb://host/bios/a@b.bin"),
        ("file:///home/me/a@b.bin", "file:///home/me/a@b.bin"),
        ("me@example.invalid", "me@example.invalid"),
        ("see smb://host and me@example.invalid", "see smb://host and me@example.invalid"),
        ("a ratio of 1:2@3", "a ratio of 1:2@3"),
        ("Can't read 'smb://u:p@h/s': no", "Can't read 'smb://h/s': no"),
    ],
)
def test_a_url_never_keeps_its_credentials(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_a_url_in_the_place_of_a_path_loses_its_credentials_before_it_is_a_path() -> None:
    """Path turns smb:// into smb:/, and as_uri encodes the rest, so it can't be done afterwards."""
    url = URL_WITH_A_PASSWORD
    flags = Flags(source=url, target_dir=url)

    settings = resolve(flags, {}, Config())

    assert SENTINEL not in str(settings.source_dir)
    assert SENTINEL not in str(settings.target_dir)
    assert USER not in str(settings.target_dir)
    assert SENTINEL not in str(find_config(url, {}).path)


@pytest.mark.parametrize(
    ("name", "field"),
    [("BECK_SOURCE", "source_dir"), ("BECK_TARGET_DIR", "target_dir")],
)
def test_a_url_in_a_variable_for_a_folder_loses_its_credentials_too(name: str, field: str) -> None:
    settings = resolve(Flags(), {name: URL_WITH_A_PASSWORD}, Config())

    assert SENTINEL not in str(getattr(settings, field))


def test_a_url_in_the_variable_for_the_settings_file_loses_its_credentials_too() -> None:
    assert SENTINEL not in str(find_config(None, {"BECK_CONFIG": URL_WITH_A_PASSWORD}).path)


def test_an_ordinary_path_is_left_alone() -> None:
    assert without_url_credentials("/home/me/a@b/bios") == "/home/me/a@b/bios"
    assert resolve(Flags(source="/home/me/a@b"), {}, Config()).source_dir == Path("/home/me/a@b")


def test_a_path_holding_the_password_still_means_that_path() -> None:
    """Masking is for what's shown: it can't change which folder BECK reads."""
    add_secret("secret")

    assert resolve(Flags(source="/home/secret/bios"), {}, Config()).source_dir == Path(
        "/home/secret/bios"
    )


def test_a_password_it_knows_is_masked_wherever_it_is() -> None:
    add_secret(SENTINEL)

    assert redact(f"before {SENTINEL} and {SENTINEL}") == "before *** and ***"


def test_nothing_is_masked_until_it_knows_a_password() -> None:
    assert redact(SENTINEL) == SENTINEL


def test_an_empty_password_masks_nothing() -> None:
    add_secret("")

    assert redact("some text") == "some text"


def test_the_longest_password_goes_first_so_no_part_of_it_stays() -> None:
    add_secret("secret")
    add_secret("secret-and-more")

    assert redact("secret-and-more") == "***"


def test_forgetting_means_it_masks_nothing_again() -> None:
    add_secret(SENTINEL)
    forget_secrets()

    assert redact(SENTINEL) == SENTINEL


# Every command, in every mode, with the password in the environment


def run_with_a_report(server: FakeSMBServer, folder: Path) -> list[str]:
    data = make_bios_file(folder / "source", "good.bin")
    server.files[("bios", "missing_bios_report.txt")] = make_report_text(
        [make_missing("ps1/good.bin", data.md5), make_missing("gone.bin", "a" * 32)]
    ).encode()
    return ["check", "--source", str(folder / "source")]


def check_uploads(server: FakeSMBServer, folder: Path) -> list[str]:
    return run_with_a_report(server, folder)


def check_dry_run(server: FakeSMBServer, folder: Path) -> list[str]:
    return [*run_with_a_report(server, folder), "--dry-run"]


def check_fails_if_missing(server: FakeSMBServer, folder: Path) -> list[str]:
    return [*run_with_a_report(server, folder), "--fail-if-missing"]


def check_refused_login(server: FakeSMBServer, folder: Path) -> list[str]:
    server.login_succeeds = False
    return run_with_a_report(server, folder)


def check_holds_back_a_file_that_is_not_a_zip(server: FakeSMBServer, folder: Path) -> list[str]:
    data = make_bios_file(folder / "source", "neocd.bin")
    server.files[("bios", "missing_bios_report.txt")] = make_report_text(
        [make_missing("neocdz.zip", data.md5)]
    ).encode()
    return ["check", "--source", str(folder / "source")]


def check_with_the_web_api(server: FakeSMBServer, folder: Path) -> list[str]:
    data = make_bios_file(folder / "source", "good.bin")
    entry = {
        "mandatory": True,
        "hashMatchingMandatory": True,
        "currentMd5": "0" * 32,
        "md5List": [data.md5],
        "realStatus": "FileNotFound",
    }
    server.api_answer = json.dumps(
        {"ps1": {"fullName": "Sony Playstation", "biosList": {"ps1/good.bin": entry}}}
    ).encode()
    return ["check", "--source", str(folder / "source")]


def check_no_report(server: FakeSMBServer, folder: Path) -> list[str]:
    (folder / "source").mkdir()
    return ["check", "--source", str(folder / "source")]


def check_unknown_share(server: FakeSMBServer, folder: Path) -> list[str]:
    (folder / "source").mkdir()
    return ["check", "--source", str(folder / "source"), "--target", "smb://host/no-such-share"]


def report_works(server: FakeSMBServer, folder: Path) -> list[str]:
    run_with_a_report(server, folder)
    return ["report"]


def report_refused_login(server: FakeSMBServer, folder: Path) -> list[str]:
    server.login_succeeds = False
    return ["report"]


def scan_works(server: FakeSMBServer, folder: Path) -> list[str]:
    make_bios_file(folder / "source", "a.bin")
    return ["scan", "--source", str(folder / "source")]


def export_works(server: FakeSMBServer, folder: Path) -> list[str]:
    server.files[("bios", "a.bin")] = b"beck-test-bytes"
    return ["export", str(folder / "out")]


def export_dry_run(server: FakeSMBServer, folder: Path) -> list[str]:
    return [*export_works(server, folder), "--dry-run"]


def export_refused_login(server: FakeSMBServer, folder: Path) -> list[str]:
    server.login_succeeds = False
    return export_works(server, folder)


def scan_no_folder(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["scan", "--source", str(folder / "nope")]


def config_path(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["config", "path"]


def config_show(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["config", "show"]


def config_init_refused(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["config", "init"]


def config_init_forced(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["config", "init", "--force"]


def a_stray_url(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["check", URL_WITH_A_PASSWORD]


def a_url_with_a_password_as_the_target(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["check", "--target", URL_WITH_A_PASSWORD]


def a_url_with_a_password_as_the_source(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["scan", "--source", URL_WITH_A_PASSWORD]


def a_url_with_a_password_as_the_report_file(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["report", "--report-file", URL_WITH_A_PASSWORD]


def a_url_with_a_password_as_the_target_folder(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["report", "--target-dir", URL_WITH_A_PASSWORD]


def a_url_with_a_password_as_the_settings_file(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["config", "show", "--config", URL_WITH_A_PASSWORD]


def a_url_with_a_password_as_the_frontend(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["check", "--frontend", URL_WITH_A_PASSWORD]


def the_same_when_the_settings_file_stops_the_run(server: FakeSMBServer, folder: Path) -> list[str]:
    return ["check", "--frontend", URL_WITH_A_PASSWORD, "--config", str(folder / "nope.toml")]


SCENARIOS: list[Callable[[FakeSMBServer, Path], list[str]]] = [
    check_uploads,
    check_dry_run,
    check_fails_if_missing,
    check_refused_login,
    check_holds_back_a_file_that_is_not_a_zip,
    check_with_the_web_api,
    check_no_report,
    check_unknown_share,
    report_works,
    report_refused_login,
    scan_works,
    scan_no_folder,
    export_works,
    export_dry_run,
    export_refused_login,
    config_path,
    config_show,
    config_init_refused,
    config_init_forced,
    a_stray_url,
    a_url_with_a_password_as_the_target,
    a_url_with_a_password_as_the_source,
    a_url_with_a_password_as_the_report_file,
    a_url_with_a_password_as_the_target_folder,
    a_url_with_a_password_as_the_settings_file,
    a_url_with_a_password_as_the_frontend,
    the_same_when_the_settings_file_stops_the_run,
]
MODES = {
    "human": [],
    "verbose": ["-v"],
    "quiet": ["-q"],
    "json": ["--json"],
    "json-verbose": ["--json", "-v"],
}


@pytest.fixture
def account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    settings = tmp_path / "settings.toml"
    settings.write_text(settings_text(SERVER_URL, USER), encoding="utf-8")
    settings.chmod(0o600)
    monkeypatch.setenv("BECK_CONFIG", str(settings))
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)
    return tmp_path


@pytest.mark.parametrize("masking", ["with-the-mask", "without-the-mask"])
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_no_output_ever_holds_the_password(
    account: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    scenario: Callable[[FakeSMBServer, Path], list[str]],
    mode: str,
    masking: str,
) -> None:
    """Without the mask too, so that no path relies on it to hide a password it shouldn't print."""
    if masking == "without-the-mask":
        monkeypatch.setattr(cli, "add_secret", lambda _value: None)
    server = install_fake_smb(monkeypatch)
    arguments = scenario(server, account)

    with caplog.at_level(logging.DEBUG, logger="beck"):
        try:
            cli.main([*MODES[mode], *arguments], base_dir=account)
        except SystemExit as stop:
            assert stop.code == 2  # argparse, with no --json

    out = capsys.readouterr()
    assert SENTINEL not in out.out, "on stdout"
    assert SENTINEL not in out.err, "on stderr"
    assert SENTINEL not in caplog.text, "in a log record"
    for record in caplog.records:
        assert SENTINEL not in record.getMessage()


def test_the_password_typed_at_the_prompt_is_kept_out_too(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = install_fake_smb(monkeypatch)
    server.files[("bios", "missing_bios_report.txt")] = make_report_text([]).encode()
    monkeypatch.setattr(sys, "stdin", type("Keyboard", (), {"isatty": lambda _self: True})())
    monkeypatch.setattr(getpass, "getpass", lambda _prompt="": SENTINEL)
    url = f"smb://{USER}@beck-test-server/bios"

    with caplog.at_level(logging.DEBUG, logger="beck"):
        assert cli.main(["-v", "report", "--target", url], base_dir=tmp_path) == 0

    out = capsys.readouterr()
    assert SENTINEL not in out.out + out.err + caplog.text
    assert (server.connections[0].password,) == (SENTINEL,), "it still reaches the server"


# When something else repeats the password: a library's error message, or a bug


def fail_with_the_password(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise OSError(f"the server said no to {SENTINEL}")


@pytest.mark.parametrize("step", ["connect", "storeFile", "retrieveFile"])
@pytest.mark.parametrize("mode", ["human", "json"])
def test_a_library_that_repeats_the_password_is_masked(
    account: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    step: str,
    mode: str,
) -> None:
    server = install_fake_smb(monkeypatch)
    arguments = run_with_a_report(server, account)
    monkeypatch.setattr(FakeSMBConnection, step, fail_with_the_password)

    assert cli.main([*MODES[mode], *arguments], base_dir=account) == 3

    out = capsys.readouterr()
    assert SENTINEL not in out.out + out.err
    assert "the server said no to ***" in out.out


def test_a_library_that_repeats_a_typed_password_is_masked_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_smb(monkeypatch)
    monkeypatch.setattr(FakeSMBConnection, "connect", fail_with_the_password)
    monkeypatch.setattr(sys, "stdin", type("Keyboard", (), {"isatty": lambda _self: True})())
    monkeypatch.setattr(getpass, "getpass", lambda _prompt="": SENTINEL)
    url = f"smb://{USER}@beck-test-server/bios"

    assert cli.main(["report", "--target", url], base_dir=tmp_path) == 3

    out = capsys.readouterr()
    assert "the server said no to ***" in out.out
    assert SENTINEL not in out.out + out.err


def test_a_log_line_that_holds_the_password_is_masked(capsys: pytest.CaptureFixture[str]) -> None:
    add_secret(SENTINEL)

    configure_logging().warning("something with %s", SENTINEL)

    assert capsys.readouterr().err == "something with ***\n"


def test_a_failed_upload_in_json_is_masked_in_both_places(
    account: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = install_fake_smb(monkeypatch)
    arguments = run_with_a_report(server, account)
    monkeypatch.setattr(FakeSMBConnection, "storeFile", fail_with_the_password)

    assert cli.main(["--json", *arguments], base_dir=account) == 3

    document = json.loads(capsys.readouterr().out)
    assert "***" in document["errors"][0]["message"]
    assert "***" in document["uploads"][0]["error"]


def test_a_bug_that_holds_the_password_is_masked_in_its_traceback(
    account: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = install_fake_smb(monkeypatch)
    arguments = run_with_a_report(server, account)

    def a_bug(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError(f"a bug holding {SENTINEL}")

    monkeypatch.setattr(cli, "execute", a_bug)

    assert cli.main(arguments, base_dir=account) == 1

    err = capsys.readouterr().err
    assert "Traceback" in err
    assert "RuntimeError: a bug holding ***" in err
    assert SENTINEL not in err


def test_the_list_of_a_prompt_is_masked_too(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    add_secret(SENTINEL)
    preview = RunResult(plan=Plan(), deleted=(make_local_file(f"{SENTINEL}.bin", "a" * 32),))
    monkeypatch.setattr(sys, "stdin", io.StringIO("n\n"))

    assert ConsoleRenderer(io.StringIO(), {}).confirm_deletion(preview) is False

    err = capsys.readouterr().err
    assert "***.bin" in err
    assert SENTINEL not in err


def test_each_run_starts_knowing_no_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing here depends on it in real use, but in tests a run must not hide the next one's."""
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)
    assert cli.main(["scan", "--source", str(tmp_path)]) == 0
    monkeypatch.delenv("BECK_SMB_PASSWORD")

    assert cli.main(["scan", "--source", str(tmp_path / SENTINEL)]) == 2

    assert SENTINEL in capsys.readouterr().out


# What stays exact


def test_json_keeps_the_exact_file_name_even_if_it_holds_the_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """It's the user's own file, and a script needs the real name."""
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)
    make_bios_file(tmp_path, f"{SENTINEL}.bin")

    assert cli.main(["--json", "scan", "--source", str(tmp_path)]) == 0

    assert json.loads(capsys.readouterr().out)["files"][0]["path"] == f"{SENTINEL}.bin"


def test_people_see_the_file_name_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)
    make_bios_file(tmp_path, f"{SENTINEL}.bin")

    assert cli.main(["scan", "--source", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "***.bin" in out
    assert SENTINEL not in out


def test_colors_still_go_on_around_masked_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)
    folder = tmp_path / SENTINEL
    folder.mkdir()

    assert cli.main(["scan", "--source", str(folder)]) == 0

    out = capsys.readouterr().out
    assert "***" in out
    assert out.startswith("\x1b[36m")
    assert out.rstrip().endswith("\x1b[0m")


# A value in the wrong place in the settings file


def test_a_frontend_in_the_settings_file_is_not_repeated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "settings.toml"
    settings.write_text(f'schema_version = 1\n[target]\nfrontend = "{SENTINEL}"\n')

    assert cli.main(["config", "show", "--config", str(settings)]) == 2

    out = capsys.readouterr().out
    assert SENTINEL not in out
    assert "target.frontend" in out
    assert "recalbox" in out, "it says which ones it knows"


# Who can read the settings file


needs_posix = pytest.mark.skipif(os.name != "posix", reason="only POSIX has these permissions")


@needs_posix
@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o660, 0o666, 0o400 | 0o040])
def test_a_file_others_can_read_gets_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, mode: int
) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("schema_version = 1\n", encoding="utf-8")
    path.chmod(mode)

    config.load(path)

    assert str(path) in caplog.text
    assert "can read" in caplog.text
    assert "chmod 600" in caplog.text


@needs_posix
@pytest.mark.parametrize("mode", [0o600, 0o400, 0o700, 0o601, 0o610, 0o622])
def test_a_file_only_its_owner_can_read_gets_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, mode: int
) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("schema_version = 1\n", encoding="utf-8")
    path.chmod(mode)

    config.load(path)

    assert caplog.records == []


def test_other_systems_get_no_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "IS_POSIX", False)
    path = tmp_path / "settings.toml"
    path.write_text("schema_version = 1\n", encoding="utf-8")
    path.chmod(0o644)

    config.load(path)

    assert caplog.records == []


def test_a_file_that_goes_away_gets_no_warning_and_no_crash(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("schema_version = 1\n", encoding="utf-8")
    real_stat = Path.stat

    def gone(self: Path, **kwargs: Any) -> os.stat_result:
        if self == path:
            raise FileNotFoundError(2, "No such file")
        return real_stat(self, **kwargs)

    monkeypatch.setattr(Path, "stat", gone)

    assert config.load(path) == Config()
    assert caplog.records == []


def test_the_warning_is_on_stderr_and_a_document_stays_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("schema_version = 1\n", encoding="utf-8")
    path.chmod(0o644)

    assert cli.main(["--json", "config", "show", "--config", str(path)]) == 0

    out = capsys.readouterr()
    assert json.loads(out.out)["ok"] is True
    assert "can read" in out.err


@needs_posix
def test_config_init_writes_a_file_that_gets_no_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "settings.toml"
    assert cli.main(["config", "init", "--config", str(path)]) == 0
    capsys.readouterr()

    assert cli.main(["config", "show", "--config", str(path)]) == 0

    assert capsys.readouterr().err == ""


def test_config_path_does_not_read_the_file_so_it_does_not_warn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("schema_version = 1\n", encoding="utf-8")
    path.chmod(0o644)

    assert cli.main(["config", "path", "--config", str(path)]) == 0

    assert capsys.readouterr().err == ""


def test_a_problem_in_the_file_still_gets_the_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("[smb]\ntimeout = 0\n", encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(ConfigError):
        config.load(path)

    assert "can read" in caplog.text


# BECK's own words


def test_the_form_of_a_target_url_is_not_mistaken_for_credentials() -> None:
    assert redact(f"Use {URL_FORM}") == f"Use {URL_FORM}"


@pytest.mark.parametrize(
    "url",
    ["http://beck-test-server/bios", "smb://", "smb://user:beck-test-password@host/bios"],
    ids=["scheme", "no-host", "password"],
)
@pytest.mark.parametrize("mode", [[], ["--json"]], ids=["human", "json"])
def test_an_error_about_a_target_shows_its_form_whole(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: list[str], url: str
) -> None:
    assert cli.main([*mode, "check", "--target", url], base_dir=tmp_path) == 2

    assert URL_FORM in capsys.readouterr().out


def test_a_url_with_a_password_says_what_to_do_instead(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"smb://user:{SENTINEL}@beck-test-server/bios"

    assert cli.main(["check", "--target", url], base_dir=tmp_path) == 2

    out = capsys.readouterr().out
    assert "BECK_SMB_PASSWORD" in out
    assert "later version" not in out
