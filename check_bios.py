from smb.SMBConnection import SMBConnection
import tempfile
import hashlib
import socket
import yaml
import json
import re
import os

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


def load_configs(file):
    with open(file) as l:
        data = yaml.safe_load(l)
        try:
            configs = data["smb"]
        except:
            print(f"{RED}Error{RESET}: trying to get server name and credencials")
            exit(1)

    return configs


def smb_connect(share: str, folder: str, operation: str, file=None) -> str:
    configs = load_configs("config/config.yml")

    response = ""
    server = configs["server"]
    port = configs["port"]
    username = configs["user"]
    password = configs["passwd"]
    hostname = socket.gethostbyname(socket.gethostname())

    conn = SMBConnection(username, password, hostname, server, use_ntlm_v2=True)

    try:
        conn.connect(server, port)
    except Exception as e:
        print(f'{RED}Error connecting to SMB server {server}:{RESET} {e}')
        exit(1)

    try:
        shares = conn.listShares()
    except Exception as e:
        print(f'{RED}Error listing shares of the {server} SMB server:{RESET} {e}')
        exit(1)

    found = False

    for s in shares:
        if s.name == share:
            found = True

    if not found:
        print(f'The specified share {RED}({share}){RESET} dosent exist in the server {RED}{server}{RESET}.')
        exit(1)

    match operation:
        case 'r':
            try:
                f = tempfile.NamedTemporaryFile()
                conn.retrieveFile(share,f'{folder}{file}',f)
                f.seek(0)
                f = f.read()
                report = f.decode('utf-8')
                f = open("test.txt", "w")
                f.write(report)
                f.close()
                f = open("test.txt", "r")
                report = f.read()
                os.remove('test.txt')
                response = report
                
            except Exception as e:
                print(f'Error reading {RED}{file}{RESET}: {YELLOW}{e}{RESET}')
                exit(1)

            return response

        case 'w':
            try:
                file_content = open(file, "rb")
                conn.storeFile(share, folder, file_content)
                os.remove(file)

            except Exception as e:
                print(f'Error writing {RED}{file}{RESET}: {YELLOW}{e}{RESET}')
                exit(1)

            return

        case 'cd':
            try:
                conn.createDirectory(share, folder)

            except Exception as e:
                print(f'Error creating directory {RED}{file}{RESET}: {YELLOW}{e}{RESET}')
                exit(1)
        
        case 'ld':
            try:

                folder_names = []
                response = conn.listPath(share, folder)

                for item in response:
                    if item.isDirectory and item.filename not in ['.', '..']:
                        folder_names.append(item.filename)

                response = folder_names

            except Exception as e:
                print(f'Error creating directory {RED}{file}{RESET}: {YELLOW}{e}{RESET}')
                exit(1)

            return response

        case _:
            print(f'Invalid operation for function: {RED}smb_connect{RESET}')
            exit(1)


def get_missing_bios():
    missing_regex = r"(MISSING (O|R)(.*\n[^\n].*)+)"
    path_file_regex = r"(?<=Path: )\/(?:[^\/\s]+\/)+(?=[^\/\s]+)"
    #relative_path_file_regex = r"(?<=Path: \/recalbox\/share\/bios\/)(?:[^\/]+\/)+(?=[^\/]+)"
    file_regex = r"([a-zA-Z0-9_]+\.[a-zA-Z0-9]+)"
    md5_regex = r"([a-fA-F0-9]{32})"

    report = smb_connect("bios", "", "r", "missing_bios_report.txt")
    itens = re.findall(missing_regex, report)

    missing = []

    if len(itens) > 0:
        print(f'There are {MAGENTA}{len(itens)}{RESET} missing bios in your RECALBOX')
        for item in itens:

            item = str(item)
            name = re.search(file_regex, item)
            path = re.search(path_file_regex, item)
            relative_path = path.group(0).replace('/recalbox/share/bios/','')
            hashs = set(re.findall(md5_regex, item))
            missing.append(
                {"name": name.group(0), "path": path.group(0), "relativePath": relative_path, "hashs": list(hashs)}
            )
    else:
        print(f'{CYAN}No missing bios were found in your RECALBOX!{RESET}')
        exit()

    return missing


def get_possible_bios(folder_path):
    
    bios = []

    for root, _, files in os.walk(folder_path):
        if len(files) > 0:
            print(f'There are {MAGENTA}{len(files)}{RESET} possible bios to be analysed in your system')
            for filename in files:
                file_path = os.path.join(root, filename)
                with open(file_path, "rb") as f:
                    file_data = f.read()
                    file_md5 = hashlib.md5(file_data).hexdigest()
                    bios.append({"name": filename, "hash": file_md5.upper()})
        else:
            print(f'{CYAN}No bios were found to analyse in your system!{RESET}')
            exit()
    return bios


def validate_bios(bios, report):
    
    script_path = f"{os.path.dirname(__file__)}/bios/"
    bios_found = 0

    for item in bios:
        found = False
        for sums in report:
            for sum in sums["hashs"]:
                if sum == item["hash"]:
                    found = True
                    if item['name'] != sums['name']:
                        try:
                            os.rename(f"{script_path}{item['name']}",f"{script_path}{sums['name']}",)
                        except Exception as e:
                            print(f"Error renaming {RED}{item['name']}{RESET}: {YELLOW}{e}{RESET}")
                            exit(1)
                    if not sums['relativePath'] == '':
                        
                        directories = smb_connect('bios', '', 'ld')
                        dir_exist = False
                        path = sums['relativePath'][:-1]
                        for dir in directories:
                            if dir == path:
                                dir_exist = True
                                break

                        if not dir_exist:
                            smb_connect('bios', sums['relativePath'], 'cd')

                    smb_connect('bios', f"{sums['relativePath']}{sums['name']}", 'w', f"{script_path}{sums['name']}")
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

def main():

    report = get_missing_bios()
    bios = get_possible_bios('./bios')
    # Create a validation for duplicated md5sum of files
    validated_bios = validate_bios(bios, report)
    print(f'Final result of {GREEN}bios found{RESET}/{BLUE}files analysed{RESET}: ({GREEN}{validated_bios}{RESET}/{BLUE}{len(bios)}{RESET})')

    if validated_bios > 0:
        print(f'{MAGENTA}*** PLEASE SCAN THE BIOS ON YOUR RECALBOX ***{RESET}')

if __name__ == "__main__":
    main()
