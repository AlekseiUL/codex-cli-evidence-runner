"""Endurance protocol status helpers."""


def duration_band(minutes: int) -> str:
    """Return the endurance duration band for a run length."""
    if minutes < 5:
        return "short"
    if minutes < 30:
        return "medium"
    return "long"


def requires_background(minutes: int) -> bool:
    """Return whether the run length requires background execution."""
    return minutes >= 30


def cleanup_requires_approval(action: str) -> bool:
    """Return whether a cleanup action is destructive and needs approval."""
    return action in {
        "remove",
        "delete",
        "prune",
        "cleanup-worktrees --confirm",
    }
