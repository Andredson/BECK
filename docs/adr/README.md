# Architecture Decision Records

ADRs explain **why** BECK works the way it does: the context, what was decided, what else was considered, and
the consequences. The short form of every decision is a `DEC-NN` row in the
[roadmap decision log](../../roadmap/README.md#decision-log); the ADRs hold the reasoning.

## Index

| ADR | Title | Status | Decisions |
|---|---|---|---|
| [0001](0001-product-scope.md) | Product scope | Accepted | DEC-01, 02, 03, 04, 09, 10, 12, 13, 15, 50, 54 |
| [0002](0002-ai-agent-support.md) | AI-agent support | Accepted | DEC-05, 06, 21, 22, 23, 43, 44, 46, 47 |
| [0003](0003-tooling.md) | Tooling | Accepted | DEC-07, 08, 17, 18, 19, 24, 26, 27, 28, 29, 36, 40, 42, 45, 49, 53, 55 |
| [0004](0004-ci-security-release.md) | CI, security and release | Accepted | DEC-11, 25, 32, 33, 34, 35, 37, 38, 41, 48 |
| [0005](0005-process-and-docs.md) | Process and documentation | Accepted | DEC-14, 16, 20, 30, 31, 39, 51, 52 |
| [0006](0006-core-and-adapters.md) | Core and adapters | Accepted | None of its own (follows from DEC-02, 03, 04, 53) |
| [0007](0007-cli-contract.md) | The CLI contract | Accepted | None of its own (follows from DEC-02, 05, 17, 23, 54) |


## Adding a decision

1. Make sure the owner made the decision. Agents propose options; they don't decide.
2. Add a `DEC-NN` row to the [decision log](../../roadmap/README.md#decision-log), using the next free number,
   with the date and step.
3. Either add a section to the ADR whose topic fits, or create a new ADR from
   [the template](0000-template.md) using the next free four-digit number. Add it to the index above.
4. Record the alternatives that were actually offered and the reason given. When the owner chose without a
   reason, say so instead of inventing one.

## Changing a decision

Never edit or delete an accepted decision. Add a new DEC row that says `Supersedes DEC-NN`, record it in a new
or existing ADR, and set the old ADR section's status to *Superseded by …* with a link. Then update the
affected roadmap stage files.
