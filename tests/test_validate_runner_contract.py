#!/usr/bin/env python3
"""Focused fixtures for validate_runner_contract.py receipt checks."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_runner_contract.py"
TESTS = ROOT / "tests"


def base_receipt() -> dict:
    return {
        "status": "PASS",
        "task_id": "receipt-contract",
        "project_path": str(TESTS / "synthetic-project"),
        "started_at": "2026-06-08T00:00:00+00:00",
        "finished_at": "2026-06-08T00:01:00+00:00",
        "preflight": {"input_valid": True},
        "codex": {"exit_code": 0},
        "changes": {"changed_files": []},
        "verification": {
            "runner_verified_not_codex_claim": True,
            "outside_project_read_scan": "PASS",
            "outside_project_read_hits": [],
        },
        "rollback": {"possible": True},
        "report_path": str(TESTS / "synthetic-report.md"),
    }


class ValidateRunnerContractReceiptFixtures(unittest.TestCase):
    def run_validator(self, receipt: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="test-validator-", dir=str(TESTS)) as tmp:
            path = Path(tmp) / "receipt.json"
            path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATOR), "receipt", str(path)],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_accepts_valid_receipt_with_outside_read_pass_and_empty_hits(self) -> None:
        proc = self.run_validator(base_receipt())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("OK", proc.stdout)

    def test_rejects_missing_outside_project_read_scan(self) -> None:
        receipt = base_receipt()
        receipt["verification"].pop("outside_project_read_scan")
        proc = self.run_validator(receipt)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("verification.outside_project_read_scan: must be PASS", proc.stdout)

    def test_rejects_missing_outside_project_read_hits(self) -> None:
        receipt = base_receipt()
        receipt["verification"].pop("outside_project_read_hits")
        proc = self.run_validator(receipt)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("verification.outside_project_read_hits: must be empty array", proc.stdout)

    def test_rejects_outside_project_read_scan_not_pass(self) -> None:
        receipt = base_receipt()
        receipt["verification"]["outside_project_read_scan"] = "FAIL"
        proc = self.run_validator(receipt)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("verification.outside_project_read_scan: must be PASS", proc.stdout)

    def test_rejects_non_list_outside_project_read_hits(self) -> None:
        receipt = base_receipt()
        receipt["verification"]["outside_project_read_hits"] = "none"
        proc = self.run_validator(receipt)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("verification.outside_project_read_hits: must be empty array", proc.stdout)

    def test_rejects_non_empty_outside_project_read_hits(self) -> None:
        receipt = base_receipt()
        receipt["verification"]["outside_project_read_hits"] = ["/outside/project"]
        proc = self.run_validator(receipt)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("verification.outside_project_read_hits: must be empty array", proc.stdout)

    def test_accepts_failed_timeout_receipt_with_nonzero_codex_exit(self) -> None:
        receipt = base_receipt()
        receipt["status"] = "FAILED_TIMEOUT"
        receipt["codex"] = {"exit_code": 124, "timed_out": True}
        proc = self.run_validator(receipt)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_rejects_codex_timeout_with_pass_status(self) -> None:
        receipt = base_receipt()
        receipt["codex"] = {"exit_code": 124, "timed_out": True}
        proc = self.run_validator(receipt)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("status: codex timeout must be FAILED_TIMEOUT", proc.stdout)

    def test_rejects_timed_out_verification_command_with_zero_exit(self) -> None:
        receipt = base_receipt()
        receipt["verification"]["verification_results"] = [
            {"command": "sleep 30", "exit_code": 0, "timed_out": True}
        ]
        proc = self.run_validator(receipt)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("timed_out command cannot have exit_code 0", proc.stdout)


if __name__ == "__main__":
    unittest.main()
