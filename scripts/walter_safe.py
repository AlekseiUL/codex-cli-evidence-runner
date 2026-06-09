#!/usr/bin/env python3
"""Convenience CLI for safe Walter/Codex runs.

This wrapper keeps the normal internal path short:
- run Codex through walter_runner.py;
- validate receipt contract;
- run Nacho gate;
- print a compact summary.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import subprocess
import sys
from pathlib import Path

WALTER_ROOT = Path(__file__).resolve().parents[1]
MIKE_ROOT = WALTER_ROOT.parents[1]
RUNNER = WALTER_ROOT / "scripts" / "walter_runner.py"
VALIDATOR = WALTER_ROOT / "scripts" / "validate_runner_contract.py"
NACHO_GATE = WALTER_ROOT / "scripts" / "nacho_walter_gate.py"
DEFAULT_PROJECT = WALTER_ROOT / "workspace-repo"
DEFAULT_RUNS = WALTER_ROOT / "runs"
DEFAULT_FORBIDDEN_PATHS = [".env", "secrets/**"]
DEFAULT_ACCEPTANCE = [
    "requested change is implemented",
    "changes stay inside allowed paths",
    "verification commands pass",
]
DEFAULT_VERIFY = ["python3 -m unittest discover -s tests -v"]


def run(cmd: list[str], *, cwd: Path = MIKE_ROOT, timeout: int | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return 124, stdout + stderr + f"\nWALTER_SAFE_TIMEOUT after {timeout}s\n"


def quote_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def default_run_dir(name: str | None) -> Path:
    suffix = name or "safe-run"
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_RUNS / f"{stamp}-{suffix}"


def build_runner_cmd(args: argparse.Namespace, run_dir: Path, project: Path) -> list[str]:
    cmd = [
        sys.executable,
        str(RUNNER),
        "run",
        str(run_dir),
        "--goal",
        args.goal,
        "--project-path",
        str(project),
        "--scenario",
        args.scenario,
        "--model",
        args.model,
        "--reasoning-effort",
        args.reasoning_effort,
        "--codex-command",
        args.codex_command,
        "--timeout",
        str(args.timeout),
        "--verification-timeout",
        str(args.verification_timeout),
    ]
    for allowed in args.allowed_path or ["src/**"]:
        cmd += ["--allowed-path", allowed]
    for forbidden in args.forbidden_path or DEFAULT_FORBIDDEN_PATHS:
        cmd += ["--forbidden-path", forbidden]
    for verify in args.verification_command or DEFAULT_VERIFY:
        cmd += ["--verification-command", verify]
    for check in args.acceptance_check or DEFAULT_ACCEPTANCE:
        cmd += ["--acceptance-check", check]
    if args.codex_home:
        cmd += ["--codex-home", args.codex_home]
    if args.pty:
        cmd.append("--pty")
    if not args.no_worktree:
        cmd.append("--worktree")
    if args.skip_codex:
        cmd.append("--skip-codex")
    return cmd


def verification_command_count(args: argparse.Namespace) -> int:
    return max(1, len(args.verification_command or DEFAULT_VERIFY))


def calculated_runner_timeout(args: argparse.Namespace) -> int:
    if args.runner_timeout is not None:
        return args.runner_timeout
    # Runner timeout is not the Codex timeout. It must include Codex time,
    # every verification command budget, and enough post-processing time to
    # write receipt/report and run local gates. Otherwise long jobs die without
    # evidence, which is worse than a clean FAIL.
    return args.timeout + args.verification_timeout * verification_command_count(args) + 300


def cmd_run_safe(args: argparse.Namespace) -> int:
    project = Path(args.project_path).expanduser().resolve()
    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else default_run_dir(args.name).resolve()
    runner_cmd = build_runner_cmd(args, run_dir, project)

    print(f"RUN_DIR {run_dir}")
    print(f"PROJECT {project}")
    if args.print_command or args.dry_run:
        print("RUNNER_CMD")
        print(quote_cmd(runner_cmd))
    if args.dry_run:
        return 0

    code, out = run(runner_cmd, timeout=calculated_runner_timeout(args))
    print(out.rstrip())
    if code != 0:
        print(f"WALTER_SAFE RUNNER_FAILED exit={code}")
        return code

    checks: list[tuple[str, list[str]]] = [
        ("RECEIPT_CONTRACT", [sys.executable, str(VALIDATOR), "receipt", str(run_dir / "receipt.json")]),
        ("NACHO_GATE", [sys.executable, str(NACHO_GATE), str(run_dir)] + (["--allow-risk"] if args.allow_risk else [])),
        ("SUMMARY", [sys.executable, str(RUNNER), "summarize", str(run_dir)]),
    ]
    final_code = 0
    for label, cmd in checks:
        check_code, check_out = run(cmd, timeout=120)
        print(f"\n## {label}")
        print(check_out.rstrip())
        if check_code != 0 and label != "SUMMARY":
            final_code = check_code

    print("\nWALTER_SAFE PASS" if final_code == 0 else "\nWALTER_SAFE FAIL")
    return final_code


def parse_worktree_porcelain(text: str) -> list[Path]:
    paths: list[Path] = []
    for line in text.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.split(" ", 1)[1]).expanduser().resolve())
    return paths


def managed_worktree_candidates(project: Path = DEFAULT_PROJECT, runs_root: Path = DEFAULT_RUNS) -> list[Path]:
    code, out = run(["git", "-C", str(project), "worktree", "list", "--porcelain"])
    if code != 0:
        raise RuntimeError(out.strip() or "git worktree list failed")
    runs_root = runs_root.expanduser().resolve()
    candidates: list[Path] = []
    for path in parse_worktree_porcelain(out):
        if path.name != "worktree":
            continue
        if runs_root in path.parents:
            candidates.append(path)
    return sorted(candidates)


def run_dir_for_worktree(path: Path) -> Path:
    return path.parent


def candidate_summary(path: Path) -> dict[str, str]:
    run_dir = run_dir_for_worktree(path)
    receipt_path = run_dir / "receipt.json"
    status = "NO_RECEIPT"
    changed = "?"
    risk = "unknown"
    if receipt_path.exists():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            status = str(receipt.get("status", "UNKNOWN"))
            changes = receipt.get("changes", {}) if isinstance(receipt.get("changes"), dict) else {}
            verification = receipt.get("verification", {}) if isinstance(receipt.get("verification"), dict) else {}
            changed_files = changes.get("changed_files", [])
            changed = str(len(changed_files) if isinstance(changed_files, list) else "?")
            risky = bool(changes.get("outside_allowed_paths")) or bool(changes.get("forbidden_changed_paths"))
            risky = risky or bool(verification.get("secret_scan_hits")) or bool(verification.get("outside_project_read_hits"))
            risk = "risk" if risky else "clean"
        except Exception:  # noqa: BLE001
            status = "BAD_RECEIPT"
            risk = "risk"
    return {
        "run_id": run_dir.name,
        "status": status,
        "changed": changed,
        "risk": risk,
        "path": str(path),
    }


def resolve_run_dir(run: str, runs_root: Path = DEFAULT_RUNS) -> Path:
    candidate = Path(run).expanduser()
    if candidate.exists():
        return candidate.resolve()
    return (runs_root.expanduser().resolve() / run).resolve()


def iter_run_dirs(runs_root: Path = DEFAULT_RUNS) -> list[Path]:
    runs_root = runs_root.expanduser().resolve()
    if not runs_root.exists():
        return []
    dirs = [path for path in runs_root.iterdir() if path.is_dir()]
    return sorted(dirs, key=lambda path: path.stat().st_mtime, reverse=True)


def load_receipt(run_dir: Path) -> dict[str, object] | None:
    receipt_path = run_dir / "receipt.json"
    if not receipt_path.exists():
        return None
    try:
        data = json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"status": "BAD_RECEIPT"}
    return data if isinstance(data, dict) else {"status": "BAD_RECEIPT"}


def run_summary(run_dir: Path) -> dict[str, str]:
    receipt = load_receipt(run_dir)
    status = "NO_RECEIPT" if receipt is None else str(receipt.get("status", "UNKNOWN"))
    changes = receipt.get("changes", {}) if isinstance(receipt, dict) and isinstance(receipt.get("changes"), dict) else {}
    verification = receipt.get("verification", {}) if isinstance(receipt, dict) and isinstance(receipt.get("verification"), dict) else {}
    rollback = receipt.get("rollback", {}) if isinstance(receipt, dict) and isinstance(receipt.get("rollback"), dict) else {}
    changed_files = changes.get("changed_files", []) if isinstance(changes, dict) else []
    changed = str(len(changed_files) if isinstance(changed_files, list) else "?")
    risky = status != "PASS"
    risky = risky or bool(changes.get("outside_allowed_paths")) or bool(changes.get("forbidden_changed_paths"))
    risky = risky or bool(verification.get("secret_scan_hits")) or bool(verification.get("outside_project_read_hits"))
    gate = "unknown"
    if (run_dir / "receipt.json").exists():
        gate_code, _ = run([sys.executable, str(NACHO_GATE), str(run_dir)], timeout=120)
        gate = "PASS" if gate_code == 0 else "FAIL"
    return {
        "run_id": run_dir.name,
        "status": status,
        "gate": gate,
        "changed": changed,
        "risk": "risk" if risky else "clean",
        "rollback": str(rollback.get("possible", "?")),
        "path": str(run_dir),
    }


def next_action(summary: dict[str, str]) -> str:
    if summary["status"] == "PASS" and summary["gate"] == "PASS" and summary["risk"] == "clean":
        return "review diff.patch, then apply only if the diff matches the task"
    if summary["status"] == "NO_RECEIPT":
        return "reject result; inspect logs/process state; rerun with receipt generation"
    if summary["status"] == "FAILED_TIMEOUT":
        return "treat as failed; split task or increase the specific timed-out budget"
    if summary["status"] == "FAIL_VERIFICATION":
        return "read verify.log; do not trust Codex final text"
    if summary["status"] in {"NEEDS_APPROVAL", "OUT_OF_SCOPE_CHANGE"}:
        return "stop; inspect receipt risk fields before any apply"
    if summary["gate"] == "FAIL":
        return "do not apply; Nacho gate failed"
    return "inspect receipt.json, report.md, verify.log, diff.patch"


def evidence_score(run_dir: Path) -> tuple[int, list[str]]:
    receipt = load_receipt(run_dir)
    if not isinstance(receipt, dict):
        return 0, ["missing or unreadable receipt"]

    score = 0
    notes: list[str] = []
    status = str(receipt.get("status", ""))
    changes = receipt.get("changes", {}) if isinstance(receipt.get("changes"), dict) else {}
    verification = receipt.get("verification", {}) if isinstance(receipt.get("verification"), dict) else {}
    rollback = receipt.get("rollback", {}) if isinstance(receipt.get("rollback"), dict) else {}

    if status == "PASS":
        score += 20
    else:
        notes.append(f"status={status or 'UNKNOWN'}")

    gate_code, _ = run([sys.executable, str(NACHO_GATE), str(run_dir)], timeout=120)
    if gate_code == 0:
        score += 15
    else:
        notes.append("Nacho gate failed")

    if not changes.get("outside_allowed_paths") and not changes.get("forbidden_changed_paths"):
        score += 10
    else:
        notes.append("scope violations present")

    if verification.get("verification_commands_ok") is True:
        score += 10
    else:
        notes.append("verification commands not clean")

    if verification.get("secret_scan") == "PASS" and not verification.get("secret_scan_hits"):
        score += 10
    else:
        notes.append("secret scan not clean")

    if verification.get("outside_project_read_scan") == "PASS" and not verification.get("outside_project_read_hits"):
        score += 10
    else:
        notes.append("outside-read scan not clean")

    if changes.get("diff_available") is True and (run_dir / "diff.patch").exists():
        score += 10
    else:
        notes.append("diff evidence missing")

    if rollback.get("possible") is True and rollback.get("method") and rollback.get("instructions"):
        score += 5
    else:
        notes.append("rollback evidence weak")

    required = ["input.json", "policy.yaml", "prompt.md", "codex.log", "diff.patch", "verify.log", "receipt.json", "report.md"]
    missing = [name for name in required if not (run_dir / name).exists() or (run_dir / name).stat().st_size == 0]
    if not missing:
        score += 5
    else:
        notes.append("missing/empty artifacts: " + ",".join(missing))

    if Path(str(receipt.get("report_path", ""))).expanduser().exists():
        score += 5
    else:
        notes.append("report path missing")

    return min(score, 100), notes


def score_grade(score: int) -> str:
    if score >= 95:
        return "A"
    if score >= 85:
        return "B"
    if score >= 70:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def cmd_score(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.run, Path(args.runs_root))
    if not run_dir.exists():
        print(f"WALTER_SCORE missing run={args.run}")
        return 1
    summary = run_summary(run_dir)
    score, notes = evidence_score(run_dir)
    print("WALTER_SCORE")
    print(f"run_id: {summary['run_id']}")
    print(f"score: {score}")
    print(f"grade: {score_grade(score)}")
    print(f"status: {summary['status']}")
    print(f"gate: {summary['gate']}")
    print(f"risk: {summary['risk']}")
    if notes:
        print("notes:")
        for note in notes:
            print(f"- {note}")
    print(f"next_action: {next_action(summary)}")
    return 0 if score >= args.min_score and summary["gate"] == "PASS" and summary["risk"] == "clean" else 1


def cmd_hygiene(args: argparse.Namespace) -> int:
    dirs = iter_run_dirs(Path(args.runs_root))[: args.limit]
    print("WALTER_HYGIENE")
    if not dirs:
        print("runs: none")
        return 0
    issues = 0
    for run_dir in dirs:
        summary = run_summary(run_dir)
        score, _ = evidence_score(run_dir)
        if summary["risk"] == "clean" and summary["gate"] == "PASS" and score >= args.min_score:
            if not args.all:
                continue
        else:
            issues += 1
        print(
            f"run_id={summary['run_id']} score={score} status={summary['status']} "
            f"gate={summary['gate']} risk={summary['risk']} next='{next_action(summary)}'"
        )
    if issues == 0:
        print("issues: none")
    else:
        print(f"issues: {issues}")
    print("cleanup: destructive worktree removal still requires cleanup-worktrees --confirm --run-id <id>")
    return 0


def cmd_list_runs(args: argparse.Namespace) -> int:
    dirs = iter_run_dirs(Path(args.runs_root))[: args.limit]
    if not dirs:
        print("WALTER_RUNS none")
        return 0
    print("WALTER_RUNS")
    for run_dir in dirs:
        summary = run_summary(run_dir)
        print(
            f"run_id={summary['run_id']} status={summary['status']} gate={summary['gate']} "
            f"changed={summary['changed']} risk={summary['risk']} rollback={summary['rollback']}"
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.run, Path(args.runs_root))
    if not run_dir.exists():
        print(f"WALTER_STATUS missing run={args.run}")
        return 1
    summary = run_summary(run_dir)
    print("WALTER_STATUS")
    for key in ["run_id", "status", "gate", "changed", "risk", "rollback", "path"]:
        print(f"{key}: {summary[key]}")
    print(f"next_action: {next_action(summary)}")
    return 0 if summary["status"] == "PASS" and summary["gate"] == "PASS" and summary["risk"] == "clean" else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.run, Path(args.runs_root))
    if not run_dir.exists():
        print(f"WALTER_INSPECT missing run={args.run}")
        return 1
    summary = run_summary(run_dir)
    print("WALTER_INSPECT")
    for key in ["run_id", "status", "gate", "changed", "risk", "rollback", "path"]:
        print(f"{key}: {summary[key]}")
    print(f"next_action: {next_action(summary)}")
    print("artifacts:")
    for name in ["input.json", "prompt.md", "codex.log", "diff.patch", "verify.log", "receipt.json", "report.md"]:
        artifact = run_dir / name
        size = artifact.stat().st_size if artifact.exists() else 0
        state = "ok" if artifact.exists() and size > 0 else ("empty" if artifact.exists() else "missing")
        print(f"- {name}: {state} bytes={size} path={artifact}")
    return 0 if summary["status"] == "PASS" and summary["gate"] == "PASS" and summary["risk"] == "clean" else 1


def ensure_git_repo(path: Path) -> bool:
    code, _ = run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], timeout=60)
    return code == 0


def git_dirty(path: Path) -> tuple[bool, str]:
    code, out = run(["git", "-C", str(path), "status", "--porcelain"], timeout=60)
    if code != 0:
        return True, out.strip() or "git status failed"
    return bool(out.strip()), out.strip()


def safe_diff_text(diff_path: Path) -> str:
    if not diff_path.exists():
        return ""
    text = diff_path.read_text(encoding="utf-8", errors="replace")
    if text.strip() == "NO_DIFF":
        return ""
    return text


def cmd_apply_diff(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.run, Path(args.runs_root))
    if not run_dir.exists():
        print(f"APPLY_DIFF FAIL missing run={args.run}")
        return 1
    summary = run_summary(run_dir)
    if summary["status"] != "PASS" or summary["gate"] != "PASS" or summary["risk"] != "clean":
        print("APPLY_DIFF REFUSE gate_not_clean")
        for key in ["status", "gate", "risk", "path"]:
            print(f"{key}: {summary[key]}")
        print(f"next_action: {next_action(summary)}")
        return 1

    receipt = load_receipt(run_dir)
    if not isinstance(receipt, dict):
        print("APPLY_DIFF FAIL receipt_unreadable")
        return 1
    project_path = Path(str(receipt.get("project_path", ""))).expanduser().resolve()
    if args.project_path:
        project_path = Path(args.project_path).expanduser().resolve()
    if not project_path.exists():
        print(f"APPLY_DIFF FAIL project_missing path={project_path}")
        return 1
    if not ensure_git_repo(project_path):
        print(f"APPLY_DIFF REFUSE target_not_git_repo path={project_path}")
        return 1
    dirty, dirty_out = git_dirty(project_path)
    if dirty and not args.allow_dirty:
        print("APPLY_DIFF REFUSE target_dirty")
        print(dirty_out)
        return 1

    changes = receipt.get("changes", {}) if isinstance(receipt.get("changes"), dict) else {}
    diff_path = Path(str(changes.get("diff_path", run_dir / "diff.patch"))).expanduser()
    if not diff_path.is_absolute():
        diff_path = run_dir / diff_path
    diff_text = safe_diff_text(diff_path)
    if not diff_text.strip():
        print("APPLY_DIFF NO_CHANGES")
        print(f"run_dir: {run_dir}")
        print(f"project: {project_path}")
        return 0

    check_code, check_out = run(["git", "-C", str(project_path), "apply", "--check", str(diff_path)], timeout=120)
    if check_code != 0:
        print("APPLY_DIFF CHECK_FAIL")
        print(check_out.rstrip())
        return check_code
    print("APPLY_DIFF CHECK_PASS")
    print(f"run_dir: {run_dir}")
    print(f"project: {project_path}")
    print(f"diff: {diff_path}")
    if not args.confirm:
        print("DRY_RUN only. Re-run with --confirm after reviewing diff.patch. No files changed.")
        return 0
    apply_code, apply_out = run(["git", "-C", str(project_path), "apply", str(diff_path)], timeout=120)
    if apply_code != 0:
        print("APPLY_DIFF APPLY_FAIL")
        print(apply_out.rstrip())
        return apply_code
    print("APPLY_DIFF APPLIED")
    print("No commit was created. Review git diff/status before committing.")
    return 0


def cmd_cleanup_worktrees(args: argparse.Namespace) -> int:
    project = Path(args.project_path).expanduser().resolve()
    runs_root = Path(args.runs_root).expanduser().resolve()
    try:
        candidates = managed_worktree_candidates(project, runs_root)
    except RuntimeError as exc:
        print(f"CLEANUP_WORKTREES FAIL: {exc}")
        return 1

    requested = set(args.run_id or [])
    if requested:
        candidates = [path for path in candidates if run_dir_for_worktree(path).name in requested]

    if not candidates:
        print("CLEANUP_WORKTREES none")
        if requested:
            print("requested_run_ids_not_found: " + ",".join(sorted(requested)))
        return 0

    print("CLEANUP_WORKTREES candidates")
    for path in candidates:
        summary = candidate_summary(path)
        print(
            f"run_id={summary['run_id']} status={summary['status']} "
            f"changed={summary['changed']} risk={summary['risk']} path={summary['path']}"
        )

    if not args.confirm:
        print("DRY_RUN only. Re-run with --confirm --run-id <id> after explicit approval to remove selected worktrees.")
        return 0

    if not requested:
        print("REFUSE: --confirm requires at least one --run-id. No bulk removal by default.")
        return 2

    final_code = 0
    for path in candidates:
        cmd = ["git", "-C", str(project), "worktree", "remove", str(path)]
        if args.force:
            cmd.insert(5, "--force")
        code, out = run(cmd)
        if code == 0:
            print(f"REMOVED {path}")
        else:
            final_code = code
            print(f"REMOVE_FAILED {path}\n{out.rstrip()}")
    return final_code


def cmd_endurance_plan(args: argparse.Namespace) -> int:
    minutes = args.minutes
    codex_timeout = max(1800, minutes * 60)
    verification_timeout = max(900, minutes * 60 + 300)
    runner_timeout = codex_timeout + verification_timeout + 300
    print("WALTER_ENDURANCE_PLAN")
    print(f"duration_minutes: {minutes}")
    print(f"codex_timeout_seconds: {codex_timeout}")
    print(f"verification_timeout_seconds: {verification_timeout}")
    print(f"calculated_runner_timeout_seconds: {runner_timeout}")
    print("command_template:")
    print(
        "agents/walter/scripts/walter run-safe "
        "--name endurance-$(date +%Y%m%d-%H%M%S) "
        "--goal '<bounded multi-step goal>' "
        "--allowed-path 'src/**' --allowed-path 'tests/**' "
        "--verification-command 'python3 -m unittest discover -s tests -v' "
        f"--timeout {codex_timeout} --verification-timeout {verification_timeout}"
    )
    print("background_rule: use terminal(background=True, notify_on_complete=True) for 30+ minute runs")
    print(f"protocol: {WALTER_ROOT / 'ENDURANCE.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-cli-evidence-runner",
        description="Safe convenience wrapper for Codex CLI evidence runs",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_safe = sub.add_parser("run-safe", help="run Walter runner + receipt validation + Nacho gate")
    run_safe.add_argument("--goal", required=True)
    run_safe.add_argument("--name", help="run id suffix; timestamp is prepended")
    run_safe.add_argument("--run-dir", help="explicit run directory")
    run_safe.add_argument("--project-path", default=str(DEFAULT_PROJECT))
    run_safe.add_argument("--scenario", choices=["implementation", "repair", "verification"], default="implementation")
    run_safe.add_argument("--allowed-path", action="append")
    run_safe.add_argument("--forbidden-path", action="append")
    run_safe.add_argument("--verification-command", action="append")
    run_safe.add_argument("--acceptance-check", action="append")
    run_safe.add_argument("--model", default="gpt-5.5")
    run_safe.add_argument("--reasoning-effort", default="xhigh")
    run_safe.add_argument("--codex-command", default="codex")
    run_safe.add_argument("--codex-home", help="HOME directory for Codex CLI auth/config; defaults to current process HOME")
    run_safe.add_argument("--pty", action="store_true", help="record PTY intent in runner preflight; execution is non-PTY subprocess mode")
    run_safe.add_argument("--timeout", type=int, default=560, help="Codex execution timeout in seconds")
    run_safe.add_argument("--verification-timeout", type=int, default=600, help="timeout per verification command in seconds")
    run_safe.add_argument("--runner-timeout", type=int, help="parent wrapper timeout; default = codex + verification budgets + 300s")
    run_safe.add_argument("--no-worktree", action="store_true", help="disable git worktree mode; not normal path")
    run_safe.add_argument("--allow-risk", action="store_true", help="pass --allow-risk to Nacho gate")
    run_safe.add_argument("--skip-codex", action="store_true", help="forward --skip-codex for wrapper tests")
    run_safe.add_argument("--dry-run", action="store_true")
    run_safe.add_argument("--print-command", action="store_true")
    run_safe.set_defaults(func=cmd_run_safe)

    list_runs = sub.add_parser("list-runs", help="list recent Walter run receipts")
    list_runs.add_argument("--runs-root", default=str(DEFAULT_RUNS))
    list_runs.add_argument("--limit", type=int, default=10)
    list_runs.set_defaults(func=cmd_list_runs)

    status = sub.add_parser("status", help="compact verdict for a Walter run")
    status.add_argument("run", help="run id or run directory path")
    status.add_argument("--runs-root", default=str(DEFAULT_RUNS))
    status.set_defaults(func=cmd_status)

    score = sub.add_parser("score", help="numeric evidence score for a Walter run")
    score.add_argument("run", help="run id or run directory path")
    score.add_argument("--runs-root", default=str(DEFAULT_RUNS))
    score.add_argument("--min-score", type=int, default=95)
    score.set_defaults(func=cmd_score)

    hygiene = sub.add_parser("hygiene", help="show risky/incomplete recent Walter runs")
    hygiene.add_argument("--runs-root", default=str(DEFAULT_RUNS))
    hygiene.add_argument("--limit", type=int, default=20)
    hygiene.add_argument("--min-score", type=int, default=95)
    hygiene.add_argument("--all", action="store_true", help="show clean runs too")
    hygiene.set_defaults(func=cmd_hygiene)

    inspect = sub.add_parser("inspect", help="print verdict plus artifact state for a Walter run")
    inspect.add_argument("run", help="run id or run directory path")
    inspect.add_argument("--runs-root", default=str(DEFAULT_RUNS))
    inspect.set_defaults(func=cmd_inspect)

    apply_diff = sub.add_parser("apply-diff", help="dry-run/check or apply a gated Walter diff")
    apply_diff.add_argument("run", help="run id or run directory path")
    apply_diff.add_argument("--runs-root", default=str(DEFAULT_RUNS))
    apply_diff.add_argument("--project-path", help="override target project path from receipt")
    apply_diff.add_argument("--confirm", action="store_true", help="actually apply after gate/check pass; default is dry-run")
    apply_diff.add_argument("--allow-dirty", action="store_true", help="allow applying/checking against a dirty target checkout")
    apply_diff.set_defaults(func=cmd_apply_diff)

    cleanup = sub.add_parser("cleanup-worktrees", help="preview or remove managed Walter run worktrees")
    cleanup.add_argument("--project-path", default=str(DEFAULT_PROJECT))
    cleanup.add_argument("--runs-root", default=str(DEFAULT_RUNS))
    cleanup.add_argument("--confirm", action="store_true", help="actually remove selected candidates; deletion requires explicit approval")
    cleanup.add_argument("--run-id", action="append", help="run id to remove when --confirm is used; repeatable")
    cleanup.add_argument("--force", action="store_true", help="pass --force to git worktree remove")
    cleanup.set_defaults(func=cmd_cleanup_worktrees)

    endurance = sub.add_parser("endurance-plan", help="print the long-run operating protocol and command template")
    endurance.add_argument("--minutes", type=int, default=30)
    endurance.set_defaults(func=cmd_endurance_plan)
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
