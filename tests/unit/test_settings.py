# SPDX-License-Identifier: GPL-3.0-only
"""Which file BECK reads, and which source wins: flags, then the environment, then the file."""

import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from beck import cli, config, frontends
from beck.config import Config, ConfigLocation, Flags, Settings, find_config, resolve
from beck.errors import ConfigError
from beck.frontends.recalbox import RecalboxAdapter
from tests.conftest import NO_SETTINGS_FOLDER, SETTINGS_VARIABLES
from tests.factories import make_bios_file, make_missing, make_report_text
from tests.fakes import FakeSMBServer, install_fake_smb

SENTINEL = "beck-test-password-sentinel"


def settings(**kwargs: Any) -> Settings:
    """What resolve gives when nothing is set, with these changes."""
    defaults: dict[str, Any] = {
        "target_url": None,
        "target_dir": None,
        "source_dir": None,
        "frontend": "recalbox",
        "smb_user": "",
        "smb_timeout": None,
    }
    return Settings(**{**defaults, **kwargs})


# Every setting, with each source over the ones below it

FLAG_URL, ENV_URL, FILE_URL = "smb://flag/bios", "smb://env/bios", "smb://file/bios"
FLAG_DIR, ENV_DIR, FILE_DIR = "/flag", "/env", "/file"


@pytest.mark.parametrize(
    ("flags", "environ", "file", "expected"),
    [
        # Nothing set
        (Flags(), {}, Config(), settings()),
        # The target as a URL, with each source over the ones below it
        (Flags(), {}, Config(target_url=FILE_URL), settings(target_url=FILE_URL)),
        (
            Flags(),
            {"BECK_TARGET": ENV_URL},
            Config(target_url=FILE_URL),
            settings(target_url=ENV_URL),
        ),
        (
            Flags(target=FLAG_URL),
            {"BECK_TARGET": ENV_URL},
            Config(target_url=FILE_URL),
            settings(target_url=FLAG_URL),
        ),
        # The target as a folder
        (Flags(), {}, Config(target_dir=Path(FILE_DIR)), settings(target_dir=Path(FILE_DIR))),
        (
            Flags(),
            {"BECK_TARGET_DIR": ENV_DIR},
            Config(target_dir=Path(FILE_DIR)),
            settings(target_dir=Path(ENV_DIR)),
        ),
        (
            Flags(target_dir=FLAG_DIR),
            {"BECK_TARGET_DIR": ENV_DIR},
            Config(target_dir=Path(FILE_DIR)),
            settings(target_dir=Path(FLAG_DIR)),
        ),
        # A target is one setting, so a higher source wins even in the other form
        (
            Flags(target=FLAG_URL),
            {"BECK_TARGET_DIR": ENV_DIR},
            Config(),
            settings(target_url=FLAG_URL),
        ),
        (
            Flags(target=FLAG_URL),
            {},
            Config(target_dir=Path(FILE_DIR)),
            settings(target_url=FLAG_URL),
        ),
        (
            Flags(target_dir=FLAG_DIR),
            {"BECK_TARGET": ENV_URL},
            Config(),
            settings(target_dir=Path(FLAG_DIR)),
        ),
        (
            Flags(target_dir=FLAG_DIR),
            {},
            Config(target_url=FILE_URL),
            settings(target_dir=Path(FLAG_DIR)),
        ),
        (
            Flags(),
            {"BECK_TARGET": ENV_URL},
            Config(target_dir=Path(FILE_DIR)),
            settings(target_url=ENV_URL),
        ),
        (
            Flags(),
            {"BECK_TARGET_DIR": ENV_DIR},
            Config(target_url=FILE_URL),
            settings(target_dir=Path(ENV_DIR)),
        ),
        # The source
        (Flags(), {}, Config(source_dir=Path(FILE_DIR)), settings(source_dir=Path(FILE_DIR))),
        (
            Flags(),
            {"BECK_SOURCE": ENV_DIR},
            Config(source_dir=Path(FILE_DIR)),
            settings(source_dir=Path(ENV_DIR)),
        ),
        (
            Flags(source=FLAG_DIR),
            {"BECK_SOURCE": ENV_DIR},
            Config(source_dir=Path(FILE_DIR)),
            settings(source_dir=Path(FLAG_DIR)),
        ),
        # The frontend: there's no variable for it
        (Flags(), {}, Config(frontend="file"), settings(frontend="file")),
        (Flags(frontend="flag"), {}, Config(frontend="file"), settings(frontend="flag")),
        # The user: there's no flag for it, and an empty variable means a guest
        (Flags(), {}, Config(smb_user="file"), settings(smb_user="file")),
        (
            Flags(),
            {"BECK_SMB_USER": "env"},
            Config(smb_user="file"),
            settings(smb_user="env"),
        ),
        (Flags(), {"BECK_SMB_USER": ""}, Config(smb_user="file"), settings(smb_user="")),
        # The timeout: only the file sets it
        (Flags(), {}, Config(smb_timeout=5), settings(smb_timeout=5)),
    ],
)
def test_each_source_wins_over_the_ones_below_it(
    flags: Flags, environ: dict[str, str], file: Config, expected: Settings
) -> None:
    assert resolve(flags, environ, file) == expected


