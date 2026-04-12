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

from collectors.github_search import (
    build_github_report,
    extract_focus_labels,
    extract_readme_brief,
    extract_readme_excerpt,
    select_top_repositories,
)


class GitHubSearchTests(unittest.TestCase):
    def test_extract_readme_excerpt_skips_badges_and_headings(self) -> None:
        readme = """
# Project Title

[![CI](https://img.shields.io/badge/ci-green)](https://example.com)

This repository adds practical Claude Code workflows for daily coding tasks.

## Usage

Run the tool with a terminal-first workflow and ship from GitHub Actions.
"""
        excerpt = extract_readme_excerpt(readme, max_chars=120)
        self.assertIn("practical Claude Code workflows", excerpt)
        self.assertNotIn("shields.io", excerpt)
        self.assertNotIn("Project Title", excerpt)

    def test_extract_readme_brief_keeps_play_points(self) -> None:
        readme = """
# Project Title

This repository adds practical Claude Code workflows for daily coding tasks.

## Features

- Review pull requests with a reusable GitHub Actions workflow.
- Run a terminal-first coding loop before shipping from CI.
"""
        brief = extract_readme_brief(readme, excerpt_max_chars=120, max_points=3)
        self.assertIn("practical Claude Code workflows", brief["excerpt"])
        self.assertTrue(any("GitHub Actions workflow" in point for point in brief["key_points"]))

    def test_extract_focus_labels_uses_profile_focus_map(self) -> None:
        config = {
            "github_focus_map": {
                "通用 Agent": ["hermes agent", "agent harness"],
                "Claude Code": ["claude code"],
            }
        }
        repo = {
            "full_name": "NousResearch/hermes-agent",
            "description": "The agent that grows with you",
            "topics": ["ai-agent", "claude-code", "codex"],
            "matched_query": "\"Hermes Agent\" in:name,description,readme",
            "readme_excerpt": "",
        }
        labels = extract_focus_labels(repo, config)
        self.assertIn("通用 Agent", labels)
        self.assertIn("Claude Code", labels)

    def test_select_top_repositories_diversifies_focus_labels(self) -> None:
        now = datetime(2026, 4, 8, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        config = {
            "github_min_stars": 80,
            "github_max_candidates": 4,
            "github_created_days": 14,
            "github_readme_max_chars": 220,
            "github_focus_map": {
                "通用 Agent": ["hermes agent", "openhands", "agent harness"],
                "Codex": ["codex"],
                "Claude Code": ["claude code"],
            },
        }
        repos = [
            {
                "full_name": "NousResearch/hermes-agent",
                "description": "General agent harness",
                "topics": ["agent", "ai-agent"],
                "matched_query": "hermes agent",
                "readme_excerpt": "General agent harness",
                "stars": 500,
                "watchlisted": False,
                "bucket": "fresh",
                "created_at": datetime(2026, 4, 2, 12, 0, tzinfo=ZoneInfo("UTC")),
                "pushed_at": datetime(2026, 4, 8, 3, 0, tzinfo=ZoneInfo("UTC")),
                "latest_release": None,
            },
            {
                "full_name": "openai/codex",
                "description": "Codex CLI agent",
                "topics": ["agent"],
                "matched_query": "codex",
                "readme_excerpt": "Codex CLI agent",
                "stars": 400,
                "watchlisted": True,
                "bucket": "watch",
                "created_at": datetime(2026, 4, 1, 12, 0, tzinfo=ZoneInfo("UTC")),
                "pushed_at": datetime(2026, 4, 8, 0, 0, tzinfo=ZoneInfo("UTC")),
                "latest_release": None,
            },
            {
                "full_name": "community/claude-workflow",
                "description": "Claude Code workflow templates",
                "topics": ["workflow"],
                "matched_query": "claude code",
                "readme_excerpt": "Claude Code workflow templates",
                "stars": 300,
                "watchlisted": False,
                "bucket": "fresh",
                "created_at": datetime(2026, 4, 3, 12, 0, tzinfo=ZoneInfo("UTC")),
                "pushed_at": datetime(2026, 4, 8, 1, 0, tzinfo=ZoneInfo("UTC")),
                "latest_release": None,
            },
        ]
        selected = select_top_repositories(repos, now, config, enrich=False)
        labels = {label for repo in selected for label in repo.get("focus_labels", [])}
        self.assertIn("通用 Agent", labels)
        self.assertIn("Codex", labels)
        self.assertIn("Claude Code", labels)

    def test_build_github_report_uses_short_section_titles(self) -> None:
        now = datetime(2026, 4, 8, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        config = {"topic_name": "Agent / Codex / Claude Code GitHub 日报", "github_scope_name": "通用 Agent、Codex 生态、Claude Code 生态"}
        repos = [
            {
                "full_name": "openai/codex",
                "description": "Codex CLI agent",
                "readme_excerpt": "Codex CLI for coding tasks in the terminal.",
                "readme_key_points": [
                    "Run the coding loop from the terminal before shipping from CI.",
                    "Use repository prompts and rules to standardize coding tasks.",
                ],
                "focus_labels": ["Codex"],
                "watchlisted": True,
                "bucket": "watch",
                "stars": 400,
                "language": "Python",
                "created_at": datetime(2026, 4, 1, 12, 0, tzinfo=ZoneInfo("UTC")),
                "pushed_at": datetime(2026, 4, 8, 0, 0, tzinfo=ZoneInfo("UTC")),
                "latest_release": None,
                "html_url": "https://github.com/openai/codex",
            }
        ]
        report = build_github_report(now, config, repos)
        self.assertIn("## 结论", report)
        self.assertIn("## 项目", report)
        self.assertIn("## 官方", report)
        self.assertIn("## 动作", report)
        self.assertIn("## 来源", report)
        self.assertNotIn("## Executive Summary", report)
        self.assertIn("- 今日主题：", report)
        self.assertIn("- 整体概况：", report)
        self.assertIn("- 主题：", report)
        self.assertIn("- 它在做什么：", report)
        self.assertIn("- 可玩点 1：", report)
        self.assertIn("- 适合参考：", report)


if __name__ == "__main__":
    unittest.main()
