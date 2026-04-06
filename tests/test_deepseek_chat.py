from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from collectors import deepseek_chat
from scripts.brief_utils import BriefGenerationError


class DeepSeekCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 4, 6, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.config = {
            "topic_name": "AI 发展进程每日晚报",
            "lookback_hours": 24,
            "focus_companies": ["OpenAI", "DeepSeek"],
            "source_policy": {
                "primary_publishers": ["OpenAI"],
                "secondary_publishers": ["Reuters"],
                "require_primary_source": False,
            },
            "impact_policy": {
                "keywords": ["launch", "funding"],
                "max_candidates": 8,
                "min_high_confidence_items": 2,
            },
            "slug": "ai-evening-brief",
        }
        self.template = "# AI 发展进程每日晚报\n\n## Executive Summary\n\n## Source Log\n"
        self.items = [
            {
                "title": "OpenAI launch a new reasoning model",
                "source": "OpenAI",
                "company": "OpenAI",
                "published_at": self.now,
                "link": "https://example.com/openai",
                "query": "OpenAI",
                "source_tier": "primary",
                "impact_matches": ["launch"],
                "high_confidence": True,
            },
            {
                "title": "Reuters reports major AI funding round",
                "source": "Reuters",
                "company": "",
                "published_at": self.now,
                "link": "https://example.com/reuters",
                "query": "AI funding",
                "source_tier": "secondary",
                "impact_matches": ["funding"],
                "high_confidence": True,
            },
        ]

    def test_extract_choice_text_supports_content_arrays(self) -> None:
        response = {"choices": [{"message": {"content": [{"text": "line 1"}, {"text": "line 2"}]}}]}
        self.assertEqual(deepseek_chat.extract_choice_text(response), "line 1\nline 2")

    def test_collect_deepseek_report_returns_low_signal_when_candidates_too_few(self) -> None:
        with mock.patch.object(deepseek_chat, "collect_rss_items", return_value=self.items[:1]):
            result = deepseek_chat.collect_deepseek_report(self.now, self.config, self.template, "deepseek-chat")
        self.assertEqual(result["mode"], "low-signal-filtered-rss")
        self.assertTrue(result["degraded"])

    def test_collect_deepseek_report_raises_on_empty_model_output(self) -> None:
        old_env = {key: os.environ.get(key) for key in ("DEEPSEEK_API_URL", "DEEPSEEK_API_KEY")}
        os.environ["DEEPSEEK_API_URL"] = "https://example.com/chat/completions"
        os.environ["DEEPSEEK_API_KEY"] = "test-key"
        try:
            with mock.patch.object(deepseek_chat, "collect_rss_items", return_value=self.items):
                with mock.patch.object(deepseek_chat, "request_deepseek", return_value={"choices": []}):
                    with self.assertRaises(BriefGenerationError):
                        deepseek_chat.collect_deepseek_report(self.now, self.config, self.template, "deepseek-chat")
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
