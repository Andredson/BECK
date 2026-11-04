"""The SMB config (D14): git ignores the real file, ships an example, and explains a missing one."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import check_bios
from tests.conftest import use_folder

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "config" / "config.example.yml"


def test_missing_config_tells_the_user_to_copy_the_example(tmp_path: Path) -> None:
    missing = tmp_path / "config" / "config.yml"

    with pytest.raises(check_bios.BeckError) as error:
        check_bios.load_configs(missing)

    assert f"{missing} not found" in str(error.value)
    assert "Copy config/config.example.yml to config/config.yml and fill it in" in str(error.value)


@pytest.mark.parametrize("content", ["", "other: 1\n", "- a list\n"])
def test_config_without_an_smb_section_is_a_clear_error(tmp_path: Path, content: str) -> None:
    file = tmp_path / "config.yml"
    file.write_text(content, encoding="utf-8")

    with pytest.raises(check_bios.BeckError, match="has no smb section"):
        check_bios.load_configs(file)


def test_main_prints_a_config_error_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_folder(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as exit_info:
        check_bios.main()

    assert exit_info.value.code == 1
    assert "Copy config/config.example.yml" in capsys.readouterr().out


def test_example_config_has_the_keys_the_script_reads() -> None:
    configs = check_bios.load_configs(EXAMPLE)

    assert set(configs) == {"user", "passwd", "server", "port"}
    assert configs["port"] == 445


def test_example_config_ships_empty_credentials() -> None:
    configs = check_bios.load_configs(EXAMPLE)

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
