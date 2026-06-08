# Walter Codex Runner

A guarded runner for OpenAI Codex CLI.

It turns a Codex run from “the agent said it is done” into an auditable evidence bundle:

```text
preflight -> bounded Codex run -> logs/diff -> verification -> receipt -> safety gate -> score -> optional gated apply
```

## What it does

- runs Codex in a scoped git worktree by default;
- writes an evidence bundle: `input.json`, `policy.yaml`, `prompt.md`, `codex.log`, `diff.patch`, `verify.log`, `receipt.json`, `report.md`;
- validates receipts;
- rejects Codex self-report without independent evidence;
- scans artifacts for secret-looking output;
- scans Codex logs for suspicious outside-project reads;
- scores evidence quality from 0 to 100;
- applies diffs only through a dry-run-first gate.

## What it does not do

- no production deploys;
- no account posting/sending;
- no secrets handling;
- no payments/billing;
- no auto-commit;
- no destructive cleanup without explicit run id and confirmation.

## Requirements

- Python 3.11+
- `git`
- Codex CLI for real runs: `codex`

The test suite uses only the Python standard library and a fake Codex fixture.

## Quick start

Run tests:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s workspace-repo/tests -v
```

Preview a guarded run without invoking Codex:

```bash
scripts/walter run-safe \
  --goal 'Do a bounded change.' \
  --project-path /path/to/git/project \
  --allowed-path 'src/**' \
  --allowed-path 'tests/**' \
  --verification-command 'python3 -m unittest discover -s tests -v' \
  --dry-run --print-command
```

Run for real:

```bash
scripts/walter run-safe \
  --goal 'Do a bounded change.' \
  --project-path /path/to/git/project \
  --allowed-path 'src/**' \
  --allowed-path 'tests/**' \
  --verification-command 'python3 -m unittest discover -s tests -v'
```

Inspect a run:

```bash
scripts/walter list-runs --limit 10
scripts/walter status <run-id-or-run-dir>
scripts/walter score <run-id-or-run-dir>
scripts/walter inspect <run-id-or-run-dir>
scripts/walter hygiene --limit 20
```

Apply gate:

```bash
scripts/walter apply-diff <run-id-or-run-dir>
# If CHECK_PASS and you reviewed diff.patch:
scripts/walter apply-diff <run-id-or-run-dir> --confirm
```

`apply-diff` refuses unless status is `PASS`, the safety gate is `PASS`, risk is clean, the target is a git repo, and the target checkout is clean. It never commits.

## Evidence score

`score` prints a compact evidence grade:

```text
WALTER_SCORE
score: 100
grade: A
status: PASS
gate: PASS
risk: clean
```

A low score means the run should not be applied. Common reasons: missing receipt, failed verification, out-of-scope change, secret scan hit, outside-read hit, missing report, or failed gate.

## Repository hygiene

`runs/` is ignored except for `.gitkeep`. Do not commit real run logs, receipts, prompts, worktrees, credentials, or local cache files.

Generated cache files are ignored:

```text
__pycache__/
*.py[cod]
.DS_Store
```

## Public-safety note

This repository contains sanitized runner code, tests, templates, and a toy workspace. It should not contain real run logs, private prompts, local absolute paths, credentials, account data, or internal operational reports.
