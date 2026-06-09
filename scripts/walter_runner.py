#!/usr/bin/env python3
"""Walter runner helper.

Stdlib helper for Walter's internal Codex-CLI run bundles. It creates/checks the
control artifacts around Codex runs and can execute a bounded Codex run with an
independent receipt.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

WALTER_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = WALTER_ROOT / "templates"
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

DEFAULT_FORBIDDEN_READ_ROOTS = [
    str(Path.home() / ".ssh"),
    str(Path.home() / ".aws"),
    str(Path.home() / ".config"),
    str(Path.home() / ".gnupg"),
]

PROMPT_TEMPLATES = {
    "implementation": TEMPLATES / "prompts" / "implementation.md",
    "repair": TEMPLATES / "prompts" / "repair.md",
    "verification": TEMPLATES / "prompts" / "verification.md",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def append_log(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(text)
        if text and not text.endswith("\n"):
            fh.write("\n")


def run_capture(cmd: list[str], cwd: Path, timeout: int | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def is_git_repo(path: Path) -> bool:
    code, _ = run_capture(["git", "rev-parse", "--is-inside-work-tree"], path)
    return code == 0


def git_changed_files(project_path: Path) -> list[str]:
    code, out = run_capture(["git", "status", "--porcelain"], project_path)
    if code != 0:
        return []
    files: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        files.append(raw.strip('"'))
    return sorted(set(files))


def git_output(project_path: Path, *args: str) -> str:
    code, out = run_capture(["git", *args], project_path)
    if code != 0:
        return ""
    return out.strip()


def git_status_state(project_path: Path) -> dict[str, Any]:
    if not is_git_repo(project_path):
        return {"state": "not-a-git-repo", "porcelain": "", "changed_files": []}
    code, out = run_capture(["git", "status", "--porcelain"], project_path)
    if code != 0:
        return {"state": "unknown", "porcelain": out.strip(), "changed_files": []}
    changed = git_changed_files(project_path)
    return {"state": "dirty" if out.strip() else "clean", "porcelain": out.strip(), "changed_files": changed}


def detect_package_manager(project_path: Path) -> str:
    markers = [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("package-lock.json", "npm"),
        ("package.json", "npm"),
        ("uv.lock", "uv"),
        ("pyproject.toml", "python"),
        ("requirements.txt", "pip"),
        ("go.mod", "go"),
        ("Cargo.toml", "cargo"),
    ]
    for marker, manager in markers:
        if (project_path / marker).exists():
            return manager
    return "unknown"


def detect_test_commands(project_path: Path) -> list[str]:
    commands: list[str] = []
    if (project_path / "pytest.ini").exists() or (project_path / "tests").exists():
        commands.append("python3 -m unittest discover -s tests -p 'test_*.py' -v")
    if (project_path / "package.json").exists():
        commands.append("npm test")
    if (project_path / "go.mod").exists():
        commands.append("go test ./...")
    if (project_path / "Cargo.toml").exists():
        commands.append("cargo test")
    return commands


def create_git_worktree(project_path: Path, run_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Create a detached git worktree inside the run dir.

    The worktree stays in the artifact bundle for inspection. Cleanup is an
    explicit human/runner action, not an automatic destructive step.
    """
    if not is_git_repo(project_path):
        raise RuntimeError("--worktree requires project_path to be a git repository")
    worktree_path = run_dir / "worktree"
    if worktree_path.exists() and any(worktree_path.iterdir()):
        raise RuntimeError(f"worktree path already exists and is not empty: {worktree_path}")
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    base_commit = git_output(project_path, "rev-parse", "HEAD") or "UNKNOWN"
    code, out = run_capture(["git", "worktree", "add", "--detach", str(worktree_path), "HEAD"], project_path)
    if code != 0:
        raise RuntimeError(f"git worktree add failed:\n{out}")
    return worktree_path.resolve(), {
        "enabled": True,
        "path": str(worktree_path.resolve()),
        "base_commit": base_commit,
        "cleanup_command": f"git -C {project_path} worktree remove {worktree_path.resolve()}",
    }


