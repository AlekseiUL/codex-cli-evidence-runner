from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE = ROOT / "scripts" / "walter_safe.py"


def load_safe_module():
    spec = importlib.util.spec_from_file_location("walter_safe_under_test", SAFE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SAFE), *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )


def make_git_repo(path: Path) -> None:
    (path / "src").mkdir(parents=True)
    (path / "tests").mkdir(parents=True)
    (path / "src" / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "walter-safe-test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Walter Safe Test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True, capture_output=True, text=True)


class WalterSafeCliTests(unittest.TestCase):
    def test_dry_run_prints_runner_command_with_safe_defaults(self) -> None:
        proc = run([
            "run-safe",
            "--goal", "Do nothing.",
            "--name", "dry-test",
            "--dry-run",
            "--print-command",
        ])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("RUNNER_CMD", proc.stdout)
        self.assertIn("walter_runner.py", proc.stdout)
        self.assertIn("--worktree", proc.stdout)
        self.assertIn("--allowed-path 'src/**'", proc.stdout)
        self.assertIn("--forbidden-path .env", proc.stdout)
        self.assertIn("--forbidden-path 'secrets/**'", proc.stdout)
        self.assertIn("--verification-timeout 600", proc.stdout)

    def test_calculated_runner_timeout_includes_verification_budget(self) -> None:
        module = load_safe_module()
        parser = module.build_parser()
        args = parser.parse_args([
            "run-safe",
            "--goal", "Do nothing.",
            "--timeout", "10",
            "--verification-timeout", "20",
            "--verification-command", "true",
            "--verification-command", "python3 -c 'print(1)'",
        ])
        self.assertEqual(module.calculated_runner_timeout(args), 10 + 20 * 2 + 300)

    def test_run_safe_skip_codex_executes_validation_gate_summary(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as tmp:
            root = Path(tmp)
            project = root / "project"
            run_dir = root / "run"
            project.mkdir()
            make_git_repo(project)
            proc = run([
                "run-safe",
                "--goal", "No-op runner mechanics test.",
                "--project-path", str(project),
                "--run-dir", str(run_dir),
                "--verification-command", "true",
                "--acceptance-check", "true command passes",
                "--skip-codex",
            ])
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("RECEIPT_CONTRACT", proc.stdout)
            self.assertIn("NACHO_GATE PASS", proc.stdout)
            self.assertIn("WALTER_SAFE PASS", proc.stdout)
            self.assertTrue((run_dir / "receipt.json").exists())
            self.assertTrue((run_dir / "report.md").exists())

            list_proc = run(["list-runs", "--runs-root", str(root), "--limit", "1"])
            self.assertEqual(list_proc.returncode, 0, list_proc.stdout + list_proc.stderr)
            self.assertIn("WALTER_RUNS", list_proc.stdout)
            self.assertIn("status=PASS", list_proc.stdout)

            status_proc = run(["status", str(run_dir), "--runs-root", str(root)])
            self.assertEqual(status_proc.returncode, 0, status_proc.stdout + status_proc.stderr)
            self.assertIn("WALTER_STATUS", status_proc.stdout)
            self.assertIn("gate: PASS", status_proc.stdout)
            self.assertIn("next_action:", status_proc.stdout)

            score_proc = run(["score", str(run_dir), "--runs-root", str(root)])
            self.assertEqual(score_proc.returncode, 0, score_proc.stdout + score_proc.stderr)
            self.assertIn("WALTER_SCORE", score_proc.stdout)
            self.assertIn("score: 100", score_proc.stdout)
            self.assertIn("grade: A", score_proc.stdout)

            hygiene_proc = run(["hygiene", "--runs-root", str(root), "--all"])
            self.assertEqual(hygiene_proc.returncode, 0, hygiene_proc.stdout + hygiene_proc.stderr)
            self.assertIn("WALTER_HYGIENE", hygiene_proc.stdout)
            self.assertIn("score=100", hygiene_proc.stdout)

            inspect_proc = run(["inspect", str(run_dir), "--runs-root", str(root)])
            self.assertEqual(inspect_proc.returncode, 0, inspect_proc.stdout + inspect_proc.stderr)
            self.assertIn("WALTER_INSPECT", inspect_proc.stdout)
            self.assertIn("artifacts:", inspect_proc.stdout)
            self.assertIn("receipt.json: ok", inspect_proc.stdout)

            apply_check = run(["apply-diff", str(run_dir), "--runs-root", str(root)])
            self.assertEqual(apply_check.returncode, 0, apply_check.stdout + apply_check.stderr)
            self.assertIn("APPLY_DIFF NO_CHANGES", apply_check.stdout)

            (project / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            dirty_check = run(["apply-diff", str(run_dir), "--runs-root", str(root)])
            self.assertNotEqual(dirty_check.returncode, 0)
            self.assertIn("APPLY_DIFF REFUSE target_dirty", dirty_check.stdout)

    def test_parse_worktree_porcelain_finds_paths(self) -> None:
        module = load_safe_module()
        paths = module.parse_worktree_porcelain(
            "worktree /tmp/project\nHEAD abc\n\nworktree /tmp/run/worktree\ndetached\n"
        )
        self.assertEqual(paths, [Path("/tmp/project").resolve(), Path("/tmp/run/worktree").resolve()])

    def test_cleanup_worktrees_default_is_dry_run(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            make_git_repo(project)
            proc = run(["cleanup-worktrees", "--project-path", str(project), "--runs-root", str(root)])
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue("DRY_RUN" in proc.stdout or "CLEANUP_WORKTREES none" in proc.stdout)
            if "CLEANUP_WORKTREES candidates" in proc.stdout:
                self.assertIn("run_id=", proc.stdout)
                self.assertIn("status=", proc.stdout)

    def test_cleanup_confirm_refuses_bulk_remove(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            make_git_repo(project)
            proc = run(["cleanup-worktrees", "--project-path", str(project), "--runs-root", str(root), "--confirm"])
            if "CLEANUP_WORKTREES none" in proc.stdout:
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            else:
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn("REFUSE", proc.stdout)

    def test_cleanup_unknown_run_id_is_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            make_git_repo(project)
            proc = run([
                "cleanup-worktrees",
                "--project-path", str(project),
                "--runs-root", str(root),
                "--run-id", "definitely-missing-run-id",
            ])
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("requested_run_ids_not_found", proc.stdout)

    def test_endurance_plan_prints_protocol_and_background_rule(self) -> None:
        proc = run(["endurance-plan", "--minutes", "30"])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("WALTER_ENDURANCE_PLAN", proc.stdout)
        self.assertIn("codex_timeout_seconds: 1800", proc.stdout)
        self.assertIn("verification_timeout_seconds: 2100", proc.stdout)
        self.assertIn("calculated_runner_timeout_seconds: 4200", proc.stdout)
        self.assertIn("background_rule", proc.stdout)
        self.assertIn("ENDURANCE.md", proc.stdout)


if __name__ == "__main__":
    unittest.main()
