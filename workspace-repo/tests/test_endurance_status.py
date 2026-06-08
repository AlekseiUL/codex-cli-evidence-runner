from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from walter_workspace.endurance_status import (
    cleanup_requires_approval,
    duration_band,
    requires_background,
)


class EnduranceStatusTests(unittest.TestCase):
    def test_duration_band_matches_protocol_boundaries(self) -> None:
        cases = [
            (0, "short"),
            (4, "short"),
            (5, "medium"),
            (29, "medium"),
            (30, "long"),
            (120, "long"),
        ]

        for minutes, band in cases:
            with self.subTest(minutes=minutes):
                self.assertEqual(duration_band(minutes), band)

    def test_background_required_for_long_runs(self) -> None:
        self.assertFalse(requires_background(29))
        self.assertTrue(requires_background(30))

    def test_destructive_cleanup_requires_approval(self) -> None:
        actions = [
            "remove",
            "delete",
            "prune",
            "cleanup-worktrees --confirm",
        ]

        for action in actions:
            with self.subTest(action=action):
                self.assertTrue(cleanup_requires_approval(action))

    def test_preview_and_dry_run_do_not_require_approval(self) -> None:
        self.assertFalse(cleanup_requires_approval("preview"))
        self.assertFalse(cleanup_requires_approval("dry-run"))


if __name__ == "__main__":
    unittest.main()
