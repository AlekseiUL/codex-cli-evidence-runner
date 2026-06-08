"""Audit helpers for Walter runner receipt bundles."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PASS = "PASS"
OK = "OK"
RECEIPT_FILE = "receipt.json"


def _normalize_status(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().replace("-", "_").replace(" ", "_").upper()


def _mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _list_count(value: object) -> int:
    if isinstance(value, list):
        return len(value)
    return 0


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _command_objects(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _reject_failed_verification_commands(
    verification_map: Mapping[str, Any], reasons: list[str]
) -> None:
    if (
        "verification_commands_ok" in verification_map
        and verification_map.get("verification_commands_ok") is not True
    ):
        _append_reason(reasons, "verification_commands_ok_not_true")

    for field_name in ("commands", "verification_commands"):
        for command in _command_objects(verification_map.get(field_name)):
            if "exit_code" in command and command.get("exit_code") != 0:
                _append_reason(reasons, "verification_command_exit_code_non_zero")
            if "status" in command and _normalize_status(command.get("status")) not in {
                PASS,
                OK,
            }:
                _append_reason(reasons, "verification_command_status_not_pass_or_ok")
            if command.get("passed") is False:
                _append_reason(reasons, "verification_command_passed_false")
            if command.get("ok") is False:
                _append_reason(reasons, "verification_command_ok_false")


def _reason_audit(reasons: list[str]) -> dict:
    safe = not reasons
    return {
        "safe": safe,
        "clean": safe,
        "reject_reasons": reasons,
        "changed_files_count": 0,
        "outside_allowed_count": 0,
        "risks_count": 0,
        "status_pass": False,
        "secret_scan_pass": False,
        "outside_project_read_scan_pass": False,
        "runner_verified": False,
        "rollback_possible": False,
    }


def reject_reasons(receipt: object) -> list[str]:
    """Return deterministic reject reason codes for a Walter receipt."""
    receipt_map = _mapping(receipt)
    if receipt_map is None:
        return ["receipt_not_object"]

    reasons: list[str] = []

    if "status" not in receipt_map:
        reasons.append("missing_status")
    elif _normalize_status(receipt_map.get("status")) != PASS:
        reasons.append("status_not_pass")

    changes = receipt_map.get("changes")
    changes_map = _mapping(changes)
    if "changes" not in receipt_map:
        reasons.append("missing_changes")
    elif changes_map is None:
        reasons.append("changes_not_object")
    else:
        if "changed_files" not in changes_map:
            reasons.append("missing_changed_files")
        elif not isinstance(changes_map.get("changed_files"), list):
            reasons.append("changed_files_not_list")

        outside_allowed_paths = changes_map.get("outside_allowed_paths")
        if "outside_allowed_paths" not in changes_map:
            reasons.append("missing_outside_allowed_paths")
        elif not isinstance(outside_allowed_paths, list):
            reasons.append("outside_allowed_paths_not_list")
        elif outside_allowed_paths:
            reasons.append("outside_allowed_paths_present")

    verification = receipt_map.get("verification")
    verification_map = _mapping(verification)
    if "verification" not in receipt_map:
        reasons.append("missing_verification")
    elif verification_map is None:
        reasons.append("verification_not_object")
    else:
        if "secret_scan" not in verification_map:
            reasons.append("missing_secret_scan")
        elif _normalize_status(verification_map.get("secret_scan")) != PASS:
            reasons.append("secret_scan_not_pass")

        if "outside_project_read_scan" not in verification_map:
            reasons.append("missing_outside_project_read_scan")
        elif _normalize_status(verification_map.get("outside_project_read_scan")) != PASS:
            reasons.append("outside_project_read_scan_not_pass")

        if "runner_verified_not_codex_claim" not in verification_map:
            reasons.append("missing_runner_verification")
        elif verification_map.get("runner_verified_not_codex_claim") is not True:
            reasons.append("runner_verification_not_true")

        _reject_failed_verification_commands(verification_map, reasons)

    rollback = receipt_map.get("rollback")
    rollback_map = _mapping(rollback)
    if "rollback" not in receipt_map:
        reasons.append("missing_rollback")
    elif rollback_map is None:
        reasons.append("rollback_not_object")
    else:
        if "possible" not in rollback_map:
            reasons.append("missing_rollback_possible")
        elif rollback_map.get("possible") is not True:
            reasons.append("rollback_not_possible")

    if "risks" in receipt_map:
        risks = receipt_map.get("risks")
        if not isinstance(risks, list):
            reasons.append("risks_not_list")
        elif risks:
            reasons.append("risks_present")

    return reasons


def audit_receipt(receipt: object) -> dict:
    """Return a compact, deterministic audit summary for a Walter receipt."""
    reasons = reject_reasons(receipt)
    audit = _reason_audit(reasons)

    receipt_map = _mapping(receipt)
    if receipt_map is None:
        return audit

    changes_map = _mapping(receipt_map.get("changes"))
    verification_map = _mapping(receipt_map.get("verification"))
    rollback_map = _mapping(receipt_map.get("rollback"))

    if changes_map is not None:
        audit["changed_files_count"] = _list_count(changes_map.get("changed_files"))
        audit["outside_allowed_count"] = _list_count(
            changes_map.get("outside_allowed_paths")
        )

    if "risks" in receipt_map:
        audit["risks_count"] = _list_count(receipt_map.get("risks"))

    audit["status_pass"] = _normalize_status(receipt_map.get("status")) == PASS

    if verification_map is not None:
        audit["secret_scan_pass"] = (
            _normalize_status(verification_map.get("secret_scan")) == PASS
        )
        audit["outside_project_read_scan_pass"] = (
            _normalize_status(verification_map.get("outside_project_read_scan")) == PASS
        )
        audit["runner_verified"] = (
            verification_map.get("runner_verified_not_codex_claim") is True
        )

    if rollback_map is not None:
        audit["rollback_possible"] = rollback_map.get("possible") is True

    return audit


def is_safe_receipt(receipt: object) -> bool:
    """Return whether a receipt has no audit reject reasons."""
    return audit_receipt(receipt)["safe"]


def audit_run_directory(run_directory: str | Path) -> dict:
    """Read and audit ``receipt.json`` from a Walter run directory."""
    receipt_path = Path(run_directory) / RECEIPT_FILE
    if not receipt_path.exists():
        audit = _reason_audit(["receipt_missing"])
        audit["receipt_found"] = False
        return audit

    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        audit = _reason_audit(["receipt_json_invalid"])
        audit["receipt_found"] = True
        return audit

    audit = audit_receipt(receipt)
    audit["receipt_found"] = True
    return audit
