"""Run history aggregation for Walter receipt audits."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from walter_workspace.receipt_audit import audit_run_directory


def scan_run_history(history_directory: str | Path) -> list[dict]:
    """Audit immediate child run directories in deterministic name order."""
    history_path = Path(history_directory)
    if not history_path.is_dir():
        return []

    runs: list[dict] = []
    for run_path in sorted(
        (path for path in history_path.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ):
        audit = audit_run_directory(run_path)
        audit["run_index"] = len(runs)
        runs.append(audit)

    return runs


def summarize_run_audits(runs: list[dict]) -> dict:
    """Return aggregate counts for audited Walter runs."""
    total_runs = len(runs)
    safe_runs = sum(1 for run in runs if run.get("safe") is True)
    clean_runs = sum(1 for run in runs if run.get("clean") is True)
    reason_counts: Counter[str] = Counter()

    for run in runs:
        for reason in run.get("reject_reasons", []):
            reason_counts[reason] += 1

    missing_receipts = reason_counts.get("receipt_missing", 0)
    unsafe_runs = total_runs - safe_runs

    return {
        "total_runs": total_runs,
        "safe_runs": safe_runs,
        "unsafe_runs": unsafe_runs,
        "clean_runs": clean_runs,
        "missing_receipts": missing_receipts,
        "all_safe": total_runs > 0 and unsafe_runs == 0,
        "all_clean": total_runs > 0 and clean_runs == total_runs,
        "reject_reason_counts": dict(sorted(reason_counts.items())),
    }


def summarize_run_history(runs: list[dict]) -> dict:
    """Public alias for summarizing audited Walter runs."""
    return summarize_run_audits(runs)
