"""How BECK shows results: for people in ``console``, and for machines in ``json``."""

from beck.models import Plan, PlannedUpload


def distinct_targets(plan: Plan) -> int:
    """How many targets the run set out to fill. One listed in several systems counts once."""
    return len({u.target for u in plan.uploads} | {e.target for e in plan.still_missing})


def extension_warning(upload: PlannedUpload) -> str:
    source = upload.source.relative.as_posix()
    return (
        f"{source} has a different extension from {upload.target}. The MD5 matches, but an "
        "emulator may not be able to read it."
    )
