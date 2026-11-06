# Security policy

## Supported versions

BECK hasn't had a release yet. Once it has, only the latest minor version gets security fixes.

## Reporting a vulnerability

Please report it privately, not in a public issue. On GitHub, go to the repository's **Security** tab and choose **Report a
vulnerability**.

If that option isn't there, open an issue that says only that you'd like to report a security problem and asks for a private way to do it.
Leave out the details.

A useful report says which version you used, what you ran, what happened, and what you expected. Please leave out your real passwords and
your BIOS files. For the output of a run, `--json` and `-v` already keep passwords out.

## What to expect

BECK is a small project with no security team, so replies are on a best-effort basis, with no fixed deadlines. If a report is confirmed, the fix and an
advisory go out together, and you'll be credited if you'd like that.

## What's in scope

BECK itself: the `beck` command, how it handles your credentials, your local files and the reports it reads, and its build and release process.
[The threat model](docs/threat-model.md) says what BECK protects and how, and the risks it accepts.

## What's out of scope

- **Recalbox and its Samba settings**, including its default guest access. Please report those to the Recalbox project.
- **The lack of encryption on SMB.** BECK's SMB library doesn't support it, so this is a [known limit](docs/threat-model.md#risks-it-accepts).
- **Bugs in a dependency** that BECK doesn't make worse. Please report those to its project, though it's useful to know if one affects BECK.
- **Someone who already controls your account or your computer,** who can read whatever BECK can.
- **BIOS files, or where to find them.** BECK doesn't provide them, and neither do its maintainers.
