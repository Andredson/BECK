# BECK - BIOS CHECKER for ReCALBOX! 
simple script to validate and send verified bios files via smb to your RECALBOX system.

## Pre-requisites
Minimun python 3.10 and the dependencies will be installed with the command below.
```sh
pip install -r requirements
```

## Structure
```
┌───────────────────┐
│       BECK        │
└───────────────────┘

┌BECK
├── bios_bios.py
├─┬─bios
│ └── *
├──bios
├─┬─config
│ └── config.yml
├── requirements.txt
├── .gitignore
├── readme.MD
└── LICENSE
```
## Usage
Please put your possible bios files into the **bios** folder.

```sh
./bios_bios.py
```
### Support

Recalbox 9.1