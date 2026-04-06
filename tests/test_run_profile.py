from __future__ import annotations

import unittest
from datetime import datetime

from scripts.run_profile import build_degraded_report


class RunProfileTests(unittest.TestCase):
    def test_frontier_degraded_report_preserves_required_sections(self) -> None:
        config = {"slug": "ai-frontier-daily", "topic_name": "AI Frontier Daily"}
        report = build_degraded_report(datetime(2026, 3, 28, 12, 0), config, "quota exceeded")
        self.assertIn("## Executive Summary", report)
        self.assertIn("## Source Log", report)
        self.assertIn("Jensen Huang / NVIDIA", report)


if __name__ == "__main__":
    unittest.main()
