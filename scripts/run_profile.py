#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from collectors import collect_openai_report, collect_rss_report
from delivery import send_profile_email
from brief_utils import DEFAULT_MODEL, apply_template_defaults, merge_config, read_json, write_text

FALLBACK_RESEARCH_NOTES = """# Research Notes
## Time Window
- 2026-03-26 12:00 CST 到 2026-03-27 12:00 CST

## Key Findings
- 2026-03-27：这是 dry-run 样例数据，用于验证 profile 管线。

## Evidence Table
| Date | Topic | Claim | Why It Matters | Source |
| --- | --- | --- | --- | --- |
| 2026-03-27 | Sample | Dry-run 使用样例研究底稿 | 用于验证端到端链路 | https://example.com/sample |

## Source Quality Notes
- 这是 dry-run 样例数据，不代表真实新闻结果。
"""

FALLBACK_REPORT = """# {{topic_name}}

日期：{{date}}
生成时间：{{generated_at}}

## 一、执行摘要

- dry-run 模式已成功跑通 profile 管线。
- 当前输出基于样例研究底稿，不代表真实市场变化。

## 二、重点事件

### 1. 行业层面

- 无重大新增。

### 2. 公司层面

- 正式运行后将补入真实来源。

## 三、市场与产业链含义

- 可用于验证模板、报告目录和发送链路。

## 四、值得继续跟踪

- 配置 profile 后的真实主题动态。

## 五、来源清单

- Dry-run sample: https://example.com/sample
"""


def load_profile(project_root: Path, profile_name: str, config_override: Path | None = None) -> tuple[Path, dict]:
    if config_override:
        profile_path = config_override.expanduser().resolve()
    else:
        profile_path = project_root / "profiles" / f"{profile_name}.json"
    config = merge_config(read_json(profile_path))
    config["slug"] = config.get("slug", profile_path.stem)
    return profile_path, config


def cleanup_old_outputs(project_root: Path, retention_days: int, now_local: datetime) -> None:
    cutoff = now_local - timedelta(days=retention_days)
    for top_level in ("artifacts", "reports", "reviews", "summaries"):
        directory = project_root / top_level
        if not directory.exists():
            continue
        for item in directory.iterdir():
            try:
                stem = item.stem if item.is_file() else item.name
                date_value = datetime.strptime(stem[:10], "%Y-%m-%d")
            except ValueError:
                continue
            if date_value < cutoff.replace(tzinfo=None):
                if item.is_dir():
                    for nested in sorted(item.rglob("*"), reverse=True):
                        if nested.is_file():
                            nested.unlink()
                        elif nested.is_dir():
                            nested.rmdir()
                    item.rmdir()
                else:
                    item.unlink()


def generate_review_note(project_root: Path, report_path: Path) -> Path:
    import subprocess

    subprocess.run(
        [
            "python3",
            str(project_root / "scripts" / "generate_review_note.py"),
            "--project-root",
            str(project_root),
            "--report-path",
            str(report_path),
        ],
        check=True,
    )
    return project_root / "reviews" / f"{report_path.stem}-self-review.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a configured research brief profile.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--profile", default=os.environ.get("BRIEF_PROFILE", "ai-tech-daily"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timezone")
    parser.add_argument("--lookback-hours", type=int)
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-delivery", action="store_true")
    args = parser.parse_args()

    project_root = args.project_root.expanduser().resolve()
    profile_path, config = load_profile(project_root, args.profile, args.config)
    config = merge_config(config, timezone=args.timezone, lookback_hours=args.lookback_hours)

    timezone = ZoneInfo(config["timezone"])
    now_local = datetime.now(timezone)
    if args.date:
        now_local = datetime.strptime(args.date, "%Y-%m-%d").replace(
            hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone
        )
    date_str = now_local.strftime("%Y-%m-%d")

    template_path = project_root / config.get("template_path", "templates/ai_tech_brief_template.md")
    template_text = template_path.read_text(encoding="utf-8")
    report_path = project_root / "reports" / f"{date_str}.md"
    artifacts_dir = project_root / "artifacts" / date_str

    if args.dry_run:
        report_markdown = apply_template_defaults(
            FALLBACK_REPORT.replace("{{topic_name}}", config["topic_name"]),
            now_local,
        )
        result = {
            "mode": "dry-run",
            "research_notes": FALLBACK_RESEARCH_NOTES,
            "report_markdown": report_markdown,
            "research_response": {"mode": "dry-run"},
            "final_response": {"mode": "dry-run"},
            "items_found": 1,
            "degraded": False,
        }
    else:
        collectors = config.get("collectors", ["rss"])
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if "openai_search" in collectors and api_key:
            result = collect_openai_report(now_local, config, template_text, args.model, api_key)
        else:
            result = collect_rss_report(now_local, config)

    report_markdown = apply_template_defaults(result["report_markdown"], now_local)
    write_text(report_path, report_markdown.rstrip() + "\n")
    write_text(artifacts_dir / "research_notes.md", result["research_notes"].rstrip() + "\n")
    write_text(
        artifacts_dir / "research_response.json",
        json.dumps(result["research_response"], ensure_ascii=False, indent=2, default=str) + "\n",
    )
    write_text(
        artifacts_dir / "final_response.json",
        json.dumps(result["final_response"], ensure_ascii=False, indent=2, default=str) + "\n",
    )
    metadata = {
        "mode": result["mode"],
        "date": date_str,
        "timezone": config["timezone"],
        "lookback_hours": config["lookback_hours"],
        "topic_name": config["topic_name"],
        "profile": config["slug"],
        "profile_path": str(profile_path),
        "items_found": result["items_found"],
        "degraded": result["degraded"],
    }
    write_text(artifacts_dir / "run_metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    write_text(artifacts_dir / "config_snapshot.json", json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    cleanup_old_outputs(project_root, int(config["retention_days"]), now_local)

    generate_review_note(project_root, report_path)
    if not args.skip_delivery and "email" in config.get("delivery", {}).get("channels", []):
        send_profile_email(report_path, config, dry_run=args.dry_run)

    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
