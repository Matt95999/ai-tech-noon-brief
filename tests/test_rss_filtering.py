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

from collectors.rss import build_source_audit, build_rss_queries, collect_impact_matches, filter_rss_items


class RssFilteringTests(unittest.TestCase):
    def test_build_rss_queries_prefers_profile_specific_queries(self) -> None:
        config = {
            "rss_queries": ["query a", "query b"],
            "focus_companies": ["Ignored"],
            "include_keywords": ["Ignored"],
            "topic_name": "Ignored",
        }
        self.assertEqual(build_rss_queries(config), ["query a", "query b"])

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

    def test_filter_rss_items_keeps_strong_unclassified_candidates(self) -> None:
        config = {
            "source_policy": {
                "primary_publishers": ["TSMC"],
                "secondary_publishers": ["CNBC"],
                "require_primary_source": False,
            },
            "impact_policy": {
                "keywords": ["packaging", "chiplet"],
                "max_candidates": 8,
            },
        }
        now = datetime(2026, 4, 8, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        items = [
            {
                "title": "Intel is in talks with Google and Amazon to power AI chips with new packaging tech",
                "source": "TechSpot",
                "company": "Intel Foundry",
                "published_at": now,
                "source_tier": "unclassified",
                "impact_matches": ["packaging"],
            },
            {
                "title": "Why ASE Technology Holding Co Shares Are Sliding",
                "source": "TipRanks",
                "company": "ASE",
                "published_at": now,
                "source_tier": "unclassified",
                "impact_matches": [],
            },
        ]

        filtered = filter_rss_items(items, config)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["source"], "TechSpot")
        self.assertFalse(filtered[0]["high_confidence"])

    def test_collect_impact_matches_uses_description_context(self) -> None:
        config = {
            "impact_policy": {
                "keywords": ["advanced packaging", "packaging", "HBM"],
            }
        }
        item = {
            "title": "Nvidia snaps up capacity for a key part of AI chipmaking",
            "source": "CNBC",
            "company": "NVIDIA",
            "description": "The article discusses advanced packaging capacity and HBM supply.",
        }

        matches = collect_impact_matches(item, config)

        self.assertEqual(matches, ["advanced packaging", "packaging", "HBM"])

    def test_filter_rss_items_rejects_company_only_matches_when_impact_keywords_exist(self) -> None:
        config = {
            "source_policy": {
                "primary_publishers": ["TSMC"],
                "secondary_publishers": ["CNBC"],
                "require_primary_source": False,
            },
            "impact_policy": {
                "keywords": ["advanced packaging", "packaging", "HBM"],
                "max_candidates": 8,
            },
        }
        now = datetime(2026, 4, 8, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        items = [
            {
                "title": "Asian tech stocks surge as U.S.-Iran cease fire ease Hormuz disruption worries",
                "source": "CNBC",
                "company": "ASE",
                "published_at": now,
                "source_tier": "secondary",
                "impact_matches": [],
            }
        ]

        filtered = filter_rss_items(items, config)

        self.assertEqual(filtered, [])

    def test_source_audit_records_tier_distribution_and_watchlist_items(self) -> None:
        now = datetime(2026, 4, 8, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        raw_items = [
            {
                "title": "TSMC CoWoS capacity update",
                "source": "TSMC",
                "company": "TSMC",
                "published_at": now,
                "source_tier": "primary",
                "impact_matches": ["CoWoS"],
                "high_confidence": True,
            },
            {
                "title": "Intel packaging report",
                "source": "TechSpot",
                "company": "Intel Foundry",
                "published_at": now,
                "source_tier": "unclassified",
                "impact_matches": ["packaging"],
                "high_confidence": False,
            },
        ]
        audit = build_source_audit(
            raw_items,
            raw_items,
            {"fetched_items": 3, "excluded_counts": {"exclude_publisher": 1}},
        )

        self.assertEqual(audit["fetched_items"], 3)
        self.assertEqual(audit["selected_source_tiers"], {"primary": 1, "unclassified": 1})
        self.assertEqual(audit["selected_high_confidence"], 1)
        self.assertEqual(audit["selected_watchlist"], 1)
        self.assertEqual(audit["excluded_counts"], {"exclude_publisher": 1})


if __name__ == "__main__":
    unittest.main()