@pytest.mark.parametrize(
    ("name", "field", "file"),
    [
        ("BECK_TARGET", "target_url", Config(target_url=FILE_URL)),
        ("BECK_TARGET_DIR", "target_dir", Config(target_dir=Path(FILE_DIR))),
        ("BECK_SOURCE", "source_dir", Config(source_dir=Path(FILE_DIR))),
    ],
)
def test_an_empty_variable_counts_as_not_set(name: str, field: str, file: Config) -> None:
    assert getattr(resolve(Flags(), {name: ""}, file), field) == getattr(file, field)


@pytest.mark.parametrize(
    ("flags", "environ", "file", "name", "source"),
    [
        (Flags(), {}, Config(), "target", "default"),
        (Flags(), {}, Config(target_url=FILE_URL), "target", "file"),
        (Flags(), {}, Config(target_dir=Path(FILE_DIR)), "target", "file"),
        (Flags(), {"BECK_TARGET": ENV_URL}, Config(target_url=FILE_URL), "target", "environment"),
        (Flags(), {"BECK_TARGET_DIR": ENV_DIR}, Config(), "target", "environment"),
        (Flags(target=FLAG_URL), {"BECK_TARGET": ENV_URL}, Config(), "target", "flag"),
        (Flags(target_dir=FLAG_DIR), {"BECK_TARGET": ENV_URL}, Config(), "target", "flag"),
        (Flags(), {}, Config(), "source", "default"),
        (Flags(), {}, Config(source_dir=Path(FILE_DIR)), "source", "file"),
        (Flags(), {"BECK_SOURCE": ""}, Config(source_dir=Path(FILE_DIR)), "source", "file"),
        (Flags(), {"BECK_SOURCE": ENV_DIR}, Config(), "source", "environment"),
        (Flags(source=FLAG_DIR), {"BECK_SOURCE": ENV_DIR}, Config(), "source", "flag"),
        (Flags(), {}, Config(), "frontend", "default"),
        (Flags(), {}, Config(frontend="file"), "frontend", "file"),
        (Flags(frontend="flag"), {}, Config(frontend="file"), "frontend", "flag"),
        (Flags(), {}, Config(), "smb_user", "default"),
        (Flags(), {}, Config(smb_user="file"), "smb_user", "file"),
        (Flags(), {"BECK_SMB_USER": ""}, Config(smb_user="file"), "smb_user", "environment"),
        (Flags(), {}, Config(), "smb_password", "default"),
        (Flags(), {"BECK_SMB_PASSWORD": ""}, Config(), "smb_password", "default"),
        (Flags(), {"BECK_SMB_PASSWORD": SENTINEL}, Config(), "smb_password", "environment"),
        (Flags(), {}, Config(), "smb_timeout", "default"),
        (Flags(), {}, Config(smb_timeout=5), "smb_timeout", "file"),
    ],
)
def test_each_setting_says_where_it_came_from(
    flags: Flags, environ: dict[str, str], file: Config, name: str, source: str
) -> None:
    assert resolve(flags, environ, file).sources[name] == source


