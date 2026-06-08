#!/usr/bin/env python3
"""Hostile fixtures for walter_runner.py run mode.

These tests exercise the runner itself with a fake Codex binary. The fake binary
mutates a detached worktree, while the runner must classify the bundle from
independent git/verification evidence rather than the fake Codex transcript.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "walter_runner.py"
RUNS = ROOT / "runs"


def run(cmd: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False, **kwargs)


def make_git_project(root: Path) -> Path:
    project = root / "source-project"
    (project / "src").mkdir(parents=True)
    (project / "tests").mkdir(parents=True)
    (project / "src" / "README.txt").write_text("seed\n", encoding="utf-8")
    run(["git", "init"], project)
    run(["git", "config", "user.email", "walter@example.invalid"], project)
    run(["git", "config", "user.name", "Walter Runner Test"], project)
    run(["git", "add", "."], project)
    commit = run(["git", "commit", "-m", "seed"], project)
    if commit.returncode != 0:
        raise AssertionError(commit.stdout + commit.stderr)
    return project


def make_fake_codex(root: Path) -> Path:
    fake = root / "fake_codex.py"
    fake.write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env python3
            from __future__ import annotations
            import os
            import time
            from pathlib import Path

            mode = os.environ.get("FAKE_CODEX_MODE", "allowed")
            cwd = Path.cwd()
            if mode == "allowed":
                path = cwd / "src" / "codex_gate_smoke.txt"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("WALTER_GATE_SMOKE=ok\\n", encoding="utf-8")
            elif mode == "allowed_outside_read":
                path = cwd / "src" / "codex_gate_smoke.txt"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("WALTER_GATE_SMOKE=ok\\n", encoding="utf-8")
                forbidden = Path.home() / ".ssh" / "id_rsa"
                print(f"exec /bin/zsh -lc sed -n '1,20p' {forbidden}")
            elif mode == "outside":
                (cwd / "README.md").write_text("outside change\\n", encoding="utf-8")
            elif mode == "forbidden":
                (cwd / ".env").write_text("PRIVATE_MARKER=fixture\\n", encoding="utf-8")
            elif mode == "noop":
                pass
            elif mode == "slow":
                time.sleep(3)
            else:
                raise SystemExit(f"unknown fake mode: {mode}")
            print(f"fake codex finished: {mode}")
            """
        ).lstrip(),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


