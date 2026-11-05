"""The shipped config files (D14): git ignores the real file and ships an example."""

import shutil
import subprocess
from pathlib import Path

import yaml

from beck.cli import load_legacy_config

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "config" / "config.example.yml"


def test_example_config_has_the_keys_the_command_reads() -> None:
    settings = load_legacy_config(EXAMPLE)

    assert set(settings) == {"user", "passwd", "server", "port"}
    assert settings["port"] == 445


def test_example_config_ships_empty_credentials() -> None:
    settings = load_legacy_config(EXAMPLE)

    assert settings["user"] == ""
    assert settings["passwd"] == ""


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