def write_git_diff(project_path: Path, diff_path: Path) -> bool:
    if not is_git_repo(project_path):
        diff_path.write_text("NO_GIT_REPO: diff unavailable\n", encoding="utf-8")
        return False

    parts: list[str] = []
    code, out = run_capture(["git", "diff", "--binary"], project_path)
    if code != 0:
        diff_path.write_text(f"GIT_DIFF_FAILED\n{out}\n", encoding="utf-8")
        return False
    if out:
        parts.append(out)

    # `git diff` omits untracked files, but Walter receipts must show the full
    # evidence for every changed file. Render untracked files as /dev/null diffs
    # so a clean-looking diff cannot hide a new file created by Codex.
    code, out = run_capture(["git", "ls-files", "--others", "--exclude-standard"], project_path)
    if code != 0:
        diff_path.write_text(f"GIT_UNTRACKED_LIST_FAILED\n{out}\n", encoding="utf-8")
        return False
    for rel in [line.strip() for line in out.splitlines() if line.strip()]:
        proc = subprocess.run(
            ["git", "diff", "--no-index", "--binary", "--", "/dev/null", rel],
            cwd=str(project_path),
            text=True,
            capture_output=True,
            check=False,
        )
        # git diff --no-index returns 1 when a diff is present; that is success.
        if proc.returncode not in (0, 1):
            diff_path.write_text(f"GIT_UNTRACKED_DIFF_FAILED {rel}\n{proc.stdout}{proc.stderr}\n", encoding="utf-8")
            return False
        if proc.stdout or proc.stderr:
            parts.append(proc.stdout + proc.stderr)

    diff_path.write_text("\n".join(part.rstrip("\n") for part in parts if part) + "\n" if parts else "NO_DIFF\n", encoding="utf-8")
    return True


SKIP_SNAPSHOT_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


def file_fingerprint(path: Path) -> str:
    stat = path.stat()
    if stat.st_size > 2_000_000:
        return f"large:{stat.st_size}:{stat.st_mtime_ns}"
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def file_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_SNAPSHOT_DIRS]
        current_path = Path(current)
        for name in files:
            path = current_path / name
            try:
                rel = path.relative_to(root).as_posix()
                snapshot[rel] = file_fingerprint(path)
            except OSError:
                continue
    return snapshot


def snapshot_bases(project_path: Path, patterns: list[str]) -> list[Path]:
    bases: list[Path] = []
    for pattern in patterns:
        clean = pattern.replace(os.sep, "/")
        prefix = re.split(r"[*?[]", clean, maxsplit=1)[0].rstrip("/")
        base = (project_path / prefix).resolve() if prefix else project_path
        try:
            base.relative_to(project_path)
        except ValueError:
            continue
        if base.exists():
            bases.append(base)
    return sorted(set(bases))


def scoped_file_snapshot(project_path: Path, patterns: list[str]) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for base in snapshot_bases(project_path, patterns):
        if base.is_file():
            try:
                snapshot[base.relative_to(project_path).as_posix()] = file_fingerprint(base)
            except OSError:
                continue
            continue
        for rel, fingerprint in file_snapshot(base).items():
            snapshot[(base / rel).relative_to(project_path).as_posix()] = fingerprint
    return snapshot


def snapshot_changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changed = set(before) ^ set(after)
    for rel, fingerprint in before.items():
        if rel in after and after[rel] != fingerprint:
            changed.add(rel)
    return sorted(changed)


def path_matches_any(rel_path: str, patterns: list[str]) -> bool:
    rel = rel_path.replace(os.sep, "/")
    for pattern in patterns:
        pat = pattern.strip().replace(os.sep, "/")
        if not pat:
            continue
        if fnmatch.fnmatch(rel, pat) or rel == pat.rstrip("/") or rel.startswith(pat.rstrip("/") + "/"):
            return True
    return False


SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,}"
)


def secret_scan(paths: list[Path]) -> dict[str, Any]:
    hits: list[str] = []
    for path in paths:
        if not path.exists() or path.is_dir() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scan_text = text
        if path.name == "codex.log":
            # Codex transcripts include large source-code excerpts. Do not treat
            # indented fixture strings as leaked secrets; actual commands/output
            # still remain visible at column 0 and are scanned.
            scan_text = "\n".join(
                line for line in text.splitlines()
                if not line.startswith((" ", "\t")) and "NOT_A_REAL_SECRET" not in line
            )
        if SECRET_RE.search(scan_text):
            hits.append(str(path))
    return {"status": "FAIL" if hits else "PASS", "hits": hits}


ABS_PATH_RE = re.compile(r"(?:/Users|/home)/[^\s`\'\"<>]+")


def outside_read_scan(log_text: str, allowed_roots: list[Path]) -> dict[str, Any]:
    """Detect Codex transcript evidence of reads outside the run/project boundary.

    This is deliberately log-based: macOS/Codex CLI sandboxing does not give the
    runner a reliable read syscall audit trail. It still catches the common bad
    case where Codex shells out to read external skills, private roots, or legacy
    sources and prints the command/path in codex.log.
    """
    allowed = [root.expanduser().resolve() for root in allowed_roots]
    hits: list[str] = []
    for line in log_text.splitlines():
        # Codex logs include the full prompt and often source-code excerpts. Only
        # scan transcript command/output lines, not indented code quoted from files.
        if line.startswith((" ", "\t")):
            continue
        for raw in ABS_PATH_RE.findall(line):
            path = Path(raw.rstrip(".,);]")).expanduser()
            try:
                resolved = path.resolve(strict=False)
            except OSError:
                resolved = path
            if any(root in [resolved, *resolved.parents] for root in allowed):
                continue
            if any(str(resolved).startswith(root) for root in DEFAULT_FORBIDDEN_READ_ROOTS):
                hits.append(str(resolved))
                continue
            hits.append(str(resolved))
    return {"status": "FAIL" if hits else "PASS", "hits": sorted(set(hits))}


def render_report(run_dir: Path, receipt: dict[str, Any]) -> str:
    verification = receipt.get("verification", {}) if isinstance(receipt.get("verification"), dict) else {}
    changes = receipt.get("changes", {}) if isinstance(receipt.get("changes"), dict) else {}
    return "\n".join(
        [
            f"# Walter run report — {receipt.get('task_id')}",
            "",
            f"Status: {receipt.get('status')}",
            f"Project: {receipt.get('project_path')}",
            f"Execution path: {receipt.get('execution_path', receipt.get('project_path'))}",
            f"Run dir: {run_dir}",
            f"Report generated: {receipt.get('finished_at')}",
            "",
            "## Codex",
            f"- command: `{receipt.get('codex', {}).get('command')}`",
            f"- exit_code: {receipt.get('codex', {}).get('exit_code')}",
            "",
            "## Changes",
            f"- changed_files: {len(changes.get('changed_files', []))}",
            f"- outside_allowed_paths: {len(changes.get('outside_allowed_paths', []))}",
            "",
            "## Verification",
            f"- runner_verified_not_codex_claim: {verification.get('runner_verified_not_codex_claim')}",
            f"- verification_commands_ok: {verification.get('verification_commands_ok')}",
            f"- secret_scan: {verification.get('secret_scan')}",
            f"- outside_project_read_scan: {verification.get('outside_project_read_scan')}",
            "",
            "Artifacts: input.json, policy.yaml, prompt.md, codex.log, diff.patch, verify.log, receipt.json.",
            "",
        ]
    )


