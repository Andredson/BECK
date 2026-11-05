# Samba test server

A minimal Samba server for BECK's integration tests, built from our own `Containerfile` with Podman ([DEC-40](../../../docs/adr/0003-tooling.md#dec-40--own-minimal-samba-dockerfile-for-tests),
[DEC-55](../../../docs/adr/0003-tooling.md#dec-55--podman-only)). Podman runs it without root.
**It's for tests only:** guests can write to it, and its only password is a fake one in this repository. It publishes its
port on `127.0.0.1` only, so that nothing else on your network can reach it.

## Run it

```sh
podman build -t beck-samba tests/integration/samba
podman run -d --rm -p 127.0.0.1:4450:445 --name beck-samba beck-samba
```

Stop it with `podman stop beck-samba`. It keeps nothing: every run starts empty.

## Run the tests

```sh
BECK_TEST_SMB_HOST=127.0.0.1 BECK_TEST_SMB_PORT=4450 uv run pytest -m integration
```

Without those variables, they're skipped. They write to the server, so they first check for the `readonly` share and its
`seeded.txt`, and refuse any other server. **Never point them at a real Recalbox.** Tests run one at a time, because the
end-to-end ones share the report at the root of the `bios` share.

## Shares

| Share | Who | Used for |
|---|---|---|
| `bios` | Guests can write, with the settings of a real Recalbox 10.1.1 | Normal runs |
| `private` | Only the user `beck`, with the password `beck-test-password` | Password logins |
| `readonly` | Guests can read, and it has one file, `seeded.txt` | Error paths |

## Check that it works

This lists the three shares, using `pysmb` as BECK does:

```sh
uv run python -c "
from smb.SMBConnection import SMBConnection
c = SMBConnection('', '', 'beck', 'beck-samba', is_direct_tcp=True, use_ntlm_v2=True)
assert c.connect('127.0.0.1', 4450, timeout=10)
print(sorted(s.name for s in c.listShares() if not s.isTemporary))
c.close()"
```
