"""BECK's settings file: TOML, read with the standard library (DEC-24).

``find_config`` finds the file, ``load`` reads and checks it, and ``resolve`` decides between it,
the environment and the flags. A password never goes in this file, and no message here repeats a
value that could be one: someone may have typed it in the wrong place.
"""

import json
import logging
import os
import shlex
import stat
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

from beck.errors import ConfigError, UsageError
from beck.frontends import known_frontends
from beck.redact import without_url_credentials
from beck.targets import parse_smb_url

SCHEMA_VERSION = 1
DEFAULT_FRONTEND = "recalbox"
KNOWN_SETTINGS = {
    "target": {"frontend", "url", "dir"},
    "smb": {"user", "timeout"},
    "source": {"dir"},
}
PASSWORD_KEYS = {"password", "passwd"}
IS_POSIX = os.name == "posix"
TEMPLATE = """\
# BECK's settings. Flags and environment variables beat what's here: see docs/cli.md.
# Passwords can't go in this file: BECK asks for one, or set BECK_SMB_PASSWORD.
schema_version = 1

[target]
frontend = "recalbox"
url = "smb://recalbox.local/bios"   # or, for an SD card or USB drive: dir = "/media/you/bios"

[smb]
user = ""                           # empty means a guest, which is what Recalbox allows by default
timeout = 30                        # seconds

[source]
dir = "~/beck/bios"                 # your BIOS files. Create this folder, or change this
"""

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


@dataclass(frozen=True, slots=True)
class ConfigLocation:
    """Which file to read, and why: ``flag``, ``environment`` or ``default``."""

    path: Path
    source: str


@dataclass(frozen=True, slots=True)
class Flags:
    """The settings on the command line. None means they aren't there."""

    target: str | None = None
    target_dir: str | None = None
    source: str | None = None
    frontend: str | None = None


@dataclass(frozen=True, slots=True)
class Settings:
    """What a run uses, once flags, the environment, the file and the defaults are decided.

    No ``source_dir`` means ``./bios``, and no target means the legacy settings file, because both
    depend on where BECK runs. No ``smb_timeout`` means the transport's own. ``sources`` says where
    each came from: ``flag``, ``environment``, ``file`` or ``default``.
    """

    target_url: str | None = None
    target_dir: Path | None = None
    source_dir: Path | None = None
    frontend: str = DEFAULT_FRONTEND
    smb_user: str = ""
    smb_password: str = field(default="", repr=False)  # so that printing this can't show it
    smb_timeout: int | None = None
    sources: Mapping[str, str] = field(default_factory=dict, compare=False)


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


def _read(path: Path, *, may_be_missing: bool) -> dict[str, Any] | None:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except FileNotFoundError as e:
        if may_be_missing:
            return None
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


def _warn_if_others_can_read(path: Path) -> None:
    """It can't hold a password, but it says who you are and where your device is."""
    if not IS_POSIX:
        return
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        _log.warning(
            "%s: other users can read this file. To stop them, run: chmod 600 %s",
            path,
            shlex.quote(str(path)),
        )


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


def load(path: Path, *, may_be_missing: bool = False) -> Config:
    """Read a settings file. Raises ConfigError, listing every problem, each with its setting.

    They're on one line, because a line break in a message would show as ``\\x0a``. A setting this
    BECK doesn't know is only a warning, because it's probably a typo, and may be from a newer BECK.

    With ``may_be_missing``, no file means no settings, but any other failure is still an error.
    """
    data = _read(path, may_be_missing=may_be_missing)
    if data is None:
        return Config()
    _warn_if_others_can_read(path)
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
    if frontend is not None and frontend not in known_frontends():
        known = ", ".join(known_frontends())
        problems.append(f"target.frontend: that isn't a frontend BECK knows, which are: {known}")
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


def _named_path(value: str) -> Path:
    """A path someone typed, which may be a URL in the wrong place, with a password in it."""
    return Path(without_url_credentials(value))


