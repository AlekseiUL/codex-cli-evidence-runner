from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from walter_workspace.receipt_summary import summarize_receipt


def make_receipt() -> dict:
    return {
        "status": "PASS",
        "changes": {
            "changed_files": [
                "src/walter_workspace/receipt_summary.py",
                "tests/test_receipt_summary.py",
            ],
            "outside_allowed_paths": [],
        },
        "verification": {
            "secret_scan": "PASS",
            "outside_project_read_scan": "PASS",
            "runner_verified_not_codex_claim": True,
        },
        "rollback": {
            "possible": True,
        },
        "risks": ["legacy flat field must not affect nested summary"],
    }


class ReceiptSummaryTests(unittest.TestCase):
    def test_summarize_receipt_parses_nested_walter_shape(self) -> None:
        self.assertEqual(
            summarize_receipt(make_receipt()),
            {
                "status": "PASS",
                "changed_files_count": 2,
                "outside_allowed_count": 0,
                "secret_scan": "PASS",
                "outside_project_read_scan": "PASS",
                "rollback_possible": True,
                "runner_verified": True,
                "clean": True,
            },
        )

    def test_clean_false_when_outside_allowed_paths_exist(self) -> None:
        receipt = make_receipt()
        receipt["changes"]["outside_allowed_paths"] = ["/tmp/outside-project.txt"]

        summary = summarize_receipt(receipt)

        self.assertEqual(summary["outside_allowed_count"], 1)
        self.assertFalse(summary["clean"])

    def test_clean_requires_all_verification_and_rollback_conditions(self) -> None:
        cases = [
            ("status", "FAIL"),
            ("verification.secret_scan", "FAIL"),
            ("verification.outside_project_read_scan", "FAIL"),
            ("verification.runner_verified_not_codex_claim", False),
            ("rollback.possible", False),
        ]

        for path, value in cases:
            with self.subTest(path=path):
                receipt = make_receipt()
                section = receipt
                keys = path.split(".")
                for key in keys[:-1]:
                    section = section[key]
                section[keys[-1]] = value

                self.assertFalse(summarize_receipt(receipt)["clean"])


if __name__ == "__main__":
    unittest.main()
