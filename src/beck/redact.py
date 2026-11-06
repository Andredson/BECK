"""Keeps credentials out of whatever BECK shows: logs, error messages, the JSON output.

BECK doesn't print a password on purpose, so this is for what repeats one by accident: a URL typed
in the wrong place, a library's error message, or a bug. ``--json`` keeps the exact name of a file,
so this goes on free text, not on every field.
"""

import re

MASK = "***"
# A password can hold an @, so this runs to the last one before the path. One with a slash in it
# isn't a valid URL, and can't be told apart from a path.
# The lookahead is for BECK's own way of writing a target, smb://[user@]host, in its messages.
URL_CREDENTIALS = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.-]*://)(?!\[user@\])[^/\s]*@")

_secrets: set[str] = set()


def add_secret(value: str) -> None:
    """Mask this from now on. Only the password itself goes here: it stays in memory."""
    if value:
        _secrets.add(value)


def forget_secrets() -> None:
    _secrets.clear()


def without_url_credentials(text: str) -> str:
    """Text with no user or password in any URL.

    A value that's going to be a path needs this first: ``Path`` turns ``smb://`` into ``smb:/``,
    and a ``file://`` URL encodes the rest, so afterwards nothing can tell it was a URL.
    """
    return URL_CREDENTIALS.sub(r"\1", text)


def redact(text: str) -> str:
    """Text with no credentials in any URL, and with every password BECK knows masked.

    A short password masks whatever it appears in. That's ugly, but the other way round isn't safe.
    """
    clean = without_url_credentials(text)
    for secret in sorted(_secrets, key=len, reverse=True):  # so that no part of a longer one stays
        clean = MASK.join(clean.split(secret))
    return clean