def test_settings_can_be_compared_whatever_their_sources_say() -> None:
    assert resolve(Flags(), {}, Config(frontend="recalbox")) == resolve(Flags(), {}, Config())


def test_the_password_comes_only_from_its_variable() -> None:
    assert resolve(Flags(), {"BECK_SMB_PASSWORD": SENTINEL}, Config()).smb_password == SENTINEL
    assert resolve(Flags(), {}, Config()).smb_password == ""


def test_printing_the_settings_can_not_show_the_password() -> None:
    settings_with_a_password = resolve(Flags(), {"BECK_SMB_PASSWORD": SENTINEL}, Config())

    assert SENTINEL not in repr(settings_with_a_password)
    assert SENTINEL not in str(settings_with_a_password)
    assert SENTINEL not in f"{settings_with_a_password}"


def test_resolve_reads_only_what_it_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BECK_TARGET", "smb://from-the-real-environment/bios")
    monkeypatch.setenv("BECK_SOURCE", "/from-the-real-environment")

    assert resolve(Flags(), {}, Config()) == settings()


def test_settings_cannot_be_changed() -> None:
    with pytest.raises(AttributeError):
        settings().frontend = "other"  # type: ignore[misc]


def test_two_targets_in_the_environment_are_refused() -> None:
    environ = {"BECK_TARGET": ENV_URL, "BECK_TARGET_DIR": ENV_DIR}

    with pytest.raises(ConfigError, match="BECK_TARGET or BECK_TARGET_DIR"):
        resolve(Flags(), environ, Config())


def test_two_targets_in_the_environment_do_not_matter_under_a_flag() -> None:
    environ = {"BECK_TARGET": ENV_URL, "BECK_TARGET_DIR": ENV_DIR}

    assert resolve(Flags(target=FLAG_URL), environ, Config()).target_url == FLAG_URL


@pytest.mark.parametrize(
    "url",
    ["http://a/b", "smb://host", f"smb://user:{SENTINEL}@host/bios"],
    ids=["scheme", "no-share", "password"],
)
def test_a_bad_target_in_the_environment_names_the_variable_and_repeats_nothing(url: str) -> None:
    with pytest.raises(ConfigError) as error:
        resolve(Flags(), {"BECK_TARGET": url}, Config())

    assert str(error.value).startswith("BECK_TARGET: ")
    assert SENTINEL not in str(error.value)


def test_a_bad_target_in_the_environment_does_not_matter_under_a_flag() -> None:
    assert resolve(Flags(target=FLAG_URL), {"BECK_TARGET": "nope"}, Config()).target_url == FLAG_URL


# Finding the file


def test_the_flag_wins_then_the_variable_then_the_default() -> None:
    environ = {"BECK_CONFIG": "/env.toml"}

    assert find_config("/flag.toml", environ) == ConfigLocation(Path("/flag.toml"), "flag")
    assert find_config(None, environ) == ConfigLocation(Path("/env.toml"), "environment")
    assert find_config(None, {}).source == "default"


def test_an_empty_variable_counts_as_not_set_for_the_file_too() -> None:
    assert find_config(None, {"BECK_CONFIG": ""}).source == "default"


def test_the_default_is_in_the_folder_the_system_says(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/some/config")

    assert find_config(None, {}).path == Path("/some/config/beck/config.toml")


def test_the_folder_is_the_one_dec_19_chose_on_every_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, Any] = {}

    def user_config_path(appname: str, **kwargs: Any) -> Path:
        asked.update(kwargs, appname=appname)
        return Path("/asked")

    monkeypatch.setattr(config, "user_config_path", user_config_path)

    assert find_config(None, {}).path == Path("/asked/config.toml")
    assert asked == {"appname": "beck", "appauthor": False, "roaming": True}


def test_finding_the_file_creates_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    find_config(None, {})

    assert not (tmp_path / "config").exists()


def test_tests_can_not_read_the_settings_of_who_runs_them() -> None:
    assert find_config(None, os.environ).path.is_relative_to(NO_SETTINGS_FOLDER)
    assert not any(name in os.environ for name in SETTINGS_VARIABLES)