class WalterRunnerRunModeFixtures(unittest.TestCase):
    def setUp(self) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="test-walter-runner-", dir=str(RUNS))
        self.root = Path(self.tmp.name)
        self.project = make_git_project(self.root)
        self.fake_codex = make_fake_codex(self.root)

    def tearDown(self) -> None:
        # Remove any registered worktree before deleting the temp source repo.
        worktree = self.root / "run" / "worktree"
        if worktree.exists():
            run(["git", "-C", str(self.project), "worktree", "remove", "--force", str(worktree)], self.root)
        self.tmp.cleanup()

    def runner(self, mode: str, *extra: str) -> subprocess.CompletedProcess[str]:
        run_dir = self.root / "run"
        env = os.environ.copy()
        env["FAKE_CODEX_MODE"] = mode
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "run",
                str(run_dir),
                "--goal",
                "Create src/codex_gate_smoke.txt with exactly WALTER_GATE_SMOKE=ok.",
                "--project-path",
                str(self.project),
                "--allowed-path",
                "src/**",
                "--forbidden-path",
                ".env",
                "--verification-command",
                "test -f src/codex_gate_smoke.txt && grep -qx 'WALTER_GATE_SMOKE=ok' src/codex_gate_smoke.txt",
                "--codex-command",
                str(self.fake_codex),
                "--worktree",
                *extra,
            ],
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_run_passes_allowed_worktree_change(self) -> None:
        proc = self.runner("allowed")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("RUN PASS", proc.stdout)
        diff = (self.root / "run" / "diff.patch").read_text(encoding="utf-8")
        self.assertIn("src/codex_gate_smoke.txt", diff)
        self.assertIn("WALTER_GATE_SMOKE=ok", diff)
        self.assertNotEqual(diff.strip(), "NO_DIFF")
        gate = run([sys.executable, str(ROOT / "scripts" / "nacho_walter_gate.py"), str(self.root / "run")], ROOT)
        self.assertEqual(gate.returncode, 0, gate.stdout + gate.stderr)

    def test_run_rejects_outside_read_evidence(self) -> None:
        proc = self.runner("allowed_outside_read")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RUN NEEDS_APPROVAL", proc.stdout)
        receipt = (self.root / "run" / "receipt.json").read_text(encoding="utf-8")
        self.assertIn("outside_project_read_hits", receipt)
        gate = run([sys.executable, str(ROOT / "scripts" / "nacho_walter_gate.py"), str(self.root / "run"), "--no-require-pass"], ROOT)
        self.assertNotEqual(gate.returncode, 0)
        self.assertIn("outside project read hits present", gate.stdout)

    def test_log_scans_ignore_indented_source_fixture_paths(self) -> None:
        import importlib.util

        module_path = ROOT / "scripts" / "walter_runner.py"
        spec = importlib.util.spec_from_file_location("walter_runner_under_test", module_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        allowed = ROOT.resolve()
        forbidden = Path.home() / ".ssh" / "id_rsa"
        log_text = f"""
        print(\"exec /bin/zsh -lc sed -n '1,20p' {forbidden}\")
/bin/zsh -lc pwd in {allowed}
"""
        result = module.outside_read_scan(log_text, [allowed])
        self.assertEqual(result, {"status": "PASS", "hits": []})

    def test_log_scans_reject_actual_external_command_paths(self) -> None:
        import importlib.util

        module_path = ROOT / "scripts" / "walter_runner.py"
        spec = importlib.util.spec_from_file_location("walter_runner_under_test_actual", module_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        allowed = ROOT.resolve()
        forbidden = Path.home() / ".ssh" / "id_rsa"
        log_text = f"/bin/zsh -lc sed -n '1,20p' {forbidden}\n"
        result = module.outside_read_scan(log_text, [allowed])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(str(forbidden), result["hits"])

    def test_run_rejects_outside_allowed_change(self) -> None:
        proc = self.runner("outside")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RUN OUT_OF_SCOPE_CHANGE", proc.stdout)

    def test_run_rejects_forbidden_change(self) -> None:
        proc = self.runner("forbidden")
        self.assertNotEqual(proc.returncode, 0)
        # Secret scan may escalate this to NEEDS_APPROVAL after forbidden path detection.
        self.assertTrue("RUN NEEDS_APPROVAL" in proc.stdout or "RUN OUT_OF_SCOPE_CHANGE" in proc.stdout, proc.stdout)

    def test_run_rejects_missing_verification_evidence(self) -> None:
        proc = self.runner("noop")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RUN FAIL_VERIFICATION", proc.stdout)

    def test_run_writes_receipt_when_codex_times_out(self) -> None:
        proc = self.runner("slow", "--timeout", "1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RUN FAILED_TIMEOUT", proc.stdout)
        receipt = (self.root / "run" / "receipt.json").read_text(encoding="utf-8")
        self.assertIn('"timed_out": true', receipt)
        self.assertIn("CODEX_TIMEOUT after 1s", (self.root / "run" / "codex.log").read_text(encoding="utf-8"))

    def test_run_marks_verification_command_timeout(self) -> None:
        proc = self.runner(
            "allowed",
            "--verification-timeout",
            "1",
            "--verification-command",
            "python3 -c 'import time; time.sleep(3)'",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RUN FAIL_VERIFICATION", proc.stdout)
        receipt = (self.root / "run" / "receipt.json").read_text(encoding="utf-8")
        self.assertIn('"timed_out": true', receipt)
        self.assertIn("VERIFICATION_TIMEOUT after 1s", (self.root / "run" / "verify.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
