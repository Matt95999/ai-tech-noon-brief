from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from scripts import run_profile
from scripts.run_profile import build_degraded_report


class RunProfileTests(unittest.TestCase):
    def test_frontier_degraded_report_preserves_required_sections(self) -> None:
        config = {"slug": "ai-frontier-daily", "topic_name": "AI Frontier Daily"}
        report = build_degraded_report(datetime(2026, 3, 28, 12, 0), config, "quota exceeded")
        self.assertIn("## Executive Summary", report)
        self.assertIn("## Source Log", report)
        self.assertIn("Jensen Huang / NVIDIA", report)

    def test_us_iran_degraded_report_preserves_macro_section(self) -> None:
        config = {"slug": "us-iran-conflict-daily", "topic_name": "美伊冲突每日简报"}
        report = build_degraded_report(datetime(2026, 4, 6, 12, 0), config, "invalid key")
        self.assertIn("## Executive Summary", report)
        self.assertIn("## Latest Developments", report)
        self.assertIn("## Financial / Macro Pulse", report)
        self.assertIn("## Source Log", report)

    def test_advanced_packaging_degraded_report_preserves_required_sections(self) -> None:
        config = {"slug": "advanced-packaging-daily", "topic_name": "集成电路先进封装每日简报"}
        report = build_degraded_report(datetime(2026, 4, 19, 12, 0), config, "invalid key")
        self.assertIn("## Latest Developments", report)
        self.assertIn("## Global Leader Watch", report)
        self.assertIn("## China Watch", report)
        self.assertIn("## Supply Chain Radar", report)
        self.assertNotIn("模型发布", report)

    def test_main_degrades_when_deepseek_config_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "profiles").mkdir()
            (project_root / "templates").mkdir()
            profile = {
                "slug": "test-deepseek",
                "topic_name": "Test DeepSeek",
                "collectors": ["deepseek_chat", "rss"],
                "template_path": "templates/test_template.md",
                "delivery": {"channels": []},
            }
            (project_root / "profiles" / "test-deepseek.json").write_text(
                json.dumps(profile, ensure_ascii=False),
                encoding="utf-8",
            )
            (project_root / "templates" / "test_template.md").write_text(
                "# Test DeepSeek\n\n日期: {{date}}\n生成时间: {{generated_at}}\n\n## Executive Summary\n- placeholder\n\n## Source Log\n- placeholder\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(run_profile, "collect_deepseek_report", side_effect=ValueError("invalid key")),
                mock.patch.object(run_profile, "generate_review_note", return_value=project_root / "reviews" / "ok.md"),
                mock.patch("sys.argv", ["run_profile.py", "--project-root", str(project_root), "--profile", "test-deepseek"]),
            ):
                exit_code = run_profile.main()

            self.assertEqual(exit_code, 0)
            generated_report = next((project_root / "reports").glob("*.md"))
            content = generated_report.read_text(encoding="utf-8")
            self.assertIn("## Executive Summary", content)
            self.assertIn("invalid key", content)
            metadata = json.loads(next((project_root / "artifacts").glob("*/run_metadata.json")).read_text(encoding="utf-8"))
            self.assertTrue(metadata["degraded"])
            self.assertEqual(metadata["mode"], "degraded-deepseek-error")


if __name__ == "__main__":
    unittest.main()
