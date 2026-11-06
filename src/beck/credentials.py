"""Where an SMB password comes from: the environment or a prompt, never a file or a URL (DEC-10).

The password stays in memory, and goes straight to the transport.
"""

import getpass
import sys
import warnings

from beck.errors import ConfigError
from beck.output import escaped_for_terminal, print_safely
from beck.redact import add_secret

CANT_ASK = (
    "A user is set, but no password, and BECK can't ask for one here. "
    "Set BECK_SMB_PASSWORD, or run BECK on a terminal without --json."
)
NO_ANSWER = "Nothing was changed, because no password was given."


def _ask(user: str, host: str) -> str:
    """Ask on the terminal, with nothing typed showing. Anything but an answer stops the run.

    ``getpass`` only warns when it can't turn the echo off, and then reads the password anyway, for
    anyone to see, so here that's a refusal.
    """
    # Both come from settings, which can hold anything, and this goes straight to the terminal.
    prompt = escaped_for_terminal(f"Password for {user} on {host}: ")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt) as e:
        print_safely("", sys.stderr)  # the cursor is still at the end of the prompt
        raise ConfigError(NO_ANSWER) from e
    except (getpass.GetPassWarning, OSError, UnicodeDecodeError) as e:
        raise ConfigError(CANT_ASK) from e
    add_secret(password)
    return password


def password_for(user: str, host: str, configured: str, *, can_ask: bool) -> str:
    """The password to log in with. A guest has none, and one that's set is never asked for."""
    if not user:
        return ""
    if configured:
        return configured
    if not can_ask:
        raise ConfigError(CANT_ASK)
    return _ask(user, host)
