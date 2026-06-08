#!/usr/bin/env python3
"""Hostile fixtures for nacho_walter_gate.py.

Stdlib unittest suite. It builds synthetic Walter bundles and verifies that the
Nacho gate accepts only independently verified safe receipts.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "nacho_walter_gate.py"


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_bundle(run_dir: Path, **overrides) -> Path:
    project = run_dir / "project"
    project.mkdir(parents=True)
    report = run_dir / "report.md"
    input_data = {
        "task_id": run_dir.name,
        "originating_agent": "mike",
        "return_to": "mike",
        "scenario_class": "implementation",
        "project_path": str(project),
        "goal": "Synthetic safe runner fixture.",
        "execution_lane": "Codex-CLI",
        "allowed_paths": ["src/**", "tests/**"],
        "forbidden_paths": [".env", "secrets/**"],
        "privacy_level": "public-team",
        "side_effect_policy": "local-only/no-push/no-deploy/no-public-send",
        "acceptance_checks": ["verification command passes", "no files outside allowed paths"],
        "verification_commands": ["python -c 'print(123)'"],
        "artifact_bundle_required": True,
        "receipt_required": True,
        "rollback_required": True,
        "report_path": str(report),
    }
    receipt = {
        "status": "PASS",
        "task_id": run_dir.name,
        "project_path": str(project),
        "execution_path": str(project),
        "started_at": "2026-06-08T00:00:00+00:00",
        "finished_at": "2026-06-08T00:01:00+00:00",
        "preflight": {"input_valid": True, "project_exists": True, "git_repo": True},
        "codex": {"command": "codex exec < prompt.md", "exit_code": 0, "log_path": str(run_dir / "codex.log")},
        "changes": {
            "change_detection": "git_status",
            "diff_available": True,
            "diff_path": str(run_dir / "diff.patch"),
            "changed_files": ["src/demo.py"],
            "outside_allowed_paths": [],
            "forbidden_changed_paths": [],
        },
        "verification": {
            "runner_verified_not_codex_claim": True,
            "verification_commands_ok": True,
            "verification_results": [{"command": "python -c 'print(123)'", "exit_code": 0}],
            "commands": [{"command": "python -c 'print(123)'", "exit_code": 0}],
            "secret_scan": "PASS",
            "secret_scan_hits": [],
            "outside_project_read_scan": "PASS",
            "outside_project_read_hits": [],
        },
        "rollback": {
            "possible": True,
            "method": "git checkout/reset",
            "command": "git checkout -- . && git clean -fd",
            "instructions": "Review diff.patch first.",
        },
        "report_path": str(report),
    }
    for key, value in overrides.items():
        if key == "receipt":
            receipt.update(value)
        elif key == "input":
            input_data.update(value)
        elif key == "changes":
            receipt["changes"].update(value)
        elif key == "verification":
            receipt["verification"].update(value)
        elif key == "rollback":
            receipt["rollback"].update(value)
        elif key == "codex":
            receipt["codex"].update(value)
        else:
            raise AssertionError(f"unknown override {key}")

    write_json(run_dir / "input.json", input_data)
    (run_dir / "policy.yaml").write_text("side_effect_policy: local-only\n", encoding="utf-8")
    (run_dir / "prompt.md").write_text("Do the bounded task.\n", encoding="utf-8")
    (run_dir / "codex.log").write_text("Codex transcript placeholder.\n", encoding="utf-8")
    (run_dir / "diff.patch").write_text("diff --git a/src/demo.py b/src/demo.py\n", encoding="utf-8")
    (run_dir / "verify.log").write_text("$ python -c 'print(123)'\n123\n", encoding="utf-8")
    report.write_text("# Report\nStatus: PASS\n", encoding="utf-8")
    write_json(run_dir / "receipt.json", receipt)
    return run_dir


class NachoGateFixtures(unittest.TestCase):
    def run_gate(self, run_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(GATE), str(run_dir), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_accepts_safe_pass_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp) / "safe-pass")
            proc = self.run_gate(bundle)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("NACHO_GATE PASS", proc.stdout)

    def test_rejects_codex_done_without_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp) / "no-verification", verification={"verification_commands_ok": False})
            (bundle / "verify.log").write_text("NO_VERIFICATION_COMMANDS\n", encoding="utf-8")
            proc = self.run_gate(bundle)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("verification commands not ok", proc.stdout)
            self.assertIn("NO_VERIFICATION_COMMANDS", proc.stdout)

    def test_rejects_missing_outside_read_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp) / "missing-read-scan")
            receipt_path = bundle / "receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["verification"].pop("outside_project_read_scan", None)
            receipt["verification"].pop("outside_project_read_hits", None)
            write_json(receipt_path, receipt)
            proc = self.run_gate(bundle)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("outside project read scan not pass", proc.stdout)

    def test_rejects_outside_allowed_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp) / "outside", changes={"outside_allowed_paths": ["README.md"]})
            proc = self.run_gate(bundle)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("outside allowed paths", proc.stdout)

    def test_rejects_forbidden_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp) / "forbidden", changes={"forbidden_changed_paths": [".env"]})
            proc = self.run_gate(bundle)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("forbidden changed paths", proc.stdout)

    def test_rejects_secret_scan_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(
                Path(tmp) / "secret",
                verification={"secret_scan": "FAIL", "secret_scan_hits": ["src/config.py"]},
            )
            proc = self.run_gate(bundle)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("secret scan not pass", proc.stdout)

    def test_pass_with_risks_needs_explicit_allow_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(
                Path(tmp) / "risk",
                receipt={"status": "PASS_WITH_RISKS"},
                rollback={"possible": False},
            )
            blocked = self.run_gate(bundle)
            self.assertNotEqual(blocked.returncode, 0)
            allowed = self.run_gate(bundle, "--allow-risk")
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
            self.assertIn("warning: status is PASS_WITH_RISKS", allowed.stdout)


if __name__ == "__main__":
    unittest.main()
