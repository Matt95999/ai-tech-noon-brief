from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_profile import load_profile, resolve_default_profile


class ProfileLoadingTests(unittest.TestCase):
    def test_load_default_profile(self) -> None:
        project_root = Path("/Users/chrome/ai-tech-noon-brief")
        profile_path, config = load_profile(project_root, "ai-tech-daily")
        self.assertEqual(profile_path.name, "ai-tech-daily.json")
        self.assertEqual(config["slug"], "ai-tech-daily")
        self.assertIn("rss", config["collectors"])

    def test_load_profile_from_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "custom.json"
            path.write_text('{"slug":"custom","topic_name":"Custom","collectors":["rss"]}', encoding="utf-8")
            project_root = Path("/Users/chrome/ai-tech-noon-brief")
            profile_path, config = load_profile(project_root, "ignored", path)
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
