import hashlib
import io
import os
import re
import socket
import sys
from pathlib import Path
from typing import Any

import yaml
from smb.SMBConnection import SMBConnection

RESET = "\033[0m"
BOLD = "\033[1m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"
BLINK = "\033[5m"

BLACK = "\033[30m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

RECALBOX_BIOS_ROOT = "/recalbox/share/bios/"

# How a missing-BIOS report is laid out; see tests/fixtures/reports/ for real examples.
BLOCK_HEADING = re.compile(
    r"^[ \t]*MISSING (?:REQUIRED|OPTIONAL) BIOS\b:?[ \t]*(.*)$", re.MULTILINE
)
PATH_LINE = re.compile(r"^[ \t]*Path:[ \t]*(.+)$", re.MULTILINE)
MD5 = re.compile(r"\b[a-fA-F0-9]{32}\b")


def load_configs(file: str) -> dict[str, Any]:
    try:
        with open(file) as l:
            data = yaml.safe_load(l)
    except FileNotFoundError:
        print(
            f"{RED}Error{RESET}: {file} not found. "
            "Copy config/config.example.yml to config/config.yml and fill it in."
        )
        exit(1)

    try:
        configs: dict[str, Any] = data["smb"]
    except:
        print(f"{RED}Error{RESET}: trying to get server name and credencials")
        exit(1)

    return configs


class BeckError(Exception):
    """An error with a message for the user. Only main() prints it and exits."""


class ReportParseError(BeckError):
    """The missing-BIOS report has a block BECK can't read."""


def client_name() -> str:
    """The name BECK gives itself on the SMB connection: this computer's host name, or "BECK"."""
    try:
        return socket.gethostname() or "BECK"
    except OSError:
        return "BECK"


class SmbSession:
    """One SMB connection to one share for the whole run.

    It connects once, checks the share once and always closes. pysmb raises many unrelated
    exception types, so each operation turns any failure into a BeckError.
    """

    def __init__(self, server: str, port: int, user: str, password: str, share: str) -> None:
        self.server = server
        self.port = port
        self.user = user
        self.password = password
        self.share = share
        self._conn: Any = None

    def __enter__(self) -> "SmbSession":
        # Port 445 is SMB over plain TCP; port 139 needs a NetBIOS session first (defect D16).
        conn = SMBConnection(
            self.user,
            self.password,
            client_name(),
            self.server,
            use_ntlm_v2=True,
            is_direct_tcp=self.port == 445,
        )
        try:
            self._open(conn)
        except BaseException:
            conn.close()  # __exit__ doesn't run when __enter__ fails
            raise
        self._conn = conn
        return self

    def __exit__(self, *exc: object) -> None:
        self._conn.close()

    def _open(self, conn: Any) -> None:
        try:
            logged_in = conn.connect(self.server, self.port)
        except Exception as e:
            raise BeckError(f"Error connecting to SMB server {self.server}: {e}") from e
        if not logged_in:
            raise BeckError(
                f"SMB server {self.server} refused the login: check user and passwd in the config"
            )
        try:
            shares = conn.listShares()
        except Exception as e:
            raise BeckError(f"Error listing the shares of SMB server {self.server}: {e}") from e
        if not any(s.name == self.share for s in shares):
            raise BeckError(f"The share {self.share} doesn't exist on SMB server {self.server}")

    def read_text(self, path: str) -> str:
        """Read a remote text file into memory; no local or temporary file is written (D6)."""
        buffer = io.BytesIO()
        try:
            self._conn.retrieveFile(self.share, path, buffer)
        except Exception as e:
            raise BeckError(f"Error reading {path} from share {self.share}: {e}") from e
        return buffer.getvalue().decode("utf-8", errors="replace")

    def upload(self, local: Path, remote: str) -> None:
        """Copy a local file to the share; the local file is closed before this returns (D7)."""
        try:
            with local.open("rb") as file:
                self._conn.storeFile(self.share, remote, file)
        except Exception as e:
            raise BeckError(
                f"Error uploading {local} to {remote} on share {self.share}: {e}"
            ) from e

    def list_dirs(self, path: str) -> list[str]:
        """Names of the folders directly inside a remote folder ("" is the share root)."""
        try:
            entries = self._conn.listPath(self.share, path)
        except Exception as e:
            raise BeckError(f"Error listing folder {path!r} on share {self.share}: {e}") from e
        return [e.filename for e in entries if e.isDirectory and e.filename not in (".", "..")]

    def make_dir(self, path: str) -> None:
        try:
            self._conn.createDirectory(self.share, path)
        except Exception as e:
            raise BeckError(f"Error creating folder {path} on share {self.share}: {e}") from e