def run_validator(kind: str, path: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), kind, str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def ensure_inside_runs(run_dir: Path) -> None:
    resolved = run_dir.resolve()
    allowed = (WALTER_ROOT / "runs").resolve()
    if allowed not in [resolved, *resolved.parents]:
        raise SystemExit(f"REFUSE: run dir must be under {allowed}")


def cmd_init(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    ensure_inside_runs(run_dir)
    run_dir.mkdir(parents=True, exist_ok=args.exist_ok)

    input_data = load_json(TEMPLATES / "runner-input.example.json")
    input_data["task_id"] = run_dir.name
    input_data["scenario_class"] = args.scenario
    input_data["project_path"] = args.project_path
    input_data["goal"] = args.goal
    input_data["report_path"] = str(run_dir / "report.md")
    if args.allowed_path:
        input_data["allowed_paths"] = args.allowed_path
    if args.forbidden_path:
        input_data["forbidden_paths"] = args.forbidden_path
    if args.verification_command:
        input_data["verification_commands"] = args.verification_command
    if args.acceptance_check:
        input_data["acceptance_checks"] = args.acceptance_check
    write_json(run_dir / "input.json", input_data)

    shutil.copyfile(TEMPLATES / "runner-policy.template.yaml", run_dir / "policy.yaml")

    prompt_template = PROMPT_TEMPLATES[args.scenario if args.scenario in PROMPT_TEMPLATES else "implementation"]
    prompt = prompt_template.read_text(encoding="utf-8")
    replacements = {
        "{{goal}}": input_data["goal"],
        "{{project_path}}": input_data["project_path"],
        "{{allowed_paths}}": "\n".join(f"- {x}" for x in input_data["allowed_paths"]),
        "{{forbidden_paths}}": "\n".join(f"- {x}" for x in input_data["forbidden_paths"]),
        "{{side_effect_policy}}": input_data["side_effect_policy"],
        "{{acceptance_checks}}": "\n".join(f"- {x}" for x in input_data["acceptance_checks"]),
        "{{report_path}}": str(run_dir / "report.md"),
    }
    for old, new in replacements.items():
        prompt = prompt.replace(old, new)
    prompt += (
        "\n## Read boundary\n\n"
        f"Do not read outside this project path: `{input_data['project_path']}`.\n"
        f"Do not read outside this Walter run bundle: `{run_dir}`.\n"
        "Forbidden read roots include private roots, credential stores, and unrelated project roots unless the input contract explicitly approves them.\n"
        "If external context seems necessary, stop and return `NEEDS_APPROVAL` instead of reading it.\n"
    )
    (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")

    for name in ["codex.log", "diff.patch", "verify.log"]:
        (run_dir / name).touch()

    report = f"# Walter run report — {run_dir.name}\n\nStatus: initialized\n\nReceipt not created yet.\n"
    (run_dir / "report.md").write_text(report, encoding="utf-8")

    print(f"INIT {run_dir}")
    return cmd_validate(argparse.Namespace(run_dir=str(run_dir), require_receipt=False))


def cmd_validate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    errors: list[str] = []
    for name in ["input.json", "policy.yaml", "prompt.md", "report.md"]:
        if not (run_dir / name).exists():
            errors.append(f"missing {name}")
    if args.require_receipt and not (run_dir / "receipt.json").exists():
        errors.append("missing receipt.json")

    if (run_dir / "input.json").exists():
        code, out = run_validator("input", run_dir / "input.json")
        print(out)
        if code != 0:
            errors.append("input validation failed")
    if (run_dir / "receipt.json").exists():
        code, out = run_validator("receipt", run_dir / "receipt.json")
        print(out)
        if code != 0:
            errors.append("receipt validation failed")

    if errors:
        print("VALIDATE FAIL")
        for err in errors:
            print(f"- {err}")
        return 1
    print("VALIDATE PASS")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    for name in REQUIRED_BUNDLE:
        path = run_dir / name
        if not path.exists():
            errors.append(f"missing {name}")
        elif name not in {"codex.log", "diff.patch", "verify.log"} and path.stat().st_size == 0:
            errors.append(f"empty {name}")
        elif name in {"codex.log", "diff.patch", "verify.log"} and path.stat().st_size == 0:
            warnings.append(f"empty {name}")

    validate_code = cmd_validate(argparse.Namespace(run_dir=str(run_dir), require_receipt=True))
    if validate_code != 0:
        errors.append("contract validation failed")

    if errors:
        print("VERIFY FAIL")
        for err in errors:
            print(f"- {err}")
        for warn in warnings:
            print(f"warning: {warn}")
        return 1
    print("VERIFY PASS")
    for warn in warnings:
        print(f"warning: {warn}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    ensure_inside_runs(run_dir)
    if not (run_dir / "input.json").exists():
        if not args.goal or not args.project_path:
            print("RUN FAIL: new run requires --goal and --project-path")
            return 2
        init_args = argparse.Namespace(
            run_dir=str(run_dir),
            goal=args.goal,
            project_path=args.project_path,
            scenario=args.scenario,
            exist_ok=True,
            allowed_path=args.allowed_path,
            forbidden_path=args.forbidden_path,
            verification_command=args.verification_command,
            acceptance_check=args.acceptance_check,
        )
        init_code = cmd_init(init_args)
        if init_code != 0:
            return init_code

    input_data = load_json(run_dir / "input.json")
    project_path = Path(input_data["project_path"]).expanduser().resolve()
    started_at = utc_now()
    preflight: dict[str, Any] = {
        "input_valid": False,
        "project_exists": project_path.exists(),
        "project_path": str(project_path),
        "execution_path": str(project_path),
        "git_repo": False,
        "worktree_requested": args.worktree,
        "worktree": {"enabled": False},
        "codex_available": False,
    }

    validate_code = cmd_validate(argparse.Namespace(run_dir=str(run_dir), require_receipt=False))
    preflight["input_valid"] = validate_code == 0
    if not project_path.exists():
        print(f"RUN FAIL: project path does not exist: {project_path}")
        return 1
    preflight["git_repo"] = is_git_repo(project_path)
    source_git_status = git_status_state(project_path)
    preflight["git_status_before"] = source_git_status["state"]
    preflight["git_status_porcelain_before"] = source_git_status["porcelain"]
    preflight["dirty_files_before"] = source_git_status["changed_files"]
    preflight["base_commit_or_snapshot"] = git_output(project_path, "rev-parse", "HEAD") if preflight["git_repo"] else "filesystem-snapshot"
    preflight["package_manager"] = detect_package_manager(project_path)
    preflight["test_commands_detected"] = detect_test_commands(project_path)
    if args.worktree and preflight["git_repo"] and source_git_status["state"] == "dirty":
        print("RUN FAIL: source checkout is dirty; commit/stash changes or run without --worktree with explicit risk acceptance")
        return 1

    execution_path = project_path
    worktree_info: dict[str, Any] = {"enabled": False}
    if args.worktree:
        try:
            execution_path, worktree_info = create_git_worktree(project_path, run_dir)
        except RuntimeError as exc:
            print(f"RUN FAIL: {exc}")
            return 1
        preflight["execution_path"] = str(execution_path)
        preflight["worktree"] = worktree_info

    codex_bin = shutil.which(args.codex_command) if args.codex_command == "codex" else args.codex_command
    preflight["codex_available"] = bool(codex_bin) or args.skip_codex
    if not args.skip_codex and not preflight["codex_available"]:
        print("RUN FAIL: codex command not found")
        return 1

    codex_log = run_dir / "codex.log"
    codex_log.write_text("", encoding="utf-8")
    prompt_path = run_dir / "prompt.md"
    if args.worktree:
        # The bundle input keeps the original project path for provenance, but
        # Codex must see the detached worktree as the editable project. Otherwise
        # it may follow the absolute original path in the prompt and bypass the
        # safety boundary.
        prompt_path.write_text(prompt_path.read_text(encoding="utf-8").replace(str(project_path), str(execution_path)), encoding="utf-8")
    prompt = prompt_path.read_text(encoding="utf-8")
    allowed_paths = input_data.get("allowed_paths", []) if isinstance(input_data.get("allowed_paths"), list) else []
    forbidden_paths = input_data.get("forbidden_paths", []) if isinstance(input_data.get("forbidden_paths"), list) else []
    execution_git_repo = is_git_repo(execution_path)
    before_snapshot = {} if execution_git_repo else scoped_file_snapshot(execution_path, allowed_paths)
    codex_cmd = [
        args.codex_command,
        "exec",
        "--skip-git-repo-check",
        "--full-auto",
        "-m",
        args.model,
        "-c",
        f"model_reasoning_effort={args.reasoning_effort}",
        prompt,
    ]
    codex_exit = 0
    codex_timed_out = False
    if args.skip_codex:
        append_log(codex_log, "SKIPPED_BY_RUNNER --skip-codex")
    else:
        env = os.environ.copy()
        codex_home = Path(args.codex_home).expanduser().resolve() if args.codex_home else Path.home()
        env["HOME"] = str(codex_home)
        preflight["codex_home"] = str(codex_home)
        preflight["pty_requested"] = bool(args.pty)
        preflight["pty_used"] = False
        try:
            proc = subprocess.run(
                codex_cmd,
                cwd=str(execution_path),
                env=env,
                text=True,
                capture_output=True,
                timeout=args.timeout,
                check=False,
            )
            codex_exit = proc.returncode
            append_log(codex_log, proc.stdout + proc.stderr)
        except subprocess.TimeoutExpired as exc:
            codex_timed_out = True
            codex_exit = 124
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            append_log(codex_log, stdout + stderr)
            append_log(codex_log, f"CODEX_TIMEOUT after {args.timeout}s")

    if execution_git_repo:
        changed_files = git_changed_files(execution_path)
        change_detection = "git_status_worktree" if args.worktree else "git_status"
    else:
        changed_files = snapshot_changed_files(before_snapshot, scoped_file_snapshot(execution_path, allowed_paths))
        change_detection = "filesystem_snapshot_allowed_scope"
    diff_ok = write_git_diff(execution_path, run_dir / "diff.patch")
    if not execution_git_repo:
        append_log(run_dir / "diff.patch", "\nSnapshot scope: allowed paths only (non-git project)\nSnapshot changed files:\n" + "\n".join(changed_files))
    outside_allowed = [p for p in changed_files if not path_matches_any(p, allowed_paths)]
    forbidden_changed = [p for p in changed_files if path_matches_any(p, forbidden_paths)]

    verify_log = run_dir / "verify.log"
    verify_log.write_text("", encoding="utf-8")
    verification_results: list[dict[str, Any]] = []
    verification_ok = True
    commands = input_data.get("verification_commands", [])
    if not isinstance(commands, list):
        commands = []
    if not commands:
        verification_ok = False
        append_log(verify_log, "NO_VERIFICATION_COMMANDS")
    for command in commands:
        if not isinstance(command, str) or not command.strip():
            continue
        append_log(verify_log, f"$ {command}")
        timed_out = False
        try:
            proc = subprocess.run(
                command,
                cwd=str(execution_path),
                shell=True,
                text=True,
                capture_output=True,
                timeout=args.verification_timeout,
                check=False,
            )
            exit_code = proc.returncode
            append_log(verify_log, proc.stdout + proc.stderr)
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            append_log(verify_log, stdout + stderr)
            append_log(verify_log, f"VERIFICATION_TIMEOUT after {args.verification_timeout}s")
        verification_results.append({"command": command, "exit_code": exit_code, "timed_out": timed_out})
        if exit_code != 0:
            verification_ok = False

    scan_paths = [run_dir / name for name in REQUIRED_BUNDLE if (run_dir / name).exists()]
    for rel in changed_files:
        candidate = execution_path / rel
        if candidate.exists() and candidate.is_file():
            scan_paths.append(candidate)
    scan = secret_scan(scan_paths)
    read_scan = outside_read_scan(
        codex_log.read_text(encoding="utf-8", errors="replace"),
        [execution_path, run_dir],
    )

    status = "PASS" if execution_git_repo else "PASS_WITH_RISKS"
    if codex_exit != 0:
        status = "FAILED"
    if not verification_ok:
        status = "FAIL_VERIFICATION"
    if codex_timed_out:
        status = "FAILED_TIMEOUT"
    if outside_allowed or forbidden_changed:
        status = "OUT_OF_SCOPE_CHANGE"
    if scan["status"] != "PASS":
        status = "NEEDS_APPROVAL"
    if read_scan["status"] != "PASS":
        status = "NEEDS_APPROVAL"

    finished_at = utc_now()
    receipt = {
        "status": status,
        "task_id": input_data.get("task_id", run_dir.name),
        "project_path": str(project_path),
        "execution_path": str(execution_path),
        "started_at": started_at,
        "finished_at": finished_at,
        "preflight": preflight,
        "codex": {
            "command": f"{args.codex_command} exec --skip-git-repo-check --full-auto -m {args.model} -c model_reasoning_effort={args.reasoning_effort} < prompt.md" if not args.skip_codex else "SKIPPED_BY_RUNNER --skip-codex",
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "prompt_path": str(run_dir / "prompt.md"),
            "exit_code": codex_exit,
            "timed_out": codex_timed_out,
            "timeout_seconds": args.timeout,
            "log_path": str(codex_log),
        },
        "changes": {
            "change_detection": change_detection,
            "diff_available": diff_ok,
            "diff_path": str(run_dir / "diff.patch"),
            "changed_files": changed_files,
            "outside_allowed_paths": outside_allowed,
            "forbidden_changed_paths": forbidden_changed,
        },
        "verification": {
            "runner_verified_not_codex_claim": True,
            "diff_captured": diff_ok,
            "diff_review_required": bool(changed_files),
            "diff_reviewed": False,
            "verification_commands_ok": verification_ok,
            "verification_results": verification_results,
            "commands": verification_results,
            "verification_timeout_seconds": args.verification_timeout,
            "secret_scan": scan["status"],
            "secret_scan_hits": scan["hits"],
            "outside_project_read_scan": read_scan["status"],
            "outside_project_read_hits": read_scan["hits"],
        },
        "rollback": {
            "possible": execution_git_repo,
            "method": "git worktree discard" if args.worktree else ("git checkout/reset" if execution_git_repo else "manual from snapshot/report"),
            "command": worktree_info.get("cleanup_command", f"git -C {execution_path} checkout -- . && git -C {execution_path} clean -fd") if execution_git_repo else "Review snapshot section in diff.patch; restore changed files manually.",
            "instructions": "Review diff.patch first. In worktree mode, original project checkout is untouched; remove the worktree only after extracting/applying the approved diff. Do not trust Codex self-report as rollback proof.",
        },
        "report_path": str(run_dir / "report.md"),
    }
    write_json(run_dir / "receipt.json", receipt)
    (run_dir / "report.md").write_text(render_report(run_dir, receipt), encoding="utf-8")

    verify_code = cmd_verify(argparse.Namespace(run_dir=str(run_dir)))
    print(f"RUN {status} {run_dir}")
    return 0 if status in {"PASS", "PASS_WITH_RISKS"} and verify_code == 0 else 1


def cmd_summarize(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    receipt_path = run_dir / "receipt.json"
    if not receipt_path.exists():
        print(f"NO_RECEIPT {receipt_path}")
        return 1
    data = load_json(receipt_path)
    print(f"Status: {data.get('status')}")
    print(f"Task: {data.get('task_id')}")
    print(f"Project: {data.get('project_path')}")
    print(f"Execution path: {data.get('execution_path', data.get('project_path'))}")
    print(f"Report: {data.get('report_path')}")
    changes = data.get("changes", {}) if isinstance(data.get("changes"), dict) else {}
    print(f"Changed files: {len(changes.get('changed_files', []))}")
    print(f"Outside allowed paths: {len(changes.get('outside_allowed_paths', []))}")
    verification = data.get("verification", {}) if isinstance(data.get("verification"), dict) else {}
    print(f"Runner verified: {verification.get('runner_verified_not_codex_claim')}")
    print(f"Secret scan: {verification.get('secret_scan')}")
    print(f"Outside project read scan: {verification.get('outside_project_read_scan')}")
    rollback = data.get("rollback", {}) if isinstance(data.get("rollback"), dict) else {}
    print(f"Rollback possible: {rollback.get('possible')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Walter runner helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="create a runner bundle")
    p_init.add_argument("run_dir")
    p_init.add_argument("--goal", required=True)
    p_init.add_argument("--project-path", required=True)
    p_init.add_argument("--scenario", choices=["implementation", "repair", "verification"], default="implementation")
    p_init.add_argument("--allowed-path", action="append", help="allowed changed path/glob; repeatable")
    p_init.add_argument("--forbidden-path", action="append", help="forbidden changed path/glob; repeatable")
    p_init.add_argument("--verification-command", action="append", help="verification command to run from project path; repeatable")
    p_init.add_argument("--acceptance-check", action="append", help="acceptance check text; repeatable")
    p_init.add_argument("--exist-ok", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="create if needed, execute Codex, verify, and write receipt")
    p_run.add_argument("run_dir")
    p_run.add_argument("--goal")
    p_run.add_argument("--project-path")
    p_run.add_argument("--scenario", choices=["implementation", "repair", "verification"], default="implementation")
    p_run.add_argument("--allowed-path", action="append", help="allowed changed path/glob; repeatable")
    p_run.add_argument("--forbidden-path", action="append", help="forbidden changed path/glob; repeatable")
    p_run.add_argument("--verification-command", action="append", help="verification command to run from project path; repeatable")
    p_run.add_argument("--acceptance-check", action="append", help="acceptance check text; repeatable")
    p_run.add_argument("--model", default="gpt-5.5")
    p_run.add_argument("--reasoning-effort", default="xhigh")
    p_run.add_argument("--codex-command", default="codex")
    p_run.add_argument("--codex-home", help="HOME directory for Codex CLI auth/config; defaults to current process HOME")
    p_run.add_argument("--pty", action="store_true", help="record PTY intent in preflight; execution is still non-PTY subprocess mode")
    p_run.add_argument("--timeout", type=int, default=3600, help="Codex execution timeout in seconds")
    p_run.add_argument("--verification-timeout", type=int, default=600, help="timeout per verification command in seconds")
    p_run.add_argument("--worktree", action="store_true", help="run Codex in a detached git worktree under the run dir")
    p_run.add_argument("--skip-codex", action="store_true", help="test runner mechanics without invoking Codex")
    p_run.set_defaults(func=cmd_run)

    p_validate = sub.add_parser("validate", help="validate input/receipt contracts")
    p_validate.add_argument("run_dir")
    p_validate.add_argument("--require-receipt", action="store_true")
    p_validate.set_defaults(func=cmd_validate)

    p_verify = sub.add_parser("verify", help="verify required bundle shape")
    p_verify.add_argument("run_dir")
    p_verify.set_defaults(func=cmd_verify)

    p_summary = sub.add_parser("summarize", help="print receipt summary")
    p_summary.add_argument("run_dir")
    p_summary.set_defaults(func=cmd_summarize)
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
