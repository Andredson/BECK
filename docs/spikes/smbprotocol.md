# Spike: smbprotocol against Recalbox's Samba

**Roadmap step:** [04.1](../../roadmap/04-architecture-refactor.md#041--spike-smbprotocol-against-a-real-recalbox-gate-for-dec-26)
· **Date:** 2026-11-04 · **Outcome:** the owner chose to keep `pysmb`
([DEC-53](../adr/0003-tooling.md#dec-53--keep-pysmb-not-smbprotocol)).

## Environment
- **Server:** Recalbox 10.1.1 x86_64 in a QEMU VM, Samba 4.19.6, not a real device
  ([DEC-52](../adr/0005-process-and-docs.md#dec-52--step-041-runs-on-a-vm)). The `bios` share allows guests, with
  `map to guest = bad user`. The only Samba account is `root`.
- **Client:** `smbprotocol` 1.17.0, `pyspnego` 0.12.4, `cryptography` 50.0.2, Python 3.11, in a temporary environment
  within the 14-day cooldown. The host's port 4445 forwards to the VM's port 445.
- **Compared with:** `pysmb` 1.2.15, which BECK used against the same VM in step 03.13.

## Results

| Check | Guest | Password (`root`) |
|---|---|---|
| Login with library defaults | **Failed** | Passed |
| Login with the settings below | Passed | Not needed |
| List the `bios` share | Passed | Passed |
| Read `missing_bios_report.txt`, MD5 matches the VM's | Passed | Passed |
| `makedirs` two new levels, write a file, `stat` it, read it back | Passed | Passed |
| Delete only the test file and folders | Passed | Passed |
| Negotiated dialect | SMB 3.1.1 | SMB 3.1.1 |
| `encrypt=True` | **Refused**: a guest session can't encrypt | Passed |

Guest login needs all three of these:
- **A non-empty user name.** An empty one fails in `pyspnego` before anything is sent to the server. Any other name
  that isn't a Samba account also logs in as a guest.
- **`require_signing=False`**, because a guest session has no key to sign with.
- **`ClientConfig(require_secure_negotiate=False)`**, which applies to the whole process. Password login passed with it
  on.

Other findings:
- A wrong password for the real `root` account fails with `LogonFailure`. An unknown user name doesn't fail: it logs in
  as a guest.
- Closing the connections after a failed login can raise `UserSessionDeleted`.
- A missing share and a missing file both raise `SMBOSError` with "No such file or directory".

## pysmb, for comparison
- It logs in as a guest with empty credentials and no other settings, in both NetBIOS and direct TCP modes.
- Its source has no SMB encryption code, so it can't encrypt, even with a password account.
- It has no recursive folder creation, so BECK keeps `SmbSession.ensure_dir` from step 03.9.

## Not verified
Real hardware. The real-device run in [step 10.11](../../roadmap/10-packaging-and-release.md#1011--define-and-reach-10)
covers BECK's final transport.

## The script
It creates only `beck-spike/` and one file of random bytes, deletes only those, and refuses to run if `beck-spike/`
already exists. On the VM, the folder was gone afterwards and the report's MD5 was unchanged. The password comes from
an environment variable and is never printed.

```sh
SPIKE_USER=root SPIKE_PASSWORD=<password> SPIKE_HOST=127.0.0.1 SPIKE_PORT=4445 \
  uv run --no-project --isolated --exclude-newer "14 days" --python 3.11 --with smbprotocol python spike.py
```

```python
"""Spike for roadmap step 04.1: does smbprotocol's smbclient API work against Recalbox's Samba?

Usage: SPIKE_HOST=127.0.0.1 SPIKE_PORT=445 python spike.py
Optional: SPIKE_USER and SPIKE_PASSWORD test a password login.

It reads the report, and creates only the folder beck-spike/ with one test file of random bytes. It
then deletes only those. It refuses to run if beck-spike/ already exists.
"""

import hashlib
import importlib.metadata
import os
import sys

import smbclient

HOST = os.environ.get("SPIKE_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPIKE_PORT", "445"))
USER = os.environ.get("SPIKE_USER", "")
PASSWORD = os.environ.get("SPIKE_PASSWORD", "")
SHARE = rf"\\{HOST}\bios"
SPIKE_DIR = rf"{SHARE}\beck-spike"
NESTED_DIR = rf"{SPIKE_DIR}\a\b"
TEST_FILE = rf"{NESTED_DIR}\beck spike (test).bin"

failures = 0


def close_connections():
    """A failed login can leave a broken session behind, and closing that one raises an error."""
    try:
        smbclient.reset_connection_cache()
    except Exception as e:  # noqa: BLE001 - a spike reports every failure and carries on
        print(f"NOTE  closing the connections raised {type(e).__name__}")


def check(label, action):
    global failures
    try:
        print(f"PASS  {label}: {action()}")
        return True
    except Exception as e:  # noqa: BLE001 - a spike reports every failure and carries on
        failures += 1
        print(f"FAIL  {label}: {type(e).__name__}: {str(e)[:200]}")
        return False


def login(label, **options):
    """Open a new connection with these options, and describe what the server negotiated."""
    close_connections()

    def run():
        session = smbclient.register_session(HOST, port=PORT, **options)
        names = smbclient.listdir(SHARE, port=PORT, **options)
        return (
            f"dialect=0x{session.connection.dialect:04x} encrypt={session.encrypt_data} "
            f"signing={session.signing_required} entries={len(names)}"
        )

    return check(label, run)


def write_and_clean_up(**options):
    def exists(path):
        return smbclient.path.exists(path, port=PORT, **options)

    if exists(SPIKE_DIR):
        print(f"STOP  {SPIKE_DIR} already exists, so nothing was written.")
        return False

    data = os.urandom(4096)
    try:

        def write():
            smbclient.makedirs(NESTED_DIR, exist_ok=True, port=PORT, **options)
            with smbclient.open_file(TEST_FILE, mode="wb", port=PORT, **options) as file:
                file.write(data)
            return f"{len(data)} bytes to a name with a space and parentheses"

        def read_back():
            size = smbclient.stat(TEST_FILE, port=PORT, **options).st_size
            with smbclient.open_file(TEST_FILE, mode="rb", port=PORT, **options) as file:
                same = file.read() == data
            assert same, "content differs"
            return f"stat size={size}, content identical"

        check("makedirs (two new levels) and write", write)
        check("stat and read back", read_back)
    finally:

        def clean_up():
            if exists(TEST_FILE):
                smbclient.remove(TEST_FILE, port=PORT, **options)
            for folder in (NESTED_DIR, rf"{SPIKE_DIR}\a", SPIKE_DIR):
                if exists(folder):
                    smbclient.rmdir(folder, port=PORT, **options)
            assert not exists(SPIKE_DIR)
            return "test file and beck-spike/ removed"

        check("delete the test file and folders", clean_up)
    return True


def read_report(**options):
    def run():
        path = rf"{SHARE}\missing_bios_report.txt"
        with smbclient.open_file(path, mode="rb", port=PORT, **options) as file:
            data = file.read()
        return f"{len(data)} bytes, md5={hashlib.md5(data, usedforsecurity=False).hexdigest()}"

    return check("read missing_bios_report.txt", run)


def main():
    version = importlib.metadata.version("smbprotocol")
    print(f"smbprotocol {version}, Python {sys.version.split()[0]}, {HOST}:{PORT}")

    print("\n== Guest login, library defaults")
    guest = {"username": "", "password": ""}
    default_ok = login("empty user, defaults", **guest)

    print("\n== Guest login, signing not required")
    unsigned = {**guest, "require_signing": False}
    unsigned_ok = login("empty user, require_signing=False", **unsigned)

    print("\n== Guest login, named guest user")
    named = {"username": "guest", "password": "", "require_signing": False}
    named_ok = login("user guest, require_signing=False", **named)

    print("\n== Guest login, named guest user, secure negotiate check off")
    smbclient.ClientConfig(require_secure_negotiate=False)
    negotiate_ok = login("user guest, require_signing=False, check off", **named)
    login(
        "unknown user, require_signing=False, check off", **{**named, "username": "beck-test-user"}
    )
    login("user guest, signing left on, check off", username="guest", password="")

    working = (
        guest
        if default_ok
        else unsigned
        if unsigned_ok
        else named
        if named_ok or negotiate_ok
        else None
    )
    if working is not None:
        print(f"\n== Basic operations as guest, options={sorted(working.items())}")
        close_connections()
        smbclient.register_session(HOST, port=PORT, **working)
        read_report(**working)
        write_and_clean_up(**working)

    print("\n== Encryption as guest")
    login("guest, encrypt=True", **(working or guest), encrypt=True)

    if USER:
        print("\n== Password login")
        account = {"username": USER, "password": PASSWORD}
        if login("user and password, defaults", **account):
            login("user and password, encrypt=True", **account, encrypt=True)
            close_connections()
            smbclient.ClientConfig(require_secure_negotiate=True)
            login("user and password, check back on", **account)
            close_connections()
            smbclient.register_session(HOST, port=PORT, **account)
            read_report(**account)
            write_and_clean_up(**account)

    print("\n== Wrong password for a real user")
    if USER:
        login("real user, wrong password", username=USER, password="beck-test-password")

    print("\n== Unknown user (map to guest = bad user)")
    login("unknown user", username="beck-test-user", password="beck-test-password")

    print("\n== Missing share")
    close_connections()
    smbclient.ClientConfig(require_secure_negotiate=False)
    check(
        "listdir on a share that doesn't exist",
        lambda: smbclient.listdir(
            rf"\\{HOST}\beck-spike-no-share", port=PORT, **(working or guest)
        ),
    )

    close_connections()
    print(f"\nfailures: {failures} (some of the login variants are expected to fail)")


if __name__ == "__main__":
    main()
```
