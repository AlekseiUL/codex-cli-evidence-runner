"""Receipt summary helpers for Walter receipts."""


def summarize_receipt(receipt: dict) -> dict:
    """Return a compact summary for the actual nested Walter receipt shape."""
    status = receipt["status"]
    changes = receipt["changes"]
    verification = receipt["verification"]
    rollback = receipt["rollback"]

    changed_files_count = len(changes["changed_files"])
    outside_allowed_count = len(changes["outside_allowed_paths"])
    secret_scan = verification["secret_scan"]
    outside_project_read_scan = verification["outside_project_read_scan"]
    rollback_possible = rollback["possible"]
    runner_verified = verification["runner_verified_not_codex_claim"]

    clean = (
        status == "PASS"
        and outside_allowed_count == 0
        and secret_scan == "PASS"
        and outside_project_read_scan == "PASS"
        and rollback_possible is True
        and runner_verified is True
    )

    return {
        "status": status,
        "changed_files_count": changed_files_count,
        "outside_allowed_count": outside_allowed_count,
        "secret_scan": secret_scan,
        "outside_project_read_scan": outside_project_read_scan,
        "rollback_possible": rollback_possible,
        "runner_verified": runner_verified,
        "clean": clean,
    }
