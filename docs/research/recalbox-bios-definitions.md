# Where Recalbox defines its BIOS files

Research for [step 11.2](../../roadmap/11-feature-expansion.md#112--report-less-recalbox-mode): can BECK know what's missing without the
report the user generates? Done on 2026-11-11, on Recalbox 10.1.1 x86_64 in a QEMU VM, read-only, with the owner's OK, and in Recalbox's
public source. It led to DEC-79.

## The list of BIOS files: `es_bios.xml`

- **Where:** `/recalbox/share_init/system/.emulationstation/es_bios.xml`, with `es_bios.xsd`, on the read-only system disk. There's no
  copy or override under `/recalbox/share`.
- **Not reachable over SMB.** Recalbox 10.1.1's Samba shares are `share` (`/recalbox/share`), `bios`, `roms (internal)`,
  `roms (network)`, `logs` and `system`. None of them reaches `/recalbox/share_init`.
- **Format:** `<system fullname platform>` holding `<bios path md5 core mandatory? hashMatchMandatory? note?/>`. `md5` lists accepted
  hashes, separated by commas. `mandatory` and `hashMatchMandatory` are `true` when they're left out. A `path` can give two locations
  separated by `|`, and one of those is outside the BIOS folder: `neogeo.zip|/recalbox/share/roms/neogeo/neogeo.zip`.
- **Size on 10.1.1:** 67 systems and 357 entries. 122 are `mandatory="false"`, and 81 are `hashMatchMandatory="false"`.

Bundling a copy of this file in BECK was considered and not chosen: BECK would then carry a database of hashes, which it has never done,
and need a new copy for every Recalbox release.

## The web manager's API

Recalbox's web manager (v3, port 80) calls an API on port 81. Its source is in Recalbox's frontend, in
`projects/frontend/es-app/src/web/server/` of [the Recalbox repository](https://gitlab.com/recalbox/recalbox): the routes are in
`IRouter.h`, and the handlers in `handlers/RequestHandler.cpp`. They were added with web manager v3, in a commit of 2023-11-29.

| Route | What it does |
|---|---|
| `GET /api/bios` | Every system's BIOS files, with their status. It scans the BIOS folder on each call. |
| `GET /api/bios/get/<system>` | The same, for one system. |
| `GET /api/bios/download` | Writes `/recalbox/share/system/bios_backup.zip` on the device, with the BIOS files a user added, and sends it. Not read-only. |
| `POST /api/bios/upload/<name>` | Takes a file, looks it up by name and MD5, and saves it where Recalbox expects it. |

The server binds every address, uses plain HTTP, and asks for no login.

`GET /api/bios` answers `{system: {"fullName", "scanResult", "biosList": {path: bios}}}`. Each `bios` has `mandatory`,
`hashMatchingMandatory`, `displayFileName`, `notes`, `currentMd5` (upper case, or all zeros with no file), `md5List`, `cores`,
`lightStatus` (`Green`, `Yellow`, `Red`) and `realStatus` (`HashMatching`, `FileNotFound`, `HashNotMatching`). On 10.1.1, the `path` keys
are relative to the BIOS folder. In newer source, the key is `bios.Filepath()`, which may be a whole path, so BECK accepts both.

## The API and the report give the same list

The report lists each BIOS whose `realStatus` is `FileNotFound` as missing, and each `HashNotMatching` one as incorrect only if
`hashMatchingMandatory` is true. `REQUIRED` or `OPTIONAL` is `mandatory`. On the VM, comparing the API on 2026-11-11 with the report of
2026-11-06, with nothing changed in between that the report could see:

- all 80 targets agree, and so do their MD5 lists, with no differences;
- the API has one more problem, `geolith/neocdz.zip`: `HashNotMatching` with `hashMatchingMandatory` false. The report leaves such an entry
  out, as the 03.13 run noticed, so BECK does too.

## How Recalbox hashes a `.zip` target

Found while doing this research, and used for [step 11.4](../../roadmap/11-feature-expansion.md#114--zip-aware-matching) (DEC-74,
DEC-78). For a `.zip` target, `Bios::Scan` calls `Zip::Md5Composite`, in `es-core/src/utils/Zip.cpp` of
[EmulationStation for Recalbox](https://gitlab.com/recalbox/recalbox-emulationstation). It sorts the members' names, as libzip gives them,
byte by byte, and takes one MD5 over all their bytes in that order. An archive libzip can't open gives an empty hash, which Recalbox logs
as `[Bios] Invalid MD5:`.

## Open questions

- **Older versions:** the API arrived with web manager v3, so Recalbox before that has none, and a user can turn the web manager off.
  BECK falls back to the report then. Only 10.1.1 was checked.
- **Real hardware:** only the VM was checked.
