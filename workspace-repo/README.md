# Walter workspace repo

Disposable git-backed sandbox for Walter runner proof runs.

This repo is intentionally small. It exists so Walter can execute Codex in worktree mode and produce clean receipts with diff and rollback evidence.

## Evidence toolkit

The stdlib-only evidence helpers audit synthetic or runner-produced `receipt.json`
bundles without reading run logs.

```python
from walter_workspace.evidence_report import render_markdown_report
from walter_workspace.run_history import scan_run_history, summarize_run_history

runs = scan_run_history("path/to/history")
summary = summarize_run_history(runs)
markdown = render_markdown_report(summary)
```

Audit output uses booleans, counts, and fixed reject reason codes. Missing
top-level `risks` is accepted for otherwise valid Walter receipts.
