from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from walter_workspace.receipt_audit import (
    audit_receipt,
    audit_run_directory,
    is_safe_receipt,
    reject_reasons,
)


def make_receipt() -> dict:
    return {
        "status": "PASS",
        "changes": {
            "changed_files": [
                "src/walter_workspace/receipt_audit.py",
                "tests/test_receipt_audit.py",
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
        "risks": [],
    }


def make_command_receipt() -> dict:
    receipt = make_receipt()
    receipt.pop("risks")
    receipt["verification"]["verification_commands_ok"] = True
    receipt["verification"]["commands"] = [
        {
            "name": "unit_tests",
            "exit_code": 0,
            "status": "PASS",
            "passed": True,
            "ok": True,
        }
    ]
    return receipt


class ReceiptAuditTests(unittest.TestCase):
    def test_clean_receipt_passes(self) -> None:
        audit = audit_receipt(make_receipt())

        self.assertTrue(audit["safe"])
        self.assertTrue(audit["clean"])
        self.assertTrue(is_safe_receipt(make_receipt()))
        self.assertEqual(audit["reject_reasons"], [])
        self.assertEqual(audit["changed_files_count"], 2)
        self.assertEqual(audit["outside_allowed_count"], 0)
        self.assertEqual(audit["risks_count"], 0)

    def test_minimal_real_walter_shape_without_risks_passes(self) -> None:
        receipt = make_receipt()
        del receipt["risks"]

        audit = audit_receipt(receipt)

        self.assertTrue(audit["safe"])
        self.assertTrue(audit["clean"])
        self.assertEqual(audit["risks_count"], 0)
        self.assertEqual(reject_reasons(receipt), [])

    def test_clean_real_shape_with_verification_commands_passes(self) -> None:
        receipt = make_command_receipt()

        audit = audit_receipt(receipt)

        self.assertTrue(audit["safe"])
        self.assertTrue(audit["clean"])
        self.assertEqual(audit["reject_reasons"], [])

    def test_clean_command_backed_receipt_can_omit_verification_commands_ok(
        self,
    ) -> None:
        receipt = make_command_receipt()
        del receipt["verification"]["verification_commands_ok"]

        audit = audit_receipt(receipt)

        self.assertTrue(audit["safe"])
        self.assertEqual(audit["reject_reasons"], [])

    def test_rejects_verification_commands_ok_false(self) -> None:
        receipt = make_command_receipt()
        receipt["verification"]["verification_commands_ok"] = False

        audit = audit_receipt(receipt)

        self.assertIn(
            "verification_commands_ok_not_true",
            audit["reject_reasons"],
        )
        self.assertFalse(audit["safe"])

    def test_rejects_non_zero_exit_code_in_real_commands_field(self) -> None:
        receipt = make_command_receipt()
        receipt["verification"]["commands"][0]["exit_code"] = 1

        audit = audit_receipt(receipt)

        self.assertIn(
            "verification_command_exit_code_non_zero",
            audit["reject_reasons"],
        )
        self.assertFalse(audit["safe"])

    def test_rejects_failed_command_status(self) -> None:
        receipt = make_command_receipt()
        receipt["verification"]["commands"][0]["status"] = "FAIL"

        audit = audit_receipt(receipt)

        self.assertIn(
            "verification_command_status_not_pass_or_ok",
            audit["reject_reasons"],
        )
        self.assertFalse(audit["safe"])

    def test_rejects_command_passed_false(self) -> None:
        receipt = make_command_receipt()
        receipt["verification"]["commands"][0]["passed"] = False

        audit = audit_receipt(receipt)

        self.assertIn(
            "verification_command_passed_false",
            audit["reject_reasons"],
        )
        self.assertFalse(audit["safe"])

    def test_rejects_command_ok_false(self) -> None:
        receipt = make_command_receipt()
        receipt["verification"]["commands"][0]["ok"] = False

        audit = audit_receipt(receipt)

        self.assertIn(
            "verification_command_ok_false",
            audit["reject_reasons"],
        )
        self.assertFalse(audit["safe"])

    def test_rejects_failed_alias_verification_commands(self) -> None:
        receipt = make_receipt()
        receipt["verification"]["verification_commands"] = [
            {
                "name": "smoke",
                "exit_code": 1,
                "status": "OK",
                "passed": True,
                "ok": True,
            }
        ]

        audit = audit_receipt(receipt)

        self.assertIn(
            "verification_command_exit_code_non_zero",
            audit["reject_reasons"],
        )
        self.assertFalse(audit["safe"])

    def test_every_unsafe_reject_reason(self) -> None:
        cases = [
            ("missing_status", lambda receipt: receipt.pop("status")),
            ("status_not_pass", lambda receipt: receipt.update({"status": "FAIL"})),
            ("missing_changes", lambda receipt: receipt.pop("changes")),
            ("changes_not_object", lambda receipt: receipt.update({"changes": []})),
            (
                "missing_changed_files",
                lambda receipt: receipt["changes"].pop("changed_files"),
            ),
            (
                "changed_files_not_list",
                lambda receipt: receipt["changes"].update({"changed_files": "one"}),
            ),
            (
                "missing_outside_allowed_paths",
                lambda receipt: receipt["changes"].pop("outside_allowed_paths"),
            ),
            (
                "outside_allowed_paths_not_list",
                lambda receipt: receipt["changes"].update(
                    {"outside_allowed_paths": "none"}
                ),
            ),
            (
                "outside_allowed_paths_present",
                lambda receipt: receipt["changes"].update(
                    {"outside_allowed_paths": ["/outside.txt"]}
                ),
            ),
            ("missing_verification", lambda receipt: receipt.pop("verification")),
            (
                "verification_not_object",
                lambda receipt: receipt.update({"verification": []}),
            ),
            (
                "missing_secret_scan",
                lambda receipt: receipt["verification"].pop("secret_scan"),
            ),
            (
                "secret_scan_not_pass",
                lambda receipt: receipt["verification"].update({"secret_scan": "FAIL"}),
            ),
            (
                "missing_outside_project_read_scan",
                lambda receipt: receipt["verification"].pop(
                    "outside_project_read_scan"
                ),
            ),
            (
                "outside_project_read_scan_not_pass",
                lambda receipt: receipt["verification"].update(
                    {"outside_project_read_scan": "FAIL"}
                ),
            ),
            (
                "missing_runner_verification",
                lambda receipt: receipt["verification"].pop(
                    "runner_verified_not_codex_claim"
                ),
            ),
            (
                "runner_verification_not_true",
                lambda receipt: receipt["verification"].update(
                    {"runner_verified_not_codex_claim": False}
                ),
            ),
            ("missing_rollback", lambda receipt: receipt.pop("rollback")),
            ("rollback_not_object", lambda receipt: receipt.update({"rollback": []})),
            (
                "missing_rollback_possible",
                lambda receipt: receipt["rollback"].pop("possible"),
            ),
            (
                "rollback_not_possible",
                lambda receipt: receipt["rollback"].update({"possible": False}),
            ),
            ("risks_not_list", lambda receipt: receipt.update({"risks": "none"})),
            ("risks_present", lambda receipt: receipt.update({"risks": ["manual"]})),
        ]

        for expected_reason, mutate in cases:
            with self.subTest(expected_reason=expected_reason):
                receipt = make_receipt()
                mutate(receipt)

                audit = audit_receipt(receipt)

                self.assertIn(expected_reason, audit["reject_reasons"])
                self.assertFalse(audit["safe"])
                self.assertFalse(audit["clean"])
                self.assertFalse(is_safe_receipt(receipt))

    def test_rejects_non_object_receipt(self) -> None:
        audit = audit_receipt([])

        self.assertEqual(audit["reject_reasons"], ["receipt_not_object"])
        self.assertFalse(audit["safe"])
        self.assertFalse(audit["clean"])

    def test_missing_receipt_in_run_directory_is_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = audit_run_directory(Path(tmp))

        self.assertFalse(audit["receipt_found"])
        self.assertEqual(audit["reject_reasons"], ["receipt_missing"])
        self.assertFalse(audit["safe"])

    def test_invalid_receipt_json_is_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "receipt.json"
            receipt_path.write_text("{", encoding="utf-8")

            audit = audit_run_directory(Path(tmp))

        self.assertTrue(audit["receipt_found"])
        self.assertEqual(audit["reject_reasons"], ["receipt_json_invalid"])
        self.assertFalse(audit["safe"])

    def test_run_directory_audits_synthetic_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "receipt.json"
            receipt_path.write_text(json.dumps(make_receipt()), encoding="utf-8")

            audit = audit_run_directory(Path(tmp))

        self.assertTrue(audit["receipt_found"])
        self.assertTrue(audit["safe"])
        self.assertTrue(audit["clean"])

    def test_private_marker_values_are_not_echoed(self) -> None:
        marker = "PRIVATE_MARKER_VALUE"
        receipt = make_receipt()
        receipt["risks"] = [marker]

        audit = audit_receipt(receipt)

        self.assertIn("risks_present", audit["reject_reasons"])
        self.assertEqual(audit["risks_count"], 1)
        self.assertNotIn(marker, repr(audit))


if __name__ == "__main__":
    unittest.main()
