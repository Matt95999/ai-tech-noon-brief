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

from collectors import collect_deepseek_report, collect_openai_report, collect_rss_report
from collectors.deepseek_chat import check_deepseek_config
from collectors.openai_search import check_openai_config
from delivery import send_profile_email
from brief_utils import (
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_MODEL,
    BriefGenerationError,
    apply_template_defaults,
    merge_config,
    read_json,
    write_text,
)
from scripts.brief_utils import BriefGenerationError as ScriptsBriefGenerationError

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

FALLBACK_REPORT_BODY = """
## Dry Run Notes

- dry-run 模式已成功跑通 profile 管线。
- 当前输出基于样例研究底稿，不代表真实市场变化。
- 正式运行后会按 profile collector 拉取真实资料。

## Source Log

- Dry-run sample: https://example.com/sample
"""


def resolve_default_profile() -> str:
    return os.environ.get("BRIEF_PROFILE") or os.environ.get("BRIEF_DEFAULT_PROFILE") or "ai-frontier-daily"


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


def build_degraded_research_notes(now_local: datetime, config: dict, reason: str) -> str:
    window_start = now_local - timedelta(hours=int(config["lookback_hours"]))
    return "\n".join(
        [
            "# Research Notes",
            "## Time Window",
            f"- {window_start.strftime('%Y-%m-%d %H:%M %Z')} 到 {now_local.strftime('%Y-%m-%d %H:%M %Z')}",
            "",
            "## Selection Summary",
            "- 本次模型整理链路未完成，系统已自动切换为降级输出。",
            f"- 原因：{reason}",
            "",
            "## Key Findings",
            f"- {now_local.strftime('%Y-%m-%d')}：无重大新增。为了保证结论可靠性，本轮不扩写未经模型整理的候选。",
            "",
            "## Evidence Table",
            "| Date | Topic | Company | Claim | Why It Matters | Source |",
            "| --- | --- | --- | --- | --- | --- |",
            f"| {now_local.strftime('%Y-%m-%d')} | Automation fallback | - | 模型整理链路未完成，系统自动降级输出 | 保证简报不断档 | artifacts/run_metadata.json |",
            "",
            "## Source Quality Notes",
            "- 本次未完成模型整理，Source Log 仅保留自动化降级说明与运行元数据。",
        ]
    )


def build_structured_degraded_report(now_local: datetime, config: dict, reason: str) -> str:
    date_str = now_local.strftime("%Y-%m-%d")
    generated_at = now_local.strftime("%Y-%m-%d %H:%M %Z")
    slug = config.get("slug")
    if slug == "ai-frontier-daily":
        company_headings = ["Jensen Huang / NVIDIA", "Google", "Anthropic", "DeepSeek"]
    else:
        company_headings = config.get("focus_companies", [])[:4] or ["OpenAI", "Anthropic", "Google", "DeepSeek"]
    topic_name = config.get("topic_name", "AI Brief")
    body = [
        f"# {topic_name}",
        "",
        f"日期: {date_str}",
        f"生成时间: {generated_at}",
        "",
        "## Executive Summary",
        "- 无重大新增。本次模型整理链路未完成，系统已自动切换为降级输出。",
        f"- 原因：{reason}",
        "- 影响：继续按时发送，避免简报断档，但本轮不扩写未核实细节。",
        "",
    ]
    if slug == "ai-frontier-daily":
        body.extend(
            [
                "## Macro / Market Pulse",
                "- 无重大新增。由于模型整理未完成，本次不扩展市场判断。",
                "- 关注点：待链路恢复后补跑，继续观察模型、算力与 Agent 生态变化。",
                "",
            ]
        )
    elif slug == "us-iran-conflict-daily":
        body.extend(
            [
                "## Latest Developments",
                "- 无重大新增。本次模型整理链路未完成，系统未扩写未经核验的战事、外交或能源细节。",
                "- 关注点：待链路恢复后补跑，继续观察停火进展、霍尔木兹通航与制裁变化。",
                "",
                "## Country / Geopolitical Impact",
                "### United States",
                "- 无重大新增。",
                "- 继续跟踪白宫、国防部与国务院的正式表态。",
                "",
                "### Iran",
                "- 无重大新增。",
                "- 继续跟踪伊朗官方表态、军事动作与能源设施风险。",
                "",
                "### Israel / Gulf / Major Powers",
                "- 无重大新增。",
                "- 继续跟踪以色列、海湾国家及中俄欧等主要行为体的政策变化。",
                "",
                "## Financial / Macro Pulse",
                "- 无重大新增。由于模型整理未完成，本次不扩展油价、通胀或央行路径判断。",
                "- 关注点：待链路恢复后补跑，继续观察原油、天然气、黄金、美元与航运保险价格。",
                "",
            ]
        )
    else:
        body.extend(
            [
                "## Major Developments",
                "- 无重大新增。",
                "- 继续观察模型发布、监管政策、资本开支与重大合作是否形成新催化。",
                "",
            ]
        )

    if slug not in {"us-iran-conflict-daily"}:
        body.extend(["## Company Watch"])
        for company in company_headings:
            body.extend(
                [
                    f"### {company}",
                    "- 无重大新增。",
                    "- 继续跟踪官方发布、财报、合作与产品更新。",
                    "",
                ]
            )
    if slug == "ai-frontier-daily":
        body.extend(
            [
                "## GitHub Radar",
                "- 无重大新增。模型整理未完成，未形成高置信仓库更新结论。",
                "- 跟踪重点：待恢复后补抓 Agent、Inference、RAG、Benchmark 与 Multimodal 更新。",
                "",
            ]
        )
    body.extend(
        [
            "## What Matters",
            "- 降级输出优先保证节奏与可靠性，不把低置信候选误写成正式结论。",
            "- 当模型链路恢复后，系统会重新按信源规则和影响力门槛生成完整简报。",
            "",
            "## Source Log",
            "1. Automation fallback",
            "   artifacts/run_metadata.json",
        ]
    )
    return "\n".join(body)


