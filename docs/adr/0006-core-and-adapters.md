# ADR-0006 — Core and adapters

- **Status:** Accepted
- **Date:** 2026-11-04
- **Decisions covered:** none of its own. It describes the structure that follows from DEC-02, DEC-03, DEC-04 and
  DEC-53, and from the [stage 04 plan](../../roadmap/04-architecture-refactor.md) (rows in the
  [decision log](../../roadmap/README.md#decision-log)).

## Context
At the end of stage 03, all of BECK is one script, `check_bios.py`: SMB access, report parsing, hashing, matching, upload
and output. Tests reach the logic only by replacing `pysmb` with a fake. Three later needs don't fit that shape:

- DEC-03 needs more frontends later, and each has its own report format and paths.
- DEC-04 needs a second transport, a local folder.
- Stage 06 needs other output (`--json`) and a dry run, so deciding what to do must be separate from doing it.

## Decision
Split BECK into a package with a **core** (`models`, `hashing`, `matcher`) and **adapters** (`frontends/`, `transports/`,
`output/`). `executor` applies a plan through the `Transport` Protocol, and `cli.py` connects the parts.
[ARCHITECTURE.md](../ARCHITECTURE.md) has the layout, the data flow and the rules.

The main choices within that:

- **The matcher builds a `Plan` and doesn't act on it.** A dry run is then the same plan with no writes, and matching can
  be tested with plain data.
- **Interfaces are `typing.Protocol` classes**, so adapters don't inherit from anything.
- **Models are frozen dataclasses**, with remote paths relative to the BIOS root.
- **`LocalTransport` doubles as the main test double**, so most tests use real files in `tmp_path`.
- **Only two extension points.** There's no plugin system, because nothing needs one yet.

## Alternatives considered
This structure came from the roadmap plan, and these options weren't put to the owner as a separate decision. The
owner's related choices are recorded in [ADR-0001](0001-product-scope.md):

- *Recalbox only, with no frontend interface* (DEC-03): simplest, but needs rework for any second frontend. Not chosen.
- *SMB only* (DEC-04): no local mode, and real-file tests become harder. Not chosen.

Keeping one script was ruled out by the stage's goal, because it can't offer those seams.

## Consequences
- **Easier:** testing without a network, adding a frontend or transport, and adding output formats.
- **Harder:** more files and indirection for a small tool, so the rules in ARCHITECTURE.md have to be kept on purpose.
- **Library choice stays contained:** only `transports/smb.py` uses `pysmb` (DEC-53), so changing it later touches one
  module.
- **Roadmap:** steps 04.3–04.14 build this. The stage's acceptance criteria check the main rules: only `cli.py` exits, and
  no core module imports a transport.
- **Revisit if:** a frontend can't be expressed as a report path plus a parser, or a target can't offer the `Transport`
  operations.