# Through the command


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    source, device = tmp_path / "source", tmp_path / "device"
    source.mkdir()
    device.mkdir()
    return source, device


def put_report(device: Path, *entries: Any) -> None:
    (device / "missing_bios_report.txt").write_text(
        make_report_text(entries), encoding="utf-8", newline=""
    )


def settings_file(folder: Path, body: str, name: str = "settings.toml") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(f"schema_version = 1\n{body}", encoding="utf-8")
    return path


def on_disk(source: Path, device: Path) -> str:
    return f'[target]\ndir = "{device}"\n[source]\ndir = "{source}"\n'


def a_run_to_upload(folders: tuple[Path, Path]) -> Path:
    source, device = folders
    file = make_bios_file(source, "a.bin")
    put_report(device, make_missing("a.bin", file.md5))
    return device / "a.bin"


def test_a_named_file_says_where_everything_is(folders: tuple[Path, Path], tmp_path: Path) -> None:
    uploaded = a_run_to_upload(folders)
    path = settings_file(tmp_path, on_disk(*folders))

    assert cli.main(["check", "--config", str(path)], base_dir=tmp_path) == 0

    assert uploaded.exists()


def test_config_works_before_the_command_too(folders: tuple[Path, Path], tmp_path: Path) -> None:
    uploaded = a_run_to_upload(folders)
    path = settings_file(tmp_path, on_disk(*folders))

    assert cli.main(["--config", str(path), "check"], base_dir=tmp_path) == 0

    assert uploaded.exists()


