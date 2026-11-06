# Generating the missing-BIOS report

BECK copies only what your Recalbox says it's missing, and that list is a file your Recalbox writes when you ask it to. So this comes first, and again whenever the list changes.

## Generating it

| Recalbox | Where to find it | Checked on |
|---|---|---|
| 10.1.1 | Main menu → **BIOS CHECKING** → **REPORT** | A virtual machine, 2026-11-06 |

1. On your Recalbox, open the main menu.
2. Choose **BIOS CHECKING**.
3. Choose **REPORT**.

<!-- A screenshot of each screen could go here. It must not show any personal data, such as a network name, a user name or a game library. -->

On another version, the menu may differ. BECK is only tested with the versions in this table. If a report's format has changed, BECK says it can't read it, and exits with 4: it won't mistake that for nothing being missing.

### The numbers on that screen

**BIOS CHECKING** shows its own counts, and they don't have to match the report. In one check on 10.1.1, the screen said 21 not found and 151 correct, while the report listed 81 entries. We don't know how the screen counts,
so go by the report, which is what BECK reads.

BECK's count can differ slightly from the report's too, because it counts a file once even if several systems list it. In that same report, `neogeo.zip` was listed twice, so BECK said 80.

## Where it ends up

It's a text file, `missing_bios_report.txt`, at the top of the BIOS folder:

- on your Recalbox, that's `/recalbox/share/bios/missing_bios_report.txt`;
- over the network, it's at the top of the `bios` share.

## Checking that it's there

The simplest way is to ask BECK, which lists what the report says. It changes nothing:

```sh
beck report
```

If it says `missing_bios_report.txt not found`, the report hasn't been generated, or BECK is looking at the wrong device: `beck config show` says which target it's using.

You can also open the share in a file manager:

- on Linux or macOS, at `smb://recalbox.local/bios`;
- on Windows, at `\\recalbox.local\bios`.

If your Recalbox's name doesn't work, use its IP address instead.

## What's in it

The report starts with a short header, with the date it was generated. Then, for each system, it lists each file:

```text
==============================================================
MISSING BIOS REPORT
Platform: x86_64
Generated on 2026/Nov./04 16:48:14+0100
==============================================================

SYSTEM: Amiga 1200 (AGA)
---------------------------------------------

  MISSING REQUIRED BIOS: kick39106.A1200
    Path: /recalbox/share/bios/amiga/bios/kick39106.A1200
    For: amiberry
    Possible MD5 List:
      B7CC148386AA631136F510CD29E42FC3
```

- **`MISSING`** means the file isn't there, and **`INCORRECT`** means it's there with the wrong content. BECK keeps an incorrect file unless you add `--overwrite`.
- **`REQUIRED`** and **`OPTIONAL`** say whether that system needs the file.
- **A report with only the header** means nothing is missing.

## When to generate it again

The report is a snapshot, so it doesn't change by itself. Generate it again after you've copied files, to see what's still missing, and whenever BECK says a file is `already on the device, kept`, which usually means the report is out of date.
