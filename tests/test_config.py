"""The SMB config (D14): git ignores the real file, ships an example, and explains a missing one."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import check_bios

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "config" / "config.example.yml"


def test_missing_config_tells_the_user_to_copy_the_example(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "config" / "config.yml"

    with pytest.raises(SystemExit) as exit_info:
        check_bios.load_configs(str(missing))

    assert exit_info.value.code == 1
    output = capsys.readouterr().out
    assert f"{missing} not found" in output
    assert "Copy config/config.example.yml to config/config.yml and fill it in" in output


def test_example_config_has_the_keys_the_script_reads() -> None:
    configs = check_bios.load_configs(str(EXAMPLE))

    assert set(configs) == {"user", "passwd", "server", "port"}
    assert configs["port"] == 445


def test_example_config_ships_empty_credentials() -> None:
    configs = check_bios.load_configs(str(EXAMPLE))

    assert configs["user"] == ""
    assert configs["passwd"] == ""


def test_example_config_has_only_the_smb_section() -> None:
    # The old tracked file had a meaningless `version: "3.8"` key.
    assert set(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))) == {"smb"}


def test_git_ignores_the_real_config() -> None:
    git = shutil.which("git")
    assert git is not None, "git is required to run this test"
    # --no-index checks the .gitignore rules even if someone tracks the file again.
    result = subprocess.run(  # noqa: S603 - fixed arguments, no external input
        [git, "check-ignore", "--quiet", "--no-index", "config/config.yml"], cwd=ROOT, check=False
    )
    assert result.returncode == 0, "config/config.yml must be listed in .gitignore"
