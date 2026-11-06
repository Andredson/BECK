"""The old ``config/config.yml``: read only to say what to write instead, with no YAML library.

It reads the simple ``key: value`` lines of the old example file (DEC-24). It keeps nothing of the
old password except that there was one, so that it can't end up in a message.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from beck.errors import UsageError
from beck.targets import DEFAULT_SMB_PORT, parse_smb_url

DEFAULT_SERVER = "recalbox.local"
SIMPLE_LINE = re.compile(r"^\s*(\w+)\s*:\s*(.*?)\s*$")
A_HOST = re.compile(r"[\w.-]+")


@dataclass(frozen=True, slots=True)
class LegacySettings:
    """What the old file says. An old password is never kept, only whether there was one."""

    server: str | None = None
    port: int | None = None
    user: str | None = None
    has_password: bool = False


def _value(text: str) -> str:
    """A value without its quotes or its comment."""
    if text[:1] in ('"', "'"):
        return text[1:].partition(text[0])[0]
    return text.partition(" #")[0].strip()


def parse_legacy(text: str) -> LegacySettings:
    """Read the ``key: value`` lines. A line it doesn't understand is skipped."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = SIMPLE_LINE.match(line)
        if match:  # a comment doesn't match, because it doesn't start with a word
            found[match[1]] = _value(match[2])
    port = found.get("port", "")
    return LegacySettings(
        server=found.get("server"),
        port=int(port) if port.isascii() and port.isdigit() else None,
        user=found.get("user"),
        has_password=bool(found.get("passwd")),
    )


def read_legacy(path: Path) -> LegacySettings | None:
    """The old file, if there is one that can be read. This is only ever to help."""
    try:
        return parse_legacy(path.read_bytes().decode("utf-8", errors="replace"))
    except OSError:
        return None


def _url(legacy: LegacySettings) -> str:
    """The target, or the default one if the old file holds something that isn't a target."""
    fallback = f"smb://{DEFAULT_SERVER}/bios"
    server = legacy.server or DEFAULT_SERVER
    if not A_HOST.fullmatch(server):
        return fallback
    port = "" if legacy.port in (None, DEFAULT_SMB_PORT) else f":{legacy.port}"
    url = f"smb://{server}{port}/bios"
    try:
        parse_smb_url(url)
    except UsageError:
        return fallback
    return url


def suggested_toml(legacy: LegacySettings) -> str:
    """The new settings file that says the same as the old one, except for the password."""
    # A JSON string is a valid TOML string, whatever the value holds.
    return (
        "schema_version = 1\n"
        "\n"
        "[target]\n"
        f"url = {json.dumps(_url(legacy))}\n"
        "\n"
        "[smb]\n"
        f"user = {json.dumps(legacy.user or '')}\n"
    )


def migration_notice(old: Path, legacy: LegacySettings, new: Path) -> list[str]:
    """What to tell someone who still has the old file. One item per line."""
    lines = [
        f"{old} isn't read any more. To keep these settings, put this in {new}, "
        "and then delete the old file:",
        *(f"  {line}" for line in suggested_toml(legacy).splitlines()),
    ]
    if legacy.has_password:
        lines.append(
            "The password in the old file can't go in the new one. Set BECK_SMB_PASSWORD instead."
        )
    return lines
