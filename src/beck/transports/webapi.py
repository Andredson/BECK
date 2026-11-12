# SPDX-License-Identifier: GPL-3.0-only
"""One GET to a device's web API, such as Recalbox's ``/api/bios`` (DEC-79).

It uses the standard library's ``http.client``, which ``urllib`` is built on: unlike ``urllib``, it
never follows a redirect or goes through a proxy, so it only ever talks to the device named. No
login and no secret is sent.
"""

import http.client
import logging
import time

from beck.errors import TransportError

MAX_RESPONSE = 16 * 1024 * 1024  # bytes: Recalbox 10.1.1's list of BIOS files is about 140 KB

_log = logging.getLogger(__name__)


def get(host: str, port: int, path: str, timeout: float) -> bytes:
    """The body of a successful GET to ``http://host:port/path``. Else, a TransportError."""
    where = f"http://{host}:{port}{path}"
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    started = time.monotonic()
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != http.client.OK:
            raise TransportError(f"{where} answered {response.status} {response.reason}")
        body = response.read(MAX_RESPONSE + 1)
    except (OSError, http.client.HTTPException) as e:
        raise TransportError(f"No answer from {where}: {e}") from e
    finally:
        connection.close()
    if len(body) > MAX_RESPONSE:
        raise TransportError(f"{where} answered with more than {MAX_RESPONSE // 2**20} MiB")
    _log.debug("GET %s: %d bytes in %.3f s", where, len(body), time.monotonic() - started)
    return body