def test_the_file_in_the_variable_is_read(
    folders: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded = a_run_to_upload(folders)
    monkeypatch.setenv("BECK_CONFIG", str(settings_file(tmp_path, on_disk(*folders))))

    assert cli.main(["check"], base_dir=tmp_path) == 0

    assert uploaded.exists()


def test_the_flag_beats_the_file_in_the_variable(
    folders: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded = a_run_to_upload(folders)
    monkeypatch.setenv("BECK_CONFIG", str(tmp_path / "nope.toml"))
    path = settings_file(tmp_path, on_disk(*folders))

    assert cli.main(["check", "--config", str(path)], base_dir=tmp_path) == 0

    assert uploaded.exists()


def test_the_default_file_is_read_from_any_folder(
    folders: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded = a_run_to_upload(folders)
    settings_file(tmp_path / "xdg" / "beck", on_disk(*folders), name="config.toml")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert cli.main(["check"]) == 0

    assert uploaded.exists()


def test_no_default_file_is_fine(
    tmp_path: Path, folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, device = folders
    put_report(device)

    assert cli.main(["check", "--source", str(source), "--target-dir", str(device)]) == 0

    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("how", ["flag", "variable"])
def test_a_named_file_that_does_not_exist_is_a_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    how: str,
) -> None:
    missing = tmp_path / "nope.toml"
    arguments = ["--json", "scan", "--source", str(tmp_path)]
    if how == "flag":
        arguments += ["--config", str(missing)]
    else:
        monkeypatch.setenv("BECK_CONFIG", str(missing))

    assert cli.main(arguments) == 2

    document = json.loads(capsys.readouterr().out)
    assert document["errors"][0]["code"] == "config"
    assert str(missing) in document["errors"][0]["message"]


def test_a_broken_default_file_stops_every_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings_file(tmp_path / "xdg" / "beck", "[smb]\ntimeout = 0\n", name="config.toml")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    for arguments in (["scan"], ["report"], ["check"]):
        assert cli.main(arguments, base_dir=tmp_path) == 2
        assert "smb.timeout" in capsys.readouterr().out


def test_a_default_file_that_can_not_be_read_is_not_taken_for_a_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "xdg" / "beck" / "config.toml").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert cli.main(["scan"], base_dir=tmp_path) == 2


def test_an_unknown_setting_warns_on_stderr_and_stdout_stays_a_document(
    folders: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a_run_to_upload(folders)
    path = settings_file(tmp_path, f'{on_disk(*folders)}[smb]\nusr = "x"\n')

    assert cli.main(["--json", "check", "--config", str(path)]) == 0

    out = capsys.readouterr()
    assert json.loads(out.out)["ok"] is True
    assert "smb.usr" in out.err


def test_the_environment_beats_the_file_through_the_command(
    folders: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded = a_run_to_upload(folders)
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    path = settings_file(tmp_path, on_disk(wrong, wrong))
    monkeypatch.setenv("BECK_SOURCE", str(folders[0]))
    monkeypatch.setenv("BECK_TARGET_DIR", str(folders[1]))

    assert cli.main(["check", "--config", str(path)]) == 0

    assert uploaded.exists()


def test_a_flag_beats_the_environment_through_the_command(
    folders: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded = a_run_to_upload(folders)
    monkeypatch.setenv("BECK_SOURCE", str(tmp_path / "nope"))
    monkeypatch.setenv("BECK_TARGET", "smb://beck-test-must-not-connect/bios")

    arguments = ["check", "--source", str(folders[0]), "--target-dir", str(folders[1])]
    assert cli.main(arguments) == 0

    assert uploaded.exists()


def test_a_source_named_anywhere_must_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope"
    monkeypatch.setenv("BECK_SOURCE", str(missing))
    assert cli.main(["scan"], base_dir=tmp_path) == 2
    assert "doesn't exist" in capsys.readouterr().out

    monkeypatch.delenv("BECK_SOURCE")
    path = settings_file(tmp_path, f'[source]\ndir = "{missing}"\n')
    assert cli.main(["scan", "--config", str(path)], base_dir=tmp_path) == 2
    assert "doesn't exist" in capsys.readouterr().out


def test_with_no_source_named_it_is_still_the_bios_folder_here(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = make_bios_file(tmp_path / "bios", "a.bin")

    assert cli.main(["scan"], base_dir=tmp_path) == 0

    assert file.md5 in capsys.readouterr().out


def test_report_reads_its_target_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    put_report(tmp_path, make_missing("a.bin", "a" * 32))
    monkeypatch.setenv("BECK_TARGET_DIR", str(tmp_path))

    assert cli.main(["report"], base_dir=tmp_path) == 0

    assert "a.bin" in capsys.readouterr().out


def test_a_report_file_needs_no_target_even_with_a_bad_one_in_a_lower_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "report.txt"
    report.write_text(make_report_text([make_missing("a.bin", "a" * 32)]), encoding="utf-8")
    monkeypatch.setenv("BECK_TARGET_DIR", str(tmp_path / "nope"))

    assert cli.main(["report", "--report-file", str(report)]) == 0

    assert "a.bin" in capsys.readouterr().out


class OtherFrontend(RecalboxAdapter):
    """With only one real frontend, using it can't be told from falling back on the default."""

    name = "beck-test-other"
    report_path = PurePosixPath("other_report.txt")


@pytest.fixture
def other_frontend(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setitem(frontends._ADAPTERS, OtherFrontend.name, OtherFrontend)
    return OtherFrontend.name


def put_other_report(device: Path) -> None:
    (device / "other_report.txt").write_text(
        make_report_text([make_missing("a.bin", "a" * 32)]), encoding="utf-8", newline=""
    )


@pytest.mark.parametrize("command", ["check", "report"])
def test_the_frontend_in_the_file_is_used_and_reported(
    folders: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    other_frontend: str,
    command: str,
) -> None:
    device = folders[1]
    put_other_report(device)
    path = settings_file(tmp_path, f'[target]\nfrontend = "{other_frontend}"\ndir = "{device}"\n')

    assert cli.main(["--json", command, "--config", str(path)], base_dir=tmp_path) == 0

    assert json.loads(capsys.readouterr().out)["frontend"] == other_frontend


def test_the_flag_beats_the_frontend_in_the_file(
    folders: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    other_frontend: str,
) -> None:
    device = folders[1]
    put_report(device)
    path = settings_file(tmp_path, f'[target]\nfrontend = "{other_frontend}"\ndir = "{device}"\n')
    arguments = ["--json", "check", "--config", str(path), "--frontend", "recalbox"]

    assert cli.main(arguments, base_dir=tmp_path) == 0

    assert json.loads(capsys.readouterr().out)["frontend"] == "recalbox"


def test_an_unknown_frontend_on_the_command_line_is_reported_as_it_was_given(
    tmp_path: Path, folders: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, device = folders
    arguments = ["--json", "check", "--source", str(source), "--target-dir", str(device)]

    assert cli.main([*arguments, "--frontend", "nope"]) == 2

    assert json.loads(capsys.readouterr().out)["frontend"] == "nope"


def test_the_document_says_the_frontend_when_the_file_can_not_be_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["--json", "check", "--config", str(tmp_path / "nope.toml")]

    assert cli.main(arguments) == 2

    assert json.loads(capsys.readouterr().out)["frontend"] == "recalbox"


# What reaches an SMB connection


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeSMBServer:
    # These tests name users, and with no terminal to ask on, a user needs this.
    monkeypatch.setenv("BECK_SMB_PASSWORD", "beck-test-password")
    fake = install_fake_smb(monkeypatch)
    fake.files[("bios", "missing_bios_report.txt")] = make_report_text([]).encode()
    return fake


def test_a_url_in_the_file_connects_with_its_user_and_timeout(
    server: FakeSMBServer, tmp_path: Path
) -> None:
    path = settings_file(
        tmp_path, '[target]\nurl = "smb://file-host/bios"\n[smb]\nuser = "file-user"\ntimeout = 7\n'
    )

    assert cli.main(["report", "--config", str(path)]) == 0

    connection = server.connections[0]
    assert connection.remote_name == "file-host"
    assert connection.username == "file-user"
    assert set(connection.timeouts) == {7}


def test_with_no_timeout_it_stays_what_it_was(server: FakeSMBServer, tmp_path: Path) -> None:
    assert cli.main(["report", "--target", "smb://host/bios"], base_dir=tmp_path) == 0

    assert set(server.connections[0].timeouts) == {30}


def test_the_variable_beats_the_user_in_the_file(
    server: FakeSMBServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = settings_file(
        tmp_path, '[target]\nurl = "smb://file-host/bios"\n[smb]\nuser = "file-user"\n'
    )
    monkeypatch.setenv("BECK_SMB_USER", "env-user")

    assert cli.main(["report", "--config", str(path)]) == 0

    assert server.connections[0].username == "env-user"


def test_an_empty_variable_means_a_guest_even_if_the_file_names_a_user(
    server: FakeSMBServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = settings_file(
        tmp_path, '[target]\nurl = "smb://file-host/bios"\n[smb]\nuser = "file-user"\n'
    )
    monkeypatch.setenv("BECK_SMB_USER", "")

    assert cli.main(["report", "--config", str(path)]) == 0

    assert server.connections[0].username == ""


def test_a_user_in_the_url_beats_the_variable(
    server: FakeSMBServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BECK_SMB_USER", "env-user")

    assert cli.main(["report", "--target", "smb://url-user@host/bios"], base_dir=tmp_path) == 0

    assert server.connections[0].username == "url-user"


def test_a_url_with_no_user_takes_the_one_from_the_variable(
    server: FakeSMBServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BECK_SMB_USER", "env-user")

    assert cli.main(["report", "--target", "smb://host/bios"], base_dir=tmp_path) == 0

    assert server.connections[0].username == "env-user"


def test_v_says_which_file_it_read_and_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = settings_file(tmp_path, "")

    assert cli.main(["-v", "scan", "--config", str(path), "--source", str(tmp_path)]) == 0

    assert f"Settings file: {path} (flag)" in capsys.readouterr().err


def test_a_real_process_reads_the_environment(folders: tuple[Path, Path]) -> None:
    uploaded = a_run_to_upload(folders)
    environ = {
        **os.environ,
        "BECK_SOURCE": str(folders[0]),
        "BECK_TARGET_DIR": str(folders[1]),
    }

    done = subprocess.run(
        [sys.executable, "-m", "beck", "--json", "check"],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        env=environ,
    )

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["ok"] is True
    assert uploaded.exists()
