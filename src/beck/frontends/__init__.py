# SPDX-License-Identifier: GPL-3.0-only
"""The frontend adapters BECK knows, by name."""

from collections.abc import Callable

from beck.errors import UsageError
from beck.frontends.base import FrontendAdapter
from beck.frontends.recalbox import RecalboxAdapter

_ADAPTERS: dict[str, Callable[[], FrontendAdapter]] = {"recalbox": RecalboxAdapter}


def known_frontends() -> list[str]:
    """The names ``--frontend`` accepts, sorted for messages."""
    return sorted(_ADAPTERS)


def get_adapter(name: str) -> FrontendAdapter:
    """The adapter with this name. Raises UsageError, listing the known names, if there's none."""
    try:
        factory = _ADAPTERS[name]
    except KeyError as e:
        known = ", ".join(known_frontends())
        raise UsageError(f"Unknown frontend {name!r}. Known frontends: {known}") from e
    return factory()
