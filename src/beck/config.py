"""BECK's settings file: TOML, read with the standard library (DEC-24).

``load`` reads and checks one file. Finding it, and deciding between it and other settings, is
someone else's job. A password never goes in this file, and no message here repeats a value that
could be one: someone may have typed it in the wrong place.
"""

import json
import logging
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from beck.errors import ConfigError, UsageError
from beck.frontends import get_adapter
from beck.targets import parse_smb_url

SCHEMA_VERSION = 1
KNOWN_SETTINGS = {
    "target": {"frontend", "url", "dir"},
    "smb": {"user", "timeout"},
    "source": {"dir"},
}
PASSWORD_KEYS = {"password", "passwd"}

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Config:
    """What a settings file says. None means it doesn't say, so something else can decide."""

    frontend: str | None = None
    target_url: str | None = None
    target_dir: Path | None = None
    smb_user: str | None = None  # empty means a guest, which isn't the same as not saying
    smb_timeout: int | None = None
    source_dir: Path | None = None


def _kind(value: object) -> str:
    """What a value is, without repeating it."""
    if isinstance(value, bool):
        return "true or false"
    if isinstance(value, int | float):
        return "a number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "a list"
    return "a table" if isinstance(value, dict) else "a date"


def _shown(value: object) -> str:
    """A value that's meant to be a number, which it's fine to repeat."""
    return json.dumps(value) if isinstance(value, str | int | float) else _kind(value)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _password_keys(node: object, path: str = "") -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            place = f"{path}.{key}" if path else key
            if key.lower() in PASSWORD_KEYS:
                yield place
            else:
                yield from _password_keys(value, place)
    elif isinstance(node, list):
        for item in node:
            yield from _password_keys(item, f"{path}[]")


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except FileNotFoundError as e:
        raise ConfigError(f"{path} not found") from e
    except OSError as e:
        raise ConfigError(f"Can't read {path}: {e.strerror}") from e
    except UnicodeDecodeError as e:  # its message is left out, because it can show the file's bytes
        raise ConfigError(f"{path} isn't UTF-8 text") from e
    except (tomllib.TOMLDecodeError, RecursionError) as e:
        raise ConfigError(f"{path} isn't valid TOML: {e}") from e


def _table(data: dict[str, Any], name: str, problems: list[str]) -> dict[str, Any]:
    value = data.get(name, {})
    if isinstance(value, dict):
        return value
    problems.append(f"{name}: expected a table, got {_kind(value)}")
    return {}


def _text(table: dict[str, Any], place: str, problems: list[str]) -> str | None:
    value = table.get(place.rpartition(".")[2])
    if value is None or isinstance(value, str):
        return value
    problems.append(f"{place}: expected text, got {_kind(value)}")
    return None


def _folder(table: dict[str, Any], place: str, problems: list[str]) -> Path | None:
    """A folder that means the same from anywhere, because BECK can run from any folder."""
    text = _text(table, place, problems)
    if text is None:
        return None
    if "\0" in text:
        problems.append(f"{place}: can't hold a NUL character")
        return None
    try:
        folder = Path(text).expanduser()
    except RuntimeError:
        problems.append(f"{place}: can't find that home folder")
        return None
    if folder.is_absolute():
        return folder
    problems.append(f"{place}: expected an absolute path or one starting with ~")
    return None


def _check_version(path: Path, data: dict[str, Any], problems: list[str]) -> None:
    if "schema_version" not in data:
        problems.append(f"schema_version: missing, expected {SCHEMA_VERSION}")
        return
    version = data["schema_version"]
    if _is_int(version) and version > SCHEMA_VERSION:
        # The rest of the file may be fine, in a format this BECK knows nothing about.
        raise ConfigError(
            f"{path} has schema_version {version}, and this BECK reads up to {SCHEMA_VERSION}. "
            "Upgrade BECK."
        )
    if not _is_int(version) or version != SCHEMA_VERSION:
        problems.append(f"schema_version: expected {SCHEMA_VERSION}, got {_shown(version)}")


def _warn_about_unknown_settings(path: Path, data: dict[str, Any]) -> None:
    def warn(place: str) -> None:
        _log.warning("%s: ignoring the unknown setting %s", path, place)

    for key, value in data.items():
        if key.lower() in PASSWORD_KEYS or key == "schema_version":
            continue
        if key not in KNOWN_SETTINGS:
            warn(key)
        elif isinstance(value, dict):
            for inner in value:
                if inner not in KNOWN_SETTINGS[key] and inner.lower() not in PASSWORD_KEYS:
                    warn(f"{key}.{inner}")


def load(path: Path) -> Config:
    """Read a settings file. Raises ConfigError, listing every problem, each with its setting.

    They're on one line, because a line break in a message would show as ``\\x0a``. A setting this
    BECK doesn't know is only a warning, because it's probably a typo, and may be from a newer BECK.
    """
    data = _read(path)
    problems: list[str] = []
    _check_version(path, data, problems)
    for place in dict.fromkeys(_password_keys(data)):
        problems.append(
            f"{place}: passwords can't be in this file, where anyone who can read it can see them. "
            "Use the BECK_SMB_PASSWORD environment variable, or let BECK ask."
        )
    _warn_about_unknown_settings(path, data)

    target = _table(data, "target", problems)
    smb = _table(data, "smb", problems)
    source = _table(data, "source", problems)

    frontend = _text(target, "target.frontend", problems)
    if frontend is not None:
        try:
            get_adapter(frontend)
        except UsageError as e:
            problems.append(f"target.frontend: {e}")
    url = _text(target, "target.url", problems)
    if url is not None:
        try:
            parse_smb_url(url)
        except UsageError as e:  # it never repeats the URL, which might hold a password
            problems.append(f"target.url: {e}")
    if "url" in target and "dir" in target:
        problems.append("target: use url or dir, not both")

    timeout = smb.get("timeout")
    if timeout is not None and not (_is_int(timeout) and timeout > 0):
        problems.append(f"smb.timeout: expected a positive integer, got {_shown(timeout)}")

    config = Config(
        frontend=frontend,
        target_url=url,
        target_dir=_folder(target, "target.dir", problems),
        smb_user=_text(smb, "smb.user", problems),
        smb_timeout=timeout,
        source_dir=_folder(source, "source.dir", problems),
    )
    if problems:
        raise ConfigError(f"{path} has problems: {'; '.join(problems)}")
    return config
