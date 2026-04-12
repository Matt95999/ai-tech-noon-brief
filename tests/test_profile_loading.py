from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_profile import load_profile, resolve_default_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProfileLoadingTests(unittest.TestCase):
    def test_load_default_profile(self) -> None:
        profile_path, config = load_profile(PROJECT_ROOT, "ai-tech-daily")
        self.assertEqual(profile_path.name, "ai-tech-daily.json")
        self.assertEqual(config["slug"], "ai-tech-daily")
        self.assertIn("rss", config["collectors"])

    def test_load_evening_profile_includes_policy_blocks(self) -> None:
        profile_path, config = load_profile(PROJECT_ROOT, "ai-evening-brief")
        self.assertEqual(profile_path.name, "ai-evening-brief.json")
        self.assertIn("deepseek_chat", config["collectors"])
        self.assertGreaterEqual(config["impact_policy"]["min_high_confidence_items"], 1)
        self.assertTrue(config["source_policy"]["secondary_publishers"])

    def test_load_us_iran_conflict_profile(self) -> None:
        profile_path, config = load_profile(PROJECT_ROOT, "us-iran-conflict-daily")
        self.assertEqual(profile_path.name, "us-iran-conflict-daily.json")
        self.assertEqual(config["topic_name"], "美国-伊朗冲突每日简报")
        self.assertIn("deepseek_chat", config["collectors"])
        self.assertIn("Reuters", config["source_policy"]["secondary_publishers"])
        self.assertGreaterEqual(config["impact_policy"]["min_high_confidence_items"], 1)

    def test_load_agent_codex_claude_github_daily_profile(self) -> None:
        profile_path, config = load_profile(PROJECT_ROOT, "agent-codex-claude-github-daily")
        self.assertEqual(profile_path.name, "agent-codex-claude-github-daily.json")
        self.assertEqual(config["topic_name"], "Agent / Codex / Claude Code GitHub 日报")
        self.assertIn("github_search", config["collectors"])
        self.assertIn("通用 Agent", config["github_focus_map"])

    def test_load_profile_from_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "custom.json"
            path.write_text('{"slug":"custom","topic_name":"Custom","collectors":["rss"]}', encoding="utf-8")
            profile_path, config = load_profile(PROJECT_ROOT, "ignored", path)
            self.assertEqual(profile_path, path.resolve())
            self.assertEqual(config["slug"], "custom")

    def test_resolve_default_profile_prefers_configurable_default(self) -> None:
        import os

        old_profile = os.environ.pop("BRIEF_PROFILE", None)
        old_default = os.environ.get("BRIEF_DEFAULT_PROFILE")
        os.environ["BRIEF_DEFAULT_PROFILE"] = "ai-frontier-daily"
        try:
            self.assertEqual(resolve_default_profile(), "ai-frontier-daily")
        finally:
            if old_profile is not None:
                os.environ["BRIEF_PROFILE"] = old_profile
            if old_default is None:
                os.environ.pop("BRIEF_DEFAULT_PROFILE", None)
            else:
                os.environ["BRIEF_DEFAULT_PROFILE"] = old_default


if __name__ == "__main__":
    unittest.main()
