from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from walter_workspace.receipt_status import (
    is_clean_pass,
    is_timeout_failure,
    normalize_status,
)


class ReceiptStatusTests(unittest.TestCase):
    def test_normalize_status(self) -> None:
        self.assertEqual(normalize_status(" pass "), "PASS")
        self.assertEqual(normalize_status("Pass_With_Risks"), "PASS_WITH_RISKS")

    def test_clean_pass_requires_pass_and_no_risks(self) -> None:
        self.assertTrue(is_clean_pass({"status": "PASS", "risks": []}))
        self.assertFalse(is_clean_pass({"status": "PASS_WITH_RISKS", "risks": []}))
        self.assertFalse(is_clean_pass({"status": "PASS", "risks": ["rollback missing"]}))

    def test_clean_pass_rejects_missing_or_bad_status(self) -> None:
        self.assertFalse(is_clean_pass({}))
        self.assertFalse(is_clean_pass({"status": "FAILED", "risks": []}))

    def test_timeout_failure_requires_failed_timeout_status(self) -> None:
        self.assertTrue(is_timeout_failure({"status": "FAILED_TIMEOUT"}))
        self.assertTrue(is_timeout_failure({"status": "failed-timeout"}))
        self.assertTrue(is_timeout_failure({"status": "failed timeout"}))
        self.assertFalse(is_timeout_failure({"status": "FAILED"}))


if __name__ == "__main__":
    unittest.main()
