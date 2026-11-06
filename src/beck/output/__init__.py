"""How BECK shows results: for people in ``console``, and for machines in ``json``."""

from beck.models import Plan, PlannedUpload, RunResult


def distinct_targets(plan: Plan) -> int:
    """How many targets the run set out to fill. One listed in several systems counts once."""
    return len({u.target for u in plan.uploads} | {e.target for e in plan.still_missing})


def upload_errors(result: RunResult) -> dict[str, str]:
    """What went wrong on the target, by target. A failed delete is about a local file instead,
    and that file can have the same name as a target.
    """
    return {e.item: e.message for e in result.errors if e.code != "delete_failed"}


def upload_status(upload: PlannedUpload, result: RunResult) -> str:
    """What happened to an upload. People and machines must be told the same, so both use this.

    These are the values of ``uploads[].status`` in the JSON output, a public contract.
    """
    if upload in result.kept:
        return "kept"
    if upload in result.completed:
        return "replaced" if upload in result.replaced else "uploaded"
    if upload.target.as_posix() in upload_errors(result):
        return "failed"
    return "planned" if result.dry_run else "skipped"


def extension_warning(upload: PlannedUpload) -> str:
    source = upload.source.relative.as_posix()
    return (
        f"{source} has a different extension from {upload.target}. The MD5 matches, but an "
        "emulator may not be able to read it."
    )
