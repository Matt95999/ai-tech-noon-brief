from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from collectors.rss import filter_rss_items


class RssFilteringTests(unittest.TestCase):
    def test_filter_rss_items_respects_source_and_impact_policy(self) -> None:
        config = {
            "source_policy": {
                "primary_publishers": ["OpenAI"],
                "secondary_publishers": ["Reuters"],
                "require_primary_source": False,
            },
            "impact_policy": {
                "keywords": ["launch", "funding"],
                "max_candidates": 8,
            },
        }
        now = datetime(2026, 4, 6, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        items = [
            {
                "title": "OpenAI launch a new reasoning model",
                "source": "OpenAI",
                "company": "OpenAI",
                "published_at": now,
                "source_tier": "primary",
                "impact_matches": ["launch"],
            },
            {
                "title": "Reuters reports major AI funding round",
                "source": "Reuters",
                "company": "",
                "published_at": now,
                "source_tier": "secondary",
                "impact_matches": ["funding"],
            },
            {
                "title": "Minor blog post without catalyst",
                "source": "Unknown Blog",
                "company": "",
                "published_at": now,
                "source_tier": "unclassified",
                "impact_matches": [],
            },
        ]

        filtered = filter_rss_items(items, config)

        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0]["source_tier"], "primary")
        self.assertTrue(all(item["high_confidence"] for item in filtered))


if __name__ == "__main__":
    unittest.main()