def parse_report(text: str) -> list[dict[str, Any]]:
    """Turn a missing-BIOS report into one entry per ``MISSING ... BIOS`` block, in report order.

    Pure: no I/O. Each entry has ``name``, ``path`` (folder, with a trailing slash),
    ``relativePath`` (the folder inside the ``bios`` share) and ``hashes`` (lowercase).
    """
    text = text.replace("\r\n", "\n")
    headings = list(BLOCK_HEADING.finditer(text))
    missing = []

    for heading, following in zip(headings, [*headings[1:], None], strict=False):
        block = text[heading.end() : following.start() if following else len(text)]
        first_line = heading.group(0).strip()
        name = heading.group(1).strip()
        location = PATH_LINE.search(block)
        hashes = list(dict.fromkeys(md5.lower() for md5 in MD5.findall(block)))

        if not name:
            raise ReportParseError(f"No file name in report block: {first_line}")
        if location is None:
            raise ReportParseError(f"No Path line in report block: {first_line}")
        if not hashes:
            raise ReportParseError(f"No MD5 value in report block: {first_line}")

        # A Path line can list two locations ("<path> or <path>"): use the first (DEC-50).
        first_path = location.group(1).split(" or ")[0].strip()
        if not first_path.startswith(RECALBOX_BIOS_ROOT):
            raise ReportParseError(f"Path is outside {RECALBOX_BIOS_ROOT}: {first_line}")
        folder = f"{first_path.rpartition('/')[0]}/"
        missing.append(
            {
                "name": name,
                "path": folder,
                "relativePath": folder.removeprefix(RECALBOX_BIOS_ROOT),
                "hashes": hashes,
            }
        )

    return missing


def get_missing_bios(session: SmbSession) -> list[dict[str, Any]]:
    missing = parse_report(session.read_text("missing_bios_report.txt"))

    if not missing:
        print(f"{CYAN}No missing bios were found in your RECALBOX!{RESET}")
        exit()

    print(f"There are {MAGENTA}{count_targets(missing)}{RESET} missing bios in your RECALBOX")
    return missing


def file_md5(path: str) -> str:
    """A file's MD5 in lowercase, read in chunks. MD5 identifies files; it isn't for security."""
    with open(path, "rb") as f:
        return hashlib.file_digest(f, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()


def get_possible_bios(folder_path: str) -> list[dict[str, str]]:
    """Every non-hidden file under a folder, with its path relative to that folder, and its MD5."""
    bios = []

    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [name for name in dirs if not name.startswith(".")]  # don't enter hidden folders
        for filename in files:
            if filename.startswith("."):
                continue
            file_path = Path(root, filename)
            bios.append(
                {
                    "name": filename,
                    "path": file_path.relative_to(folder_path).as_posix(),
                    "hash": file_md5(str(file_path)),
                }
            )

    if not bios:
        print(f"{CYAN}No BIOS files found in {folder_path}{RESET}")
        exit()

    print(f"There are {MAGENTA}{len(bios)}{RESET} possible bios to be analysed in your system")
    return sorted(bios, key=lambda item: item["path"])


def remote_target(entry: dict[str, Any]) -> str:
    """Where a report entry's file goes on the share. Different entries can share one target."""
    return f"{entry['relativePath']}{entry['name']}"


def count_targets(report: list[dict[str, Any]]) -> int:
    return len({remote_target(entry) for entry in report})


def validate_bios(
    bios: list[dict[str, str]], report: list[dict[str, Any]], session: SmbSession
) -> int:
    """Upload each matching local file to its targets; return how many targets were filled.

    A file is uploaded straight from its own path, under each target's name. The first file (sorted
    by path) wins: identical copies and later files for an already filled target are skipped.
    """
    script_path = f"{os.path.dirname(__file__)}/bios/"
    entries_by_md5: dict[str, list[dict[str, Any]]] = {}
    for entry in report:
        for md5 in entry["hashes"]:
            entries_by_md5.setdefault(md5, []).append(entry)

    used_md5s: dict[str, str] = {}
    filled_targets: dict[str, str] = {}

    for item in sorted(bios, key=lambda item: item["path"]):
        md5 = item["hash"]

        if md5 not in entries_by_md5:
            try:
                os.remove(f"bios/{item['path']}")
                print(f"File {YELLOW}{item['path']}{RESET} removed.")
            except:
                print(f"Failed to remove the file: {RED}{item['path']}{RESET}")
                exit(1)
            continue

        if md5 in used_md5s:
            print(f"{YELLOW}Duplicate, skipped:{RESET} {item['path']} (same as {used_md5s[md5]})")
            continue
        used_md5s[md5] = item["path"]

        local = Path(f"{script_path}{item['path']}")
        uploaded = False
        for entry in entries_by_md5[md5]:
            target = remote_target(entry)
            if target in filled_targets:
                continue
            if entry["relativePath"]:
                directories = session.list_dirs("")
                if entry["relativePath"][:-1] not in directories:
                    session.make_dir(entry["relativePath"])
            session.upload(local, target)
            filled_targets[target] = item["path"]
            uploaded = True
            print(f"{GREEN}FOUND:{RESET} {entry['name']} -> {target}")

        if not uploaded:
            print(f"{YELLOW}Already filled, skipped:{RESET} {item['path']}")
            continue

        # Old behavior, kept until step 03.10: delete the local file after upload.
        try:
            local.unlink()
        except OSError as e:
            raise BeckError(f"Error deleting {local} after upload: {e}") from e

    return len(filled_targets)


def main() -> None:
    configs = load_configs("config/config.yml")

    try:
        with SmbSession(
            server=configs["server"],
            port=configs["port"],
            user=configs["user"],
            password=configs["passwd"],
            share="bios",
        ) as session:
            report = get_missing_bios(session)
            bios = get_possible_bios("./bios")
            validated_bios = validate_bios(bios, report, session)
    except BeckError as error:
        print(f"{RED}Error{RESET}: {error}")
        sys.exit(1)

    print(
        f"Final result: {GREEN}{validated_bios}{RESET}/{BLUE}{count_targets(report)}{RESET} "
        f"missing entries satisfied, {len(bios)} files analysed"
    )

    if validated_bios > 0:
        print(f"{MAGENTA}*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***{RESET}")


if __name__ == "__main__":
    main()
