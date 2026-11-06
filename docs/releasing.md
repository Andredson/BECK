# Releasing BECK

How versions and tags work. The owner tags and publishes, and an agent never does (DEC-43).

## Version numbers

BECK follows [Semantic Versioning](https://semver.org/):

| Change | Before 1.0 | From 1.0 |
|---|---|---|
| A fix | Patch: `0.5.0` → `0.5.1` | Patch |
| A new feature | Minor: `0.5.0` → `0.6.0` | Minor |
| A breaking change | Minor: `0.5.0` → `0.6.0` | Major |

A change is breaking if someone's use of BECK stops working: a command or flag that's removed or changes meaning, a different [exit code](cli.md#exit-codes), or a settings file that's no longer accepted. Its commit message has a `!`, which [the changelog](maintenance.md#regenerating-the-changelog) marks. If a pushed commit lacks one, add it to `cliff.toml`.

**The `--json` output has its own version.** `schema_version` changes only for [a breaking change to that output](json-output.md#the-compatibility-promise), which needs the owner's approval. That's a breaking change for BECK's version as well.

## Where the version lives

It's in `pyproject.toml`, and `uv.lock` holds a copy. Nothing else stores it: `beck --version` and `beck_version` in `--json` read it with `importlib.metadata`.

Never edit it by hand, because the lockfile would no longer match, and CI's `uv sync --locked` would fail. Use `uv version` (DEC-18), and commit both files:

```sh
uv version --bump patch      # 0.5.0 → 0.5.1
uv version --bump minor      # 0.5.0 → 0.6.0
uv version --bump major      # 0.5.0 → 1.0.0
uv version --short           # prints the version
```

Add `--dry-run` to see the result without changing anything.

## Release candidates

A release candidate is a rehearsal, and it's published to TestPyPI only (DEC-41). Its version follows PEP 440, as in `0.6.0rc1`:

```sh
uv version --bump minor --bump rc      # 0.5.0 → 0.6.0rc1
uv version --bump rc                   # 0.6.0rc1 → 0.6.0rc2
uv version --bump stable               # 0.6.0rc2 → 0.6.0
```

`--bump rc` alone only works on a version that's already a release candidate. For the first public version, whose number the owner chooses, give it exactly: `uv version 0.6.0rc1`.

## Tags

A tag is `v` and the exact version:

| Version | Tag |
|---|---|
| `0.6.0` | `v0.6.0` |
| `0.6.0rc1` | `v0.6.0rc1` |

The release workflow fails if the tag isn't the project's version, with this check (step 10.6):

```sh
test "$GITHUB_REF_NAME" = "v$(uv version --short)"
```

Never move a tag or reuse a version. PyPI won't accept the same version twice, even after a delete, so a mistake in a release gets a new version.