def build_degraded_report(now_local: datetime, config: dict, reason: str) -> str:
    return build_structured_degraded_report(now_local, config, reason)


def resolve_model(args: argparse.Namespace, config: dict) -> str:
    if args.model:
        return args.model
    collectors = config.get("collectors", ["rss"])
    if "deepseek_chat" in collectors:
        return os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_DEEPSEEK_MODEL
    if "openai_search" in collectors:
        return os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL
    return DEFAULT_MODEL


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


def run_deepseek_check(model: str) -> int:
    result = check_deepseek_config(model=model)
    print(f"DeepSeek config OK: {result['api_url']}")
    print(f"Model: {result['model']}")
    print(f"Response: {result['output']}")
    return 0


def run_openai_check(model: str) -> int:
    result = check_openai_config(model=model)
    print(f"OpenAI config OK: {result['api_url']}")
    print(f"Model: {result['model']}")
    print(f"Response: {result['output']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a configured research brief profile.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--profile", default=resolve_default_profile())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--timezone")
    parser.add_argument("--lookback-hours", type=int)
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-delivery", action="store_true")
    parser.add_argument("--check-deepseek", action="store_true")
    parser.add_argument("--check-openai", action="store_true")
    args = parser.parse_args()

    project_root = args.project_root.expanduser().resolve()
    profile_path, config = load_profile(project_root, args.profile, args.config)
    config = merge_config(config, timezone=args.timezone, lookback_hours=args.lookback_hours)
    resolved_model = resolve_model(args, config)

    if args.check_deepseek:
        return run_deepseek_check(resolved_model)
    if args.check_openai:
        return run_openai_check(resolved_model)

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
        report_markdown = apply_template_defaults(template_text, now_local).rstrip()
        report_markdown = f"{report_markdown}\n\n{FALLBACK_REPORT_BODY.strip()}\n"
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
        if "deepseek_chat" in collectors:
            try:
                result = collect_deepseek_report(now_local, config, template_text, resolved_model)
            except (BriefGenerationError, ScriptsBriefGenerationError, ValueError) as exc:
                reason = str(exc).replace("\n", " ").strip()
                result = {
                    "mode": "degraded-deepseek-error",
                    "research_notes": build_degraded_research_notes(now_local, config, reason),
                    "report_markdown": build_degraded_report(now_local, config, reason),
                    "research_response": {"mode": "degraded-deepseek-error", "reason": reason},
                    "final_response": {"mode": "degraded-deepseek-error", "reason": reason},
                    "items_found": 0,
                    "degraded": True,
                }
        elif "openai_search" in collectors and api_key:
            try:
                result = collect_openai_report(now_local, config, template_text, resolved_model, api_key)
            except (BriefGenerationError, ScriptsBriefGenerationError, ValueError) as exc:
                reason = str(exc).replace("\n", " ").strip()
                result = {
                    "mode": "degraded-openai-error",
                    "research_notes": build_degraded_research_notes(now_local, config, reason),
                    "report_markdown": build_degraded_report(now_local, config, reason),
                    "research_response": {"mode": "degraded-openai-error", "reason": reason},
                    "final_response": {"mode": "degraded-openai-error", "reason": reason},
                    "items_found": 0,
                    "degraded": True,
                }
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
        "model": resolved_model,
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
    try:
        raise SystemExit(main())
    except (ValueError, BriefGenerationError, ScriptsBriefGenerationError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
