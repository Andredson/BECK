"""``beck config``, and what happens to someone who still has the old ``config/config.yml``."""

import json
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from beck import cli
from beck.config import TEMPLATE, Config, load
from beck.legacy_config import (
    LegacySettings,
    migration_notice,
    parse_legacy,
    read_legacy,
    suggested_toml,
)
from tests.factories import make_bios_file, make_missing, make_report_text, settings_text
from tests.fakes import FakeSMBServer, install_fake_smb

ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "beck-test-password-sentinel"
OLD_EXAMPLE = """\
# BECK's SMB settings. Copy this file to config/config.yml and edit the copy:
# git ignores config/config.yml, so your password is never committed.

smb:
  user: ""                 # leave empty for guest access
  passwd: ""               # leave empty for guest access
  server: "recalbox.local" # your Recalbox's address: host name or IP address
  port: 445
"""


def old_file(folder: Path, text: str) -> Path:
    path = folder / "config" / "config.yml"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return path


def default_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "beck" / "config.toml"


def document(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    parsed: dict[str, object] = json.loads(capsys.readouterr().out)
    return parsed


# beck config path


def test_path_says_the_default_file_and_how_to_create_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = default_file(tmp_path, monkeypatch)

    assert cli.main(["config", "path"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        str(path),
        "This is the default place on this system.",
        "It doesn't exist yet. To create it, run beck config init.",
    ]
    assert not path.parent.exists(), "asking where it is creates nothing"


def test_path_says_why_for_a_flag_and_for_a_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    named = tmp_path / "named.toml"
    named.write_text("this is not toml", encoding="utf-8")

    assert cli.main(["config", "path", "--config", str(named)]) == 0
    assert capsys.readouterr().out.splitlines() == [str(named), "This is named by --config."]

    monkeypatch.setenv("BECK_CONFIG", str(named))
    assert cli.main(["config", "path"]) == 0
    assert capsys.readouterr().out.splitlines() == [str(named), "This is named by BECK_CONFIG."]


def test_path_never_reads_the_file_so_a_broken_one_can_be_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    named = tmp_path / "named.toml"
    named.write_text("this is not toml", encoding="utf-8")

    assert cli.main(["--json", "config", "path", "--config", str(named)]) == 0

    assert document(capsys)["file"] == {"path": str(named), "source": "flag", "exists": True}


# beck config init


def test_init_writes_the_template_where_it_will_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = default_file(tmp_path, monkeypatch)

    assert cli.main(["config", "init"]) == 0

    assert path.read_text(encoding="utf-8") == TEMPLATE
    assert str(path) in capsys.readouterr().out


def test_init_makes_a_file_only_its_owner_can_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = default_file(tmp_path, monkeypatch)
    monkeypatch.setattr("os.umask", lambda _mask: 0)

    assert cli.main(["config", "init"]) == 0

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_init_refuses_to_replace_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = default_file(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    path.write_text("mine", encoding="utf-8")

    assert cli.main(["config", "init"]) == 2

    assert path.read_text(encoding="utf-8") == "mine"
    assert "--force" in capsys.readouterr().out


def test_force_replaces_a_file_and_tightens_its_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = default_file(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    path.write_text("a longer file than the template would be if it were cut short" * 40)
    path.chmod(0o644)

    assert cli.main(["config", "init", "--force"]) == 0

    assert path.read_text(encoding="utf-8") == TEMPLATE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_init_writes_where_it_is_told(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    default = default_file(tmp_path, monkeypatch)
    named = tmp_path / "deep" / "er" / "named.toml"

    assert cli.main(["--json", "config", "init", "--config", str(named)]) == 0

    parsed = document(capsys)
    assert parsed["created"] is True
    assert parsed["file"] == {"path": str(named), "source": "flag", "exists": True}
    assert named.read_text(encoding="utf-8") == TEMPLATE
    assert not default.exists()


def test_init_that_can_not_write_is_a_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocked = tmp_path / "a-file"
    blocked.write_text("in the way", encoding="utf-8")

    assert cli.main(["config", "init", "--config", str(blocked / "settings.toml")]) == 2

    assert "Can't write" in capsys.readouterr().out


def test_init_with_force_on_a_folder_is_a_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["config", "init", "--force", "--config", str(tmp_path)]) == 2

    assert "Can't write" in capsys.readouterr().out


def test_the_template_is_a_valid_file_with_what_it_promises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", "/home/beck-test")
    path = tmp_path / "settings.toml"
    path.write_text(TEMPLATE, encoding="utf-8")

    assert load(path) == Config(
        frontend="recalbox",
        target_url="smb://recalbox.local/bios",
        smb_user="",
        smb_timeout=30,
        source_dir=Path("/home/beck-test/beck/bios"),
    )


def test_the_template_says_where_a_password_goes() -> None:
    assert "BECK_SMB_PASSWORD" in TEMPLATE
    assert "\npassword" not in TEMPLATE.lower()


def test_after_init_the_settings_are_used_from_any_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stage's promise: beck config init, and an environment variable or two."""
    server = install_fake_smb(monkeypatch)
    default_file(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    data = make_bios_file(tmp_path / "beck" / "bios", "a.bin")
    server.files[("bios", "missing_bios_report.txt")] = make_report_text(
        [make_missing("a.bin", data.md5)]
    ).encode()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert cli.main(["config", "init"]) == 0
    assert cli.main(["check"]) == 0

    assert server.connections[0].remote_name == "recalbox.local"
    assert ("bios", "a.bin") in server.files


# beck config show


def test_show_with_nothing_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = default_file(tmp_path, monkeypatch)

    assert cli.main(["config", "show"], base_dir=tmp_path) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"Settings file: {path} (the default place on this system, which doesn't exist)",
        "target: not set (default)",
        f"source: {tmp_path / 'bios'} (default)",
        "frontend: recalbox (default)",
        "smb_user: (a guest) (default)",
        "smb_password: not set (default)",
        "smb_timeout: 30 (default)",
    ]


def test_show_says_where_each_setting_comes_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "settings.toml"
    settings.write_text(
        settings_text("smb://file-host:4450/bios/sub", "file-user", timeout=7)
        + f'[source]\ndir = "{tmp_path}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)

    assert cli.main(["--json", "config", "show", "--config", str(settings)]) == 0

    assert document(capsys)["settings"] == {
        "target": {"value": "smb://file-host:4450/bios/sub", "source": "file"},
        "source": {"value": str(tmp_path), "source": "file"},
        "frontend": {"value": "recalbox", "source": "default"},
        "smb_user": {"value": "file-user", "source": "file"},
        "smb_password": {"value": "set", "source": "environment"},
        "smb_timeout": {"value": 7, "source": "file"},
    }


def test_show_says_what_the_environment_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BECK_TARGET_DIR", str(tmp_path))
    monkeypatch.setenv("BECK_SOURCE", str(tmp_path))
    monkeypatch.setenv("BECK_SMB_USER", "env-user")

    assert cli.main(["--json", "config", "show"]) == 0

    settings = document(capsys)["settings"]
    assert isinstance(settings, dict)
    assert settings["target"] == {"value": tmp_path.resolve().as_uri(), "source": "environment"}
    assert settings["source"] == {"value": str(tmp_path), "source": "environment"}
    assert settings["smb_user"] == {"value": "env-user", "source": "environment"}


def test_show_says_an_empty_variable_made_it_a_guest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "settings.toml"
    settings.write_text(settings_text("smb://host/bios", "file-user"), encoding="utf-8")
    monkeypatch.setenv("BECK_SMB_USER", "")

    assert cli.main(["config", "show", "--config", str(settings)]) == 0

    assert "smb_user: (a guest) (environment)" in capsys.readouterr().out


def test_show_takes_the_user_from_the_url_and_leaves_it_out_of_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BECK_TARGET", "smb://url-user@host/bios")
    monkeypatch.setenv("BECK_SMB_USER", "env-user")

    assert cli.main(["--json", "config", "show"]) == 0

    settings = document(capsys)["settings"]
    assert isinstance(settings, dict)
    assert settings["target"] == {"value": "smb://host:445/bios", "source": "environment"}
    assert settings["smb_user"] == {"value": "url-user", "source": "environment"}


def test_show_says_a_user_in_the_url_comes_from_where_the_url_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "settings.toml"
    settings.write_text(settings_text("smb://file-host/bios", "file-user"), encoding="utf-8")
    monkeypatch.setenv("BECK_TARGET", "smb://url-user@host/bios")

    assert cli.main(["config", "show", "--config", str(settings)]) == 0

    assert "smb_user: url-user (environment)" in capsys.readouterr().out


@pytest.mark.parametrize("mode", [[], ["--json"]], ids=["human", "json"])
def test_show_never_shows_the_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: list[str],
) -> None:
    monkeypatch.setenv("BECK_SMB_PASSWORD", SENTINEL)
    monkeypatch.setenv("BECK_TARGET", "smb://user@host/bios")

    assert cli.main(["-v", *mode, "config", "show"], base_dir=tmp_path) == 0

    out = capsys.readouterr()
    assert SENTINEL not in out.out + out.err
    assert "set" in out.out


def test_show_needs_no_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = install_fake_smb(monkeypatch)
    monkeypatch.setenv("BECK_TARGET", "smb://host/bios")

    assert cli.main(["config", "show"], base_dir=tmp_path) == 0

    assert server.connections == []


def test_show_of_a_broken_file_lists_its_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "settings.toml"
    settings.write_text("[smb]\ntimeout = 0\n", encoding="utf-8")

    assert cli.main(["--json", "config", "show", "--config", str(settings)]) == 2

    parsed = document(capsys)
    assert parsed["ok"] is False
    assert parsed["settings"] is None
    assert parsed["file"] == {"path": str(settings), "source": "flag", "exists": True}
    assert "smb.timeout" in str(parsed["errors"])


def test_show_of_a_named_file_that_does_not_exist(tmp_path: Path) -> None:
    assert cli.main(["config", "show", "--config", str(tmp_path / "nope.toml")]) == 2


# The command line


@pytest.mark.parametrize(
    "arguments",
    [["config"], ["config", "nope"], ["config", "show", "--force"], ["config", "path", "--force"]],
)
def test_a_bad_config_command_is_a_usage_error(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(arguments)

    assert stop.value.code == 2


@pytest.mark.parametrize("flags", [["--json"], ["-v"], ["--no-color"], ["-q"]])
def test_global_options_work_after_the_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str]
) -> None:
    default_file(tmp_path, monkeypatch)

    assert cli.main(["config", "path", *flags]) == 0


def test_quiet_does_not_shorten_what_config_prints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    default_file(tmp_path, monkeypatch)
    assert cli.main(["config", "show"], base_dir=tmp_path) == 0
    normal = capsys.readouterr().out

    assert cli.main(["-q", "config", "show"], base_dir=tmp_path) == 0

    assert capsys.readouterr().out == normal


# Reading the old file


def test_the_old_example_file_reads_as_a_guest_on_the_default_server() -> None:
    assert parse_legacy(OLD_EXAMPLE) == LegacySettings(
        server="recalbox.local", port=445, user="", has_password=False
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("smb:\n  server: nas\n", LegacySettings(server="nas")),
        ('smb:\n  server: "nas"\n', LegacySettings(server="nas")),
        ("smb:\n  server: 'nas'\n", LegacySettings(server="nas")),
        ('smb:\n  server: "nas" # a comment\n', LegacySettings(server="nas")),
        ("smb:\n  server: nas # a comment\n", LegacySettings(server="nas")),
        ('smb:\n  user: "a # b"\n', LegacySettings(user="a # b")),
        ("smb:\n  port: 4450\n", LegacySettings(port=4450)),
        ('smb:\n  port: "4450"\n', LegacySettings(port=4450)),
        ("smb:\n  port: abc\n", LegacySettings()),
        ("smb:\n  port: ٣\n", LegacySettings()),
        ("smb:\n  user:\n", LegacySettings(user="")),
        ('smb:\n  server: ""\n', LegacySettings(server="")),
        ("#  server: commented-out\n", LegacySettings()),
        ("   # server: commented-out\n", LegacySettings()),
        ("this is not settings at all\n", LegacySettings()),
        ("", LegacySettings()),
        ('smb: {user: "", server: "inline"}\n', LegacySettings()),
    ],
)
def test_reading_the_simple_lines(text: str, expected: LegacySettings) -> None:
    assert parse_legacy(text) == expected


@pytest.mark.parametrize(
    ("line", "has_password"),
    [
        (f'  passwd: "{SENTINEL}"\n', True),
        (f"  passwd: {SENTINEL}\n", True),
        ('  passwd: ""\n', False),
        ("  passwd:\n", False),
    ],
)
def test_it_keeps_only_whether_there_was_a_password(line: str, has_password: bool) -> None:
    legacy = parse_legacy(f"smb:\n{line}")

    assert legacy.has_password is has_password
    assert SENTINEL not in repr(legacy)


def test_an_old_file_that_is_not_utf8_is_still_read(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_bytes(b"smb:\n  server: nas\n  user: \xff\n")

    legacy = read_legacy(path)

    assert legacy is not None
    assert legacy.server == "nas"


def test_an_old_file_that_can_not_be_read_is_ignored(tmp_path: Path) -> None:
    assert read_legacy(tmp_path / "nope.yml") is None
    assert read_legacy(tmp_path) is None


# The equivalent settings


def toml_loaded(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "suggested.toml"
    path.write_text(text, encoding="utf-8")
    return load(path)


@pytest.mark.parametrize(
    ("legacy", "url", "user"),
    [
        (LegacySettings(), "smb://recalbox.local/bios", ""),
        (
            LegacySettings(server="recalbox.local", port=445, user=""),
            "smb://recalbox.local/bios",
            "",
        ),
        (LegacySettings(server="nas", port=4450, user="me"), "smb://nas:4450/bios", "me"),
        (LegacySettings(server="192.168.1.20", port=445), "smb://192.168.1.20/bios", ""),
        (LegacySettings(user='quo"te\\back'), "smb://recalbox.local/bios", 'quo"te\\back'),
        (LegacySettings(user="ação\x1b"), "smb://recalbox.local/bios", "ação\x1b"),
        (LegacySettings(server="not a host/at all"), "smb://recalbox.local/bios", ""),
        (LegacySettings(server=""), "smb://recalbox.local/bios", ""),
        (LegacySettings(port=99999), "smb://recalbox.local/bios", ""),
    ],
)
def test_the_suggestion_is_a_valid_file_that_says_the_same(
    tmp_path: Path, legacy: LegacySettings, url: str, user: str
) -> None:
    assert toml_loaded(tmp_path, suggested_toml(legacy)) == Config(target_url=url, smb_user=user)


def test_the_suggestion_for_the_old_example_is_exactly_this() -> None:
    assert suggested_toml(parse_legacy(OLD_EXAMPLE)) == (
        'schema_version = 1\n\n[target]\nurl = "smb://recalbox.local/bios"\n\n[smb]\nuser = ""\n'
    )


# The notice


def test_the_notice_never_repeats_the_password() -> None:
    legacy = parse_legacy(f'smb:\n  user: "me"\n  passwd: "{SENTINEL}"\n  server: nas\n')

    lines = migration_notice(Path("old.yml"), legacy, Path("new.toml"))

    assert SENTINEL not in "\n".join(lines)
    assert any("BECK_SMB_PASSWORD" in line for line in lines)


def test_the_notice_says_nothing_of_a_password_there_was_not() -> None:
    lines = migration_notice(Path("old.yml"), parse_legacy(OLD_EXAMPLE), Path("new.toml"))

    assert not any("BECK_SMB_PASSWORD" in line for line in lines)


def test_someone_with_the_old_file_is_told_what_to_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    new = default_file(tmp_path, monkeypatch)
    old = old_file(tmp_path, f'smb:\n  user: "me"\n  passwd: "{SENTINEL}"\n  server: nas\n')
    source = tmp_path / "source"
    source.mkdir()

    assert cli.main(["scan", "--source", str(source)], base_dir=tmp_path) == 0

    out = capsys.readouterr()
    assert out.err.splitlines() == [
        f"{old} isn't read any more. To keep these settings, put this in {new}, "
        "and then delete the old file:",
        "  schema_version = 1",
        "  ",
        "  [target]",
        '  url = "smb://nas/bios"',
        "  ",
        "  [smb]",
        '  user = "me"',
        "The password in the old file can't go in the new one. Set BECK_SMB_PASSWORD instead.",
    ]
    assert SENTINEL not in out.out + out.err


def test_the_old_file_is_no_longer_used_to_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server: FakeSMBServer = install_fake_smb(monkeypatch)
    old_file(tmp_path, OLD_EXAMPLE)

    assert cli.main(["check"], base_dir=tmp_path) == 2

    out = capsys.readouterr()
    assert "BECK has no target" in out.out
    assert "isn't read any more" in out.err
    assert server.connections == []


def test_the_notice_stops_once_there_is_a_new_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    new = default_file(tmp_path, monkeypatch)
    old_file(tmp_path, OLD_EXAMPLE)
    assert cli.main(["config", "init"], base_dir=tmp_path) == 0
    assert "isn't read any more" in capsys.readouterr().err
    assert new.exists()

    assert cli.main(["config", "path"], base_dir=tmp_path) == 0

    assert capsys.readouterr().err == ""


def test_the_notice_looks_for_the_file_that_would_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    default_file(tmp_path, monkeypatch)
    old_file(tmp_path, OLD_EXAMPLE)
    named = tmp_path / "named.toml"
    named.write_text("schema_version = 1\n", encoding="utf-8")

    assert cli.main(["config", "path", "--config", str(named)], base_dir=tmp_path) == 0

    assert capsys.readouterr().err == ""


def test_no_old_file_no_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    default_file(tmp_path, monkeypatch)

    assert cli.main(["config", "path"], base_dir=tmp_path) == 0

    assert capsys.readouterr().err == ""


def test_quiet_leaves_the_notice_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    default_file(tmp_path, monkeypatch)
    old_file(tmp_path, OLD_EXAMPLE)

    assert cli.main(["-q", "config", "path"], base_dir=tmp_path) == 0

    assert capsys.readouterr().err == ""


def test_with_json_the_notice_stays_off_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    default_file(tmp_path, monkeypatch)
    old_file(tmp_path, OLD_EXAMPLE)

    assert cli.main(["--json", "config", "path"], base_dir=tmp_path) == 0

    out = capsys.readouterr()
    assert json.loads(out.out)["ok"] is True
    assert "isn't read any more" in out.err


# PyYAML is gone


def test_git_still_ignores_the_old_file_which_may_hold_a_password() -> None:
    git = shutil.which("git")
    assert git is not None, "git is required to run this test"
    # --no-index checks the .gitignore rules even if someone tracks the file again.
    result = subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [git, "check-ignore", "--quiet", "--no-index", "config/config.yml"], cwd=ROOT, check=False
    )
    assert result.returncode == 0, "config/config.yml must be listed in .gitignore"


@pytest.mark.parametrize("name", ["pyproject.toml", "requirements.txt", "uv.lock"])
def test_pyyaml_is_gone(name: str) -> None:
    assert "pyyaml" not in (ROOT / name).read_text(encoding="utf-8").lower()


def test_nothing_in_beck_imports_yaml() -> None:
    for path in (ROOT / "src" / "beck").rglob("*.py"):
        assert "import yaml" not in path.read_text(encoding="utf-8"), path
