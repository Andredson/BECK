"""Where to find the device: parsing ``--target`` URLs. No I/O."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from beck.errors import UsageError
from beck.models import SHARE_ROOT

URL_FORM = "smb://[user@]host[:port]/share[/sub/path]"
DEFAULT_SMB_PORT = 445


@dataclass(frozen=True, slots=True)
class SmbTarget:
    """A share on an SMB server. ``root`` is the BIOS folder, relative to the share."""

    host: str
    port: int
    share: str
    root: PurePosixPath = SHARE_ROOT
    user: str = ""


def _segments(path: str) -> list[str]:
    """The parts of a URL's path, decoded. Refuses anything that could climb out of the share."""
    decoded = [unquote(part) for part in path.split("/") if part]
    for part in decoded:
        if part in (".", "..") or "/" in part or "\\" in part:
            raise UsageError(f"The target's path can't contain {part!r}. Use {URL_FORM}")
    return decoded


def parse_smb_url(url: str) -> SmbTarget:
    """Parse a ``--target`` URL. Raises UsageError.

    Error messages never repeat the URL, because it might contain a password.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        raise UsageError(f"The target isn't a valid URL. Use {URL_FORM}") from e

    if parts.scheme != "smb":
        raise UsageError(f"The target must start with smb://. Use {URL_FORM}")
    if ":" in parts.netloc.rpartition("@")[0]:
        raise UsageError(
            "The target can't contain a password: anyone can read a command line. "
            f"Use {URL_FORM}. Passwords for targets arrive in a later version."
        )
    if parts.query or parts.fragment:
        raise UsageError(f"The target can't have a query or fragment. Use {URL_FORM}")
    if not parts.hostname:
        raise UsageError(f"The target has no host. Use {URL_FORM}")

    segments = _segments(parts.path)
    if not segments:
        raise UsageError(f"The target has no share. Use {URL_FORM}")

    return SmbTarget(
        host=parts.hostname,
        port=DEFAULT_SMB_PORT if port is None else port,
        share=segments[0],
        root=PurePosixPath(*segments[1:]),
        user=unquote(parts.username or ""),
    )
