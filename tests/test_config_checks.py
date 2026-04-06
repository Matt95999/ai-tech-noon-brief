from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts import run_profile


class ConfigChecksTests(unittest.TestCase):
    def test_run_deepseek_check_prints_success(self) -> None:
        with mock.patch.object(run_profile, "check_deepseek_config", return_value={
            "api_url": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-chat",
            "output": "OK",
        }):
            stream = io.StringIO()
            with mock.patch("sys.stdout", stream):
                code = run_profile.run_deepseek_check("deepseek-chat")
        self.assertEqual(code, 0)
        self.assertIn("DeepSeek config OK", stream.getvalue())

    def test_run_openai_check_prints_success(self) -> None:
        with mock.patch.object(run_profile, "check_openai_config", return_value={
            "api_url": "https://api.openai.com/v1/responses",
            "model": "gpt-5.4-mini",
            "output": "OK",
        }):
            stream = io.StringIO()
            with mock.patch("sys.stdout", stream):
                code = run_profile.run_openai_check("gpt-5.4-mini")
        self.assertEqual(code, 0)
        self.assertIn("OpenAI config OK", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
