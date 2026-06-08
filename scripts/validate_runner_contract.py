#!/usr/bin/env python3
"""Lightweight Walter runner contract validator.

No external dependencies. Validates the practical subset Walter needs before a
Codex-CLI run: required fields, allowed execution lane, booleans, arrays, and
non-empty acceptance checks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

INPUT_REQUIRED = [
    "task_id",
    "project_path",
    "goal",
    "execution_lane",
    "allowed_paths",
    "forbidden_paths",
    "side_effect_policy",
    "acceptance_checks",
    "artifact_bundle_required",
    "receipt_required",
    "rollback_required",
    "report_path",
]

RECEIPT_REQUIRED = [
    "status",
    "task_id",
    "project_path",
    "started_at",
    "finished_at",
    "preflight",
    "codex",
    "changes",
    "verification",
    "rollback",
    "report_path",
]

VALID_STATUS = {
    "PASS",
    "PASS_WITH_RISKS",
    "FAIL_VERIFICATION",
    "NEEDS_APPROVAL",
    "OUT_OF_SCOPE_CHANGE",
    "BLOCKED",
    "FAILED",
    "FAILED_TIMEOUT",
    "REJECTED",
}


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"INVALID_JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"INVALID_ROOT: {path}: root must be object")
    return data


def require(data: dict[str, Any], fields: list[str], kind: str) -> list[str]:
    errors: list[str] = []
    for field in fields:
        if field not in data:
            errors.append(f"{kind}: missing {field}")
    return errors


def nonempty_string(data: dict[str, Any], field: str, errors: list[str]) -> None:
    if field in data and (not isinstance(data[field], str) or not data[field].strip()):
        errors.append(f"{field}: must be non-empty string")


def string_array(data: dict[str, Any], field: str, errors: list[str], min_items: int = 0) -> None:
    if field not in data:
        return
    value = data[field]
    if not isinstance(value, list):
        errors.append(f"{field}: must be array")
        return
    if len(value) < min_items:
        errors.append(f"{field}: must have at least {min_items} item(s)")
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field}[{idx}]: must be non-empty string")


def validate_input(path: Path) -> int:
    data = load_json(path)
    errors = require(data, INPUT_REQUIRED, "input")
    for field in ["task_id", "project_path", "goal", "side_effect_policy", "report_path"]:
        nonempty_string(data, field, errors)
    if data.get("execution_lane") != "Codex-CLI":
        errors.append("execution_lane: must be Codex-CLI for runner input")
    string_array(data, "allowed_paths", errors, min_items=1)
    string_array(data, "forbidden_paths", errors)
    string_array(data, "acceptance_checks", errors, min_items=1)
    for field in ["artifact_bundle_required", "receipt_required", "rollback_required"]:
        if field in data and not isinstance(data[field], bool):
            errors.append(f"{field}: must be boolean")
    return finish(path, errors)


def validate_receipt(path: Path) -> int:
    data = load_json(path)
    errors = require(data, RECEIPT_REQUIRED, "receipt")
    if data.get("status") not in VALID_STATUS:
        errors.append("status: invalid verdict state")
    for field in ["task_id", "project_path", "started_at", "finished_at", "report_path"]:
        nonempty_string(data, field, errors)
    for obj in ["preflight", "codex", "changes", "verification", "rollback"]:
        if obj in data and not isinstance(data[obj], dict):
            errors.append(f"{obj}: must be object")
    verification = data.get("verification")
    if isinstance(verification, dict) and verification.get("runner_verified_not_codex_claim") is not True:
        errors.append("verification.runner_verified_not_codex_claim: must be true")
    if isinstance(verification, dict):
        if verification.get("outside_project_read_scan") != "PASS":
            errors.append("verification.outside_project_read_scan: must be PASS")
        hits = verification.get("outside_project_read_hits")
        if not isinstance(hits, list):
            errors.append("verification.outside_project_read_hits: must be empty array")
        elif hits:
            errors.append("verification.outside_project_read_hits: must be empty array")
        commands = verification.get("verification_results", verification.get("commands"))
        if commands is not None:
            if not isinstance(commands, list):
                errors.append("verification.commands: must be array when present")
            else:
                for idx, command in enumerate(commands):
                    if not isinstance(command, dict):
                        errors.append(f"verification.commands[{idx}]: must be object")
                        continue
                    if command.get("timed_out") is True and command.get("exit_code") == 0:
                        errors.append(f"verification.commands[{idx}]: timed_out command cannot have exit_code 0")
    codex = data.get("codex")
    if isinstance(codex, dict) and codex.get("timed_out") is True:
        if codex.get("exit_code") == 0:
            errors.append("codex: timed_out cannot have exit_code 0")
        if data.get("status") != "FAILED_TIMEOUT":
            errors.append("status: codex timeout must be FAILED_TIMEOUT")
    return finish(path, errors)


def finish(path: Path, errors: list[str]) -> int:
    if errors:
        print(f"FAIL {path}")
        for err in errors:
            print(f"- {err}")
        return 1
    print(f"OK {path}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in {"input", "receipt"}:
        print("Usage: validate_runner_contract.py input|receipt PATH", file=sys.stderr)
        return 2
    path = Path(argv[2]).expanduser().resolve()
    if argv[1] == "input":
        return validate_input(path)
    return validate_receipt(path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