def find_config(flag: str | None, environ: Mapping[str, str]) -> ConfigLocation:
    """The file to read: the flag, then ``BECK_CONFIG``, then the folder the system says (DEC-19).

    This creates nothing. An empty variable counts as not set.
    """
    if flag is not None:
        return ConfigLocation(_named_path(flag), "flag")
    named = environ.get("BECK_CONFIG")
    if named:
        return ConfigLocation(_named_path(named), "environment")
    folder = user_config_path("beck", appauthor=False, roaming=True)
    return ConfigLocation(folder / "config.toml", "default")


def _target(
    flags: Flags, environ: Mapping[str, str], file: Config
) -> tuple[str | None, Path | None, str]:
    """A target is one setting with two forms, so a higher source wins even in the other form."""
    if flags.target is not None:
        return flags.target, None, "flag"
    if flags.target_dir is not None:
        return None, _named_path(flags.target_dir), "flag"
    url, folder = environ.get("BECK_TARGET"), environ.get("BECK_TARGET_DIR")
    if url and folder:
        raise ConfigError("Set BECK_TARGET or BECK_TARGET_DIR, not both")
    if url:
        try:
            parse_smb_url(url)
        except UsageError as e:  # it never repeats the URL, which might hold a password
            raise ConfigError(f"BECK_TARGET: {e}") from e
        return url, None, "environment"
    if folder:
        return None, _named_path(folder), "environment"
    named_in_file = file.target_url is not None or file.target_dir is not None
    return file.target_url, file.target_dir, "file" if named_in_file else "default"


def _source_of(flag: object, variable: object, in_file: object) -> str:
    """Where a setting comes from, given what each source says about it."""
    if flag:
        return "flag"
    if variable is not None:
        return "environment"
    return "file" if in_file is not None else "default"


def resolve(flags: Flags, environ: Mapping[str, str], file: Config) -> Settings:
    """Decide each setting: flags, then the environment, then the file, then the default. Pure.

    An empty variable counts as not set, except ``BECK_SMB_USER``, where it means a guest. The
    password only comes from the environment: the file can't hold one, and neither can a URL.
    """
    target_url, target_dir, target_source = _target(flags, environ, file)
    source_variable = environ.get("BECK_SOURCE") or None
    source = flags.source if flags.source is not None else source_variable
    user_variable = environ.get("BECK_SMB_USER")
    user = environ.get("BECK_SMB_USER", file.smb_user)
    password = environ.get("BECK_SMB_PASSWORD", "")
    return Settings(
        target_url=target_url,
        target_dir=target_dir,
        source_dir=_named_path(source) if source else file.source_dir,
        frontend=flags.frontend or file.frontend or DEFAULT_FRONTEND,
        smb_user="" if user is None else user,
        smb_password=password,
        smb_timeout=file.smb_timeout,
        sources={
            "target": target_source,
            "source": _source_of(flags.source, source_variable, file.source_dir),
            "frontend": _source_of(flags.frontend, None, file.frontend),
            "smb_user": _source_of(None, user_variable, file.smb_user),
            "smb_password": "environment" if password else "default",
            "smb_timeout": _source_of(None, None, file.smb_timeout),
        },
    )


def write_template(path: Path, *, force: bool) -> None:
    """Write a settings file with comments, which only its owner can read.

    It refuses to replace a file unless ``force`` says so. It's only the template, but someone may
    have spent time on what's there.
    """
    how = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as e:  # apart: a file in the way of a folder is a FileExistsError too
        raise ConfigError(f"Can't write {path}: {e.strerror}") from e
    try:
        with os.fdopen(os.open(path, how, 0o600), "w", encoding="utf-8") as file:
            path.chmod(0o600)  # one that was already there can have any permissions
            file.write(TEMPLATE)
    except FileExistsError as e:
        raise ConfigError(f"{path} already exists. To replace it, use --force.") from e
    except OSError as e:
        raise ConfigError(f"Can't write {path}: {e.strerror}") from e
