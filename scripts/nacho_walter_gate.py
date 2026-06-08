#!/usr/bin/env python3
"""Nacho gate for Walter/Codex run bundles.

Independent stdlib-only verifier for the evidence bundle created by
walter_runner.py. This is stricter than the shape validator: it rejects runs
where Codex says "done" but runner evidence is missing or unsafe.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

WALTER_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = WALTER_ROOT / "scripts" / "validate_runner_contract.py"
REQUIRED_BUNDLE = [
    "input.json",
    "policy.yaml",
    "prompt.md",
    "codex.log",
    "diff.patch",
    "verify.log",
    "receipt.json",
    "report.md",
]
PASS_STATUSES = {"PASS", "PASS_WITH_RISKS"}


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid json {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid json {path.name}: root must be object")
    return data


def text_of(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def run_validator(kind: str, path: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), kind, str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def gate(run_dir: Path, *, allow_risk: bool = False, require_pass: bool = True) -> tuple[int, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    run_dir = run_dir.expanduser().resolve()

    if not run_dir.exists() or not run_dir.is_dir():
        return 2, [f"run dir missing: {run_dir}"], warnings

    for name in REQUIRED_BUNDLE:
        path = run_dir / name
        if not path.exists():
            errors.append(f"missing {name}")
        elif path.stat().st_size == 0:
            errors.append(f"empty {name}")

    input_path = run_dir / "input.json"
    receipt_path = run_dir / "receipt.json"
    if input_path.exists():
        code, out = run_validator("input", input_path)
        if code != 0:
            errors.append(f"input contract failed: {out}")
    if receipt_path.exists():
        code, out = run_validator("receipt", receipt_path)
        if code != 0:
            errors.append(f"receipt contract failed: {out}")

    if not receipt_path.exists():
        return 1, errors, warnings

    try:
        receipt = load_json(receipt_path)
    except ValueError as exc:
        errors.append(str(exc))
        return 1, errors, warnings

    status = receipt.get("status")
    if require_pass and status not in PASS_STATUSES:
        errors.append(f"status not pass: {status}")
    if status == "PASS_WITH_RISKS":
        if allow_risk:
            warnings.append("status is PASS_WITH_RISKS")
        else:
            errors.append("status PASS_WITH_RISKS requires --allow-risk")

    changes = receipt.get("changes", {}) if isinstance(receipt.get("changes"), dict) else {}
    verification = receipt.get("verification", {}) if isinstance(receipt.get("verification"), dict) else {}
    rollback = receipt.get("rollback", {}) if isinstance(receipt.get("rollback"), dict) else {}
    codex = receipt.get("codex", {}) if isinstance(receipt.get("codex"), dict) else {}

    if verification.get("runner_verified_not_codex_claim") is not True:
        errors.append("runner verification flag is not true")
    if verification.get("verification_commands_ok") is not True:
        errors.append("verification commands not ok")
    if verification.get("secret_scan") != "PASS":
        errors.append(f"secret scan not pass: {verification.get('secret_scan')}")
    if verification.get("secret_scan_hits"):
        errors.append("secret scan hits present")
    if verification.get("outside_project_read_scan") != "PASS":
        errors.append(f"outside project read scan not pass: {verification.get('outside_project_read_scan')}")
    if verification.get("outside_project_read_hits"):
        errors.append(f"outside project read hits present: {verification.get('outside_project_read_hits')}")

    if changes.get("outside_allowed_paths"):
        errors.append(f"outside allowed paths: {changes.get('outside_allowed_paths')}")
    if changes.get("forbidden_changed_paths"):
        errors.append(f"forbidden changed paths: {changes.get('forbidden_changed_paths')}")
    if changes.get("diff_available") is not True and status == "PASS":
        errors.append("PASS requires diff_available=true")

    verify_log = text_of(run_dir / "verify.log").strip()
    if not verify_log:
        errors.append("verify.log empty")
    if "NO_VERIFICATION_COMMANDS" in verify_log:
        errors.append("verify.log says NO_VERIFICATION_COMMANDS")

    codex_log = text_of(run_dir / "codex.log").strip()
    if not codex_log:
        errors.append("codex.log empty")
    if codex.get("exit_code") not in (0, None):
        errors.append(f"codex exit non-zero: {codex.get('exit_code')}")

    if not rollback.get("method") or not rollback.get("instructions"):
        errors.append("rollback method/instructions missing")
    if rollback.get("possible") is not True:
        if allow_risk:
            warnings.append("rollback marked not possible")
        else:
            errors.append("rollback not possible; use --allow-risk only for scoped non-git runs")

    report_path = receipt.get("report_path")
    if isinstance(report_path, str) and report_path.strip():
        if not Path(report_path).expanduser().exists():
            errors.append(f"report_path missing on disk: {report_path}")
    else:
        errors.append("report_path missing in receipt")

    return (1 if errors else 0), errors, warnings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Nacho gate for Walter run bundles")
    parser.add_argument("run_dir")
    parser.add_argument("--allow-risk", action="store_true", help="allow PASS_WITH_RISKS / non-git scoped rollback warnings")
    parser.add_argument("--no-require-pass", action="store_true", help="only inspect bundle; do not require PASS/PASS_WITH_RISKS status")
    args = parser.parse_args(argv[1:])

    code, errors, warnings = gate(
        Path(args.run_dir),
        allow_risk=args.allow_risk,
        require_pass=not args.no_require_pass,
    )
    if code == 0:
        print("NACHO_GATE PASS")
    else:
        print("NACHO_GATE FAIL")
    for err in errors:
        print(f"- {err}")
    for warn in warnings:
        print(f"warning: {warn}")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
