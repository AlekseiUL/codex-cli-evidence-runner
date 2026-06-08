"""Markdown rendering for Walter evidence summaries."""

from __future__ import annotations


def _yes_no(value: object) -> str:
    return "yes" if value is True else "no"


def render_markdown_report(summary: dict) -> str:
    """Render a compact markdown report from a run history summary."""
    lines = [
        "# Walter Evidence Report",
        "",
        f"- Total runs: {summary.get('total_runs', 0)}",
        f"- Safe runs: {summary.get('safe_runs', 0)}",
        f"- Clean runs: {summary.get('clean_runs', 0)}",
        f"- Unsafe runs: {summary.get('unsafe_runs', 0)}",
        f"- Missing receipts: {summary.get('missing_receipts', 0)}",
        f"- All safe: {_yes_no(summary.get('all_safe'))}",
        f"- All clean: {_yes_no(summary.get('all_clean'))}",
        "",
        "## Reject Reasons",
    ]

    reason_counts = summary.get("reject_reason_counts", {})
    if reason_counts:
        for reason, count in sorted(reason_counts.items()):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"
