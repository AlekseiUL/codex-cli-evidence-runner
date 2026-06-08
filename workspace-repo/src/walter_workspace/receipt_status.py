"""Receipt status helpers."""


def normalize_status(value: object) -> str:
    """Return a normalized receipt status string."""
    if not isinstance(value, str):
        return ""

    return value.strip().replace("-", "_").replace(" ", "_").upper()


def is_clean_pass(receipt: dict) -> bool:
    """Return whether a receipt is a PASS with no risks."""
    return (
        normalize_status(receipt.get("status")) == "PASS"
        and receipt.get("risks", []) == []
    )


def is_timeout_failure(receipt: dict) -> bool:
    """Return whether a receipt failed because it timed out."""
    return normalize_status(receipt.get("status")) == "FAILED_TIMEOUT"
