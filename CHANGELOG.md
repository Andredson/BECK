# Changelog

Notable changes to BECK, in the layout of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This file is generated from the commit messages by [git-cliff](https://git-cliff.org/), so don't edit it by hand.
Changes to the documentation, tests and tooling aren't listed.

## [1.1.0] - 2026-11-12

### Added

- cli: Add an export command that copies BIOS files from the target
- scan: Match BIOS files inside zip archives
- recalbox: Detect missing BIOS without a generated report
- output: Group results by system

### Fixed

- output: Count only files on disk in files_scanned
## [1.0.1] - 2026-11-11

### Fixed

- matcher: Never upload a file that isn't a zip archive to a zip target
## [1.0.0] - 2026-11-11

### Added

- **Breaking:** Remove check_bios.py, requirements.txt and the bare beck alias
## [0.5.0] - 2026-11-11

### Added

- core: Add error hierarchy with stable exit codes
- core: Add typed domain models
- frontends: Add adapter interface and Recalbox adapter
- transports: Add transport interface and local folder transport
- transports: Implement SMB transport on pysmb
- core: Add plan executor with dry-run and per-item error handling
- output: Add console renderer with NO_COLOR support and logging
- cli: Add check, scan and report subcommands
- cli: Select SMB or local targets and the frontend adapter
- cli: Add --source and offline --report-file options
- executor: Apply the agreed policy for existing remote files
- cli: Add dry-run and opt-in move/clean flags with confirmation
- executor: Warn when an upload changes the file extension
- output: Add versioned JSON output for all commands
- cli: Return documented exit codes and support --fail-if-missing
- cli: Add verbosity and color controls
- cli: Add read-only scan and report commands
- config: Load and validate a TOML configuration file
- config: Resolve settings from flags, environment, file and defaults
- **Breaking:** config: Switch to TOML config with migration from config.yml
- config: Support guest, environment and prompted SMB credentials
- transfer: Verify uploads by size and optionally by MD5
- skills: Add execute-roadmap-step skill
- skills: Add quality-gates skill
- skills: Add add-report-fixture skill
- skills: Add add-frontend-adapter skill
- skills: Add diagnose-missing-bios skill for end-user support
- skills: Add cut-release skill

### Changed

- Clean up messages, exceptions and unused code
- core: Move hashing and scanning into beck.hashing
- core: Extract a pure matcher that builds an upload plan
- **Breaking:** cli: Route all behavior through the beck package

### Fixed

- **Breaking:** config: Stop tracking config.yml and ship config.example.yml
- smb: Use one closed-on-exit SMB session and read reports in memory
- parser: Extract full file names and parse report blocks robustly
- hashing: Compare MD5 values case-insensitively and hash in chunks
- scanner: Ignore hidden files and scan sub-folders without exiting early
- matching: Upload one file to every matching target without renaming it
- smb: Create nested remote BIOS folders one level at a time
- **Breaking:** Never delete local files; copy matched BIOS files only
- paths: Resolve config and bios folders relative to the script
- matching: Give each target to the file already named like it
- parser: Handle a UTF-8 BOM, and cover every fixture and edge case
- parser: Keep INCORRECT blocks apart and reject unrecognized reports
- hashing: Report unreadable local files and keep going
- output: Show undecodable file names and failed dry-run checks correctly
- output: Keep a run and its exit code independent of its output streams
- transports: Report a failed check the same way on every Python
- output: Escape control characters in names shown to people
- security: Redact credentials in logs, errors and JSON output
- security: Reject unsafe target paths from reports
- output: Show the form of a target URL whole in messages

## [0.1.0] - 2023-12-31 to 2025-07-21

### Earlier history

- Initial commit
- Adding the default configuration file for smb connection to RECALBOX
- Adding the first version of the script
- Adding the gitignore and requirements file for this project
- Adding a good reame for this project and an update for uncreated folders in the server
- Fixing the Structure topic in the readme topic
- Update README.md
- Merge branch 'main' of github.com:Andredson/RECALBOX_bios_checker
- Update README.md
- Fixing some error on readme
- Adding the default folder to check for valid bios
