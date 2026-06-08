from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from walter_workspace.evidence_report import render_markdown_report
from walter_workspace.run_history import (
    scan_run_history,
    summarize_run_audits,
    summarize_run_history,
)


def make_receipt() -> dict:
    return {
        "status": "PASS",
        "changes": {
            "changed_files": ["src/walter_workspace/run_history.py"],
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
    }


def write_receipt(run_path: Path, receipt: dict) -> None:
    run_path.mkdir()
    (run_path / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


class RunHistoryTests(unittest.TestCase):
    def test_scan_and_summarize_multiple_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp)
            write_receipt(history_path / "001-clean", make_receipt())

            unsafe_receipt = make_receipt()
            unsafe_receipt["changes"]["outside_allowed_paths"] = ["/outside.txt"]
            write_receipt(history_path / "002-unsafe", unsafe_receipt)

            (history_path / "003-missing").mkdir()

            runs = scan_run_history(history_path)
            summary = summarize_run_audits(runs)

        self.assertEqual([run["run_index"] for run in runs], [0, 1, 2])
        self.assertEqual(summary["total_runs"], 3)
        self.assertEqual(summary["safe_runs"], 1)
        self.assertEqual(summary["clean_runs"], 1)
        self.assertEqual(summary["unsafe_runs"], 2)
        self.assertEqual(summary["missing_receipts"], 1)
        self.assertFalse(summary["all_safe"])
        self.assertFalse(summary["all_clean"])
        self.assertEqual(
            summary["reject_reason_counts"],
            {
                "outside_allowed_paths_present": 1,
                "receipt_missing": 1,
            },
        )

    def test_public_alias_matches_summary_function(self) -> None:
        runs = [
            {
                "safe": True,
                "clean": True,
                "reject_reasons": [],
            }
        ]

        self.assertEqual(summarize_run_history(runs), summarize_run_audits(runs))

    def test_markdown_rendering_from_aggregate_summary(self) -> None:
        summary = {
            "total_runs": 2,
            "safe_runs": 1,
            "clean_runs": 1,
            "unsafe_runs": 1,
            "missing_receipts": 0,
            "all_safe": False,
            "all_clean": False,
            "reject_reason_counts": {
                "risks_present": 1,
            },
        }

        report = render_markdown_report(summary)

        self.assertIn("# Walter Evidence Report", report)
        self.assertIn("- Total runs: 2", report)
        self.assertIn("- Safe runs: 1", report)
        self.assertIn("- risks_present: 1", report)

    def test_markdown_rendering_without_rejects(self) -> None:
        report = render_markdown_report(
            {
                "total_runs": 1,
                "safe_runs": 1,
                "clean_runs": 1,
                "unsafe_runs": 0,
                "missing_receipts": 0,
                "all_safe": True,
                "all_clean": True,
                "reject_reason_counts": {},
            }
        )

        self.assertIn("- All safe: yes", report)
        self.assertIn("- None", report)

    def test_private_marker_values_are_not_echoed_in_summary_or_report(self) -> None:
        marker = "PRIVATE_MARKER_VALUE"

        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp)
            private_run_path = history_path / marker
            receipt = make_receipt()
            receipt["risks"] = [marker]
            write_receipt(private_run_path, receipt)

            runs = scan_run_history(history_path)
            summary = summarize_run_audits(runs)
            report = render_markdown_report(summary)

        self.assertNotIn(marker, repr(runs))
        self.assertNotIn(marker, repr(summary))
        self.assertNotIn(marker, report)


if __name__ == "__main__":
    unittest.main()
