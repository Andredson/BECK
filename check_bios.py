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


def get_missing_bios(session):
    missing_regex = r"(MISSING (O|R)(.*\n[^\n].*)+)"
    path_file_regex = r"(?<=Path: )\/(?:[^\/\s]+\/)+(?=[^\/\s]+)"
    # relative_path_file_regex = r"(?<=Path: \/recalbox\/share\/bios\/)(?:[^\/]+\/)+(?=[^\/]+)"
    file_regex = r"([a-zA-Z0-9_]+\.[a-zA-Z0-9]+)"
    md5_regex = r"([a-fA-F0-9]{32})"

    report = session.read_text("missing_bios_report.txt")
    itens = re.findall(missing_regex, report)

    missing = []

    if len(itens) > 0:
        print(f"There are {MAGENTA}{len(itens)}{RESET} missing bios in your RECALBOX")
        for item in itens:
            item = str(item)
            name = re.search(file_regex, item)
            path = re.search(path_file_regex, item)
            relative_path = path.group(0).replace("/recalbox/share/bios/", "")
            hashs = set(re.findall(md5_regex, item))
            missing.append(
                {
                    "name": name.group(0),
                    "path": path.group(0),
                    "relativePath": relative_path,
                    "hashs": list(hashs),
                }
            )
    else:
        print(f"{CYAN}No missing bios were found in your RECALBOX!{RESET}")
        exit()

    return missing


def get_possible_bios(folder_path):

    bios = []

    for root, _, files in os.walk(folder_path):
        if len(files) > 0:
            print(
                f"There are {MAGENTA}{len(files)}{RESET} possible bios to be analysed in your system"
            )
            for filename in files:
                file_path = os.path.join(root, filename)
                with open(file_path, "rb") as f:
                    file_data = f.read()
                    file_md5 = hashlib.md5(file_data).hexdigest()
                    bios.append({"name": filename, "hash": file_md5.upper()})
        else:
            print(f"{CYAN}No bios were found to analyse in your system!{RESET}")
            exit()
    return bios


def validate_bios(bios, report, session):

    script_path = f"{os.path.dirname(__file__)}/bios/"
    bios_found = 0

    for item in bios:
        found = False
        for sums in report:
            for sum in sums["hashs"]:
                if sum == item["hash"]:
                    found = True
                    if item["name"] != sums["name"]:
                        try:
                            os.rename(
                                f"{script_path}{item['name']}",
                                f"{script_path}{sums['name']}",
                            )
                        except Exception as e:
                            print(f"Error renaming {RED}{item['name']}{RESET}: {YELLOW}{e}{RESET}")
                            exit(1)
                    if not sums["relativePath"] == "":
                        directories = session.list_dirs("")
                        dir_exist = False
                        path = sums["relativePath"][:-1]
                        for dir in directories:
                            if dir == path:
                                dir_exist = True
                                break

                        if not dir_exist:
                            session.make_dir(sums["relativePath"])

                    local = Path(f"{script_path}{sums['name']}")
                    session.upload(local, f"{sums['relativePath']}{sums['name']}")
                    # Old behavior, kept until step 03.10: delete the local file after upload.
                    try:
                        local.unlink()
                    except OSError as e:
                        raise BeckError(f"Error deleting {local} after upload: {e}") from e
                    bios_found += 1
                    print(f"{GREEN}FOUND:{RESET} {sums['name']}")

        if not found:
            try:
                os.remove(f"bios/{item['name']}")
                print(f"File {YELLOW}{item['name']}{RESET} removed.")
            except:
                print(f"Failed to remove the file: {RED}{item['name']}{RESET}")
                exit(1)

    return bios_found


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
            # Create a validation for duplicated md5sum of files
            validated_bios = validate_bios(bios, report, session)
    except BeckError as error:
        print(f"{RED}Error{RESET}: {error}")
        sys.exit(1)

    print(
        f"Final result of {GREEN}bios found{RESET}/{BLUE}files analysed{RESET}: ({GREEN}{validated_bios}{RESET}/{BLUE}{len(bios)}{RESET})"
    )

    if validated_bios > 0:
        print(f"{MAGENTA}*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***{RESET}")


if __name__ == "__main__":
    main()
