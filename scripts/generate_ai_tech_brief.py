#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import ssl
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus
from urllib import error, request
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from brief_utils import (
    DEFAULT_MODEL,
    OPENAI_API_URL,
    USER_AGENT,
    BriefGenerationError,
    apply_template_defaults,
    extract_output_text,
    merge_config,
    read_json,
    require_env,
    strip_markdown_fence,
    write_text,
)


FALLBACK_RESEARCH_NOTES = """# Research Notes
## Time Window
- 2026-03-26 12:00 CST 到 2026-03-27 12:00 CST

## Key Findings
- 2026-03-27：OpenAI、Anthropic、NVIDIA 相关公开讨论继续聚焦模型能力、企业采用与算力供给，说明市场关注点仍集中在商业化与基础设施匹配。
- 2026-03-27：多家科技公司相关新闻显示，AI 投入仍围绕云、芯片、开发者平台三条主线演进，短期关注财报与新产品节奏。
- 2026-03-27：若当日缺乏高置信新增，正式版应明确写出“无重大新增”，避免信息稀释。

## Evidence Table
| Date | Topic | Claim | Why It Matters | Source |
| --- | --- | --- | --- | --- |
| 2026-03-27 | Sample | Dry-run 使用样例研究底稿 | 用于验证端到端链路 | https://example.com/sample |

## Source Quality Notes
- 这是 dry-run 样例数据，不代表真实新闻结果。
"""

FALLBACK_REPORT = """# AI / 科技行业中午简报

日期：{{date}}
生成时间：{{generated_at}}

## 一、执行摘要

- dry-run 模式已成功跑通“采集 -> 生成 -> 落盘”链路。
- 当前输出基于样例研究底稿，不代表真实市场变化。
- 正式运行时将使用 OpenAI Responses API + web search 拉取过去 24 小时公开动态。

## 二、重点事件

### 1. 行业层面

- 无重大新增，建议继续关注模型发布、云资本开支与先进制程产能动态。

### 2. 公司层面

- OpenAI / Anthropic / NVIDIA 等公司仍是观察重点，正式版将补入真实来源。

## 三、市场与产业链含义

- 短期仍需关注 AI 基础设施投资强度与企业端落地速度是否同步。

## 四、值得继续跟踪

- 重点公司财报、产品发布会、监管政策与重大合作公告。

## 五、来源清单

- Dry-run sample: https://example.com/sample
"""

RSS_USER_AGENT = "Mozilla/5.0 (compatible; AITechNoonBrief/1.0)"


def request_openai(payload: dict, api_key: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        OPENAI_API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=240) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise BriefGenerationError(f"OpenAI API request failed: {exc.code} {details}") from exc
    except error.URLError as exc:
        raise BriefGenerationError(f"OpenAI API request failed: {exc}") from exc


def fetch_text(url: str) -> str:
    req = request.Request(url, headers={"User-Agent": RSS_USER_AGENT}, method="GET")
    try:
        with request.urlopen(req, timeout=60) as response:
            return response.read().decode("utf-8", errors="ignore")
    except error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            insecure_context = ssl._create_unverified_context()
            with request.urlopen(req, timeout=60, context=insecure_context) as response:
                return response.read().decode("utf-8", errors="ignore")
        raise BriefGenerationError(f"Failed to fetch RSS source: {exc}") from exc


def parse_pub_date(value: str, fallback_tz: ZoneInfo) -> datetime | None:
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=fallback_tz)
            return dt.astimezone(fallback_tz)
        except ValueError:
            continue
    return None


def build_rss_queries(config: dict) -> list[str]:
    companies = list(config["focus_companies"])[:6]
    keywords = list(config["include_keywords"])[:4]
    query_pool = companies + keywords
    if not query_pool:
        query_pool = ["AI technology", "semiconductor", "cloud", "developer tools"]
    return query_pool


def collect_rss_items(now_local: datetime, config: dict) -> list[dict]:
    timezone = ZoneInfo(config["timezone"])
    cutoff = now_local - timedelta(hours=int(config["lookback_hours"]))
    seen_links: set[str] = set()
    items: list[dict] = []
    exclude_terms = [term.lower() for term in config["exclude_keywords"]]
    for query in build_rss_queries(config):
        url = (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(query)}+when:{config['lookback_hours']}h&hl=en-US&gl=US&ceid=US:en"
        )
        xml_text = fetch_text(url)
        root = ET.fromstring(xml_text)
        for node in root.findall(".//item"):
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            pub_date_text = (node.findtext("pubDate") or "").strip()
            source = (node.findtext("source") or "").strip()
            pub_date = parse_pub_date(pub_date_text, timezone)
            haystack = f"{title} {source}".lower()
            if not title or not link or not pub_date or pub_date < cutoff:
                continue
            if any(term in haystack for term in exclude_terms):
                continue
            if link in seen_links:
                continue
            seen_links.add(link)
            matched_company = next((company for company in config["focus_companies"] if company.lower() in haystack), "")
            items.append(
                {
                    "title": title,
                    "link": link,
                    "source": source or "Google News RSS",
                    "published_at": pub_date,
                    "company": matched_company,
                }
            )
    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items[:12]


def build_rss_research_notes(now_local: datetime, config: dict, items: list[dict]) -> str:
    window_start = now_local - timedelta(hours=int(config["lookback_hours"]))
    if not items:
        return f"""# Research Notes
## Time Window
- {window_start.strftime('%Y-%m-%d %H:%M %Z')} 到 {now_local.strftime('%Y-%m-%d %H:%M %Z')}

## Key Findings
- {now_local.strftime('%Y-%m-%d')}：无重大新增，公开 RSS 信号未显示足够高置信的 AI / 科技重大事件。

## Company Watch
- 重点公司未观察到足够高置信新增，建议等待下一轮或补充更窄关键词。

## Evidence Table
| Date | Topic | Company | Claim | Why It Matters | Source |
| --- | --- | --- | --- | --- | --- |
| {now_local.strftime('%Y-%m-%d')} | No major update | - | 无重大新增 | 保持信息纪律，避免噪音 | Google News RSS |

## Source Quality Notes
- 本轮使用公开 RSS 抓取，适合快速监控，后续可叠加 OpenAI 深度整理。
"""

    key_findings = []
    evidence_rows = []
    company_watch = []
    for item in items:
        date_str = item["published_at"].strftime("%Y-%m-%d")
        company = item["company"] or "-"
        claim = item["title"]
        why = "反映 AI / 科技行业近期产品、资本开支、产业链或公司动作。"
        key_findings.append(f"- {date_str}：{claim} 来源：{item['source']} {item['link']}")
        evidence_rows.append(
            f"| {date_str} | News | {company} | {claim} | {why} | {item['link']} |"
        )
        if item["company"]:
            company_watch.append(f"- {item['company']}：{claim} ({item['source']}) {item['link']}")
    if not company_watch:
        company_watch.append("- 本轮重点公司未形成明显集中新增，仍建议持续监控。")

    return "\n".join(
        [
            "# Research Notes",
            "## Time Window",
            f"- {window_start.strftime('%Y-%m-%d %H:%M %Z')} 到 {now_local.strftime('%Y-%m-%d %H:%M %Z')}",
            "",
            "## Key Findings",
            *key_findings,
            "",
            "## Company Watch",
            *company_watch,
            "",
            "## Evidence Table",
            "| Date | Topic | Company | Claim | Why It Matters | Source |",
            "| --- | --- | --- | --- | --- | --- |",
            *evidence_rows,
            "",
            "## Source Quality Notes",
            "- 本轮使用公开 RSS 抓取；优点是无需私有 API 即可持续运行，缺点是摘要深度弱于大模型深度整理。",
        ]
    )


def build_rss_report(now_local: datetime, items: list[dict]) -> str:
    header = [
        "# AI / 科技行业中午简报",
        "",
        f"日期：{now_local.strftime('%Y-%m-%d')}",
        f"生成时间：{now_local.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        "## 一、执行摘要",
        "",
    ]
    if not items:
        header.extend(
            [
                "- 过去 24 小时公开 RSS 信号未显示足够高置信的 AI / 科技重大新增。",
                "- 建议继续关注重点公司财报、产品发布与产业链资本开支动向。",
            ]
        )
        body = [
            "",
            "## 二、重点事件",
            "",
            "### 1. 行业层面",
            "",
            "- 无重大新增。",
            "",
            "### 2. 公司层面",
            "",
            "- 暂无足够高置信新增。",
        ]
    else:
        summary = []
        industry = []
        companies = []
        sources = []
        for item in items[:5]:
            date_str = item["published_at"].strftime("%Y-%m-%d")
            summary.append(f"- {date_str}：{item['title']} ({item['source']})")
        for item in items[:8]:
            date_str = item["published_at"].strftime("%Y-%m-%d")
            line = f"- {date_str}：{item['title']} 来源：{item['source']} {item['link']}"
            if item["company"]:
                companies.append(line)
            else:
                industry.append(line)
            sources.append(f"- {item['source']}：{item['link']}")
        body = [
            *summary,
            "",
            "## 二、重点事件",
            "",
            "### 1. 行业层面",
            "",
            *(industry or ["- 本轮行业新闻主要集中在重点公司层面。"]),
            "",
            "### 2. 公司层面",
            "",
            *(companies or ["- 本轮未出现重点公司集中更新。"]),
            "",
            "## 三、市场与产业链含义",
            "",
            "- 需继续跟踪 AI 基础设施投资、半导体供给、云资本开支与开发者平台采用速度之间是否形成共振。",
            "",
            "## 四、值得继续跟踪",
            "",
            "- 重点公司财报、重大合作、发布会、监管政策与供应链扩产节奏。",
            "",
            "## 五、来源清单",
            "",
            *list(dict.fromkeys(sources)),
        ]
        return "\n".join(header + body)

    footer = [
        "",
        "## 三、市场与产业链含义",
        "",
        "- 维持观察，避免在低信号日过度解读。",
        "",
        "## 四、值得继续跟踪",
        "",
        "- 重点公司财报、重大合作、发布会、监管政策与供应链扩产节奏。",
        "",
        "## 五、来源清单",
        "",
        "- Google News RSS",
    ]
    return "\n".join(header + body + footer)


def format_list(items: list[str], empty_text: str) -> str:
    if not items:
        return empty_text
    return "\n".join(f"- {item}" for item in items)


def build_research_prompt(now_local: datetime, config: dict, template_text: str) -> str:
    window_start = now_local - timedelta(hours=int(config["lookback_hours"]))
    companies = format_list(config["focus_companies"], "- 无指定重点公司")
    include_keywords = format_list(config["include_keywords"], "- 无额外关键词")
    exclude_keywords = format_list(config["exclude_keywords"], "- 无排除词")
    return f"""
你是一名中文科技行业研究员，需要为投资和管理层读者准备一份高质量简报底稿。

覆盖时间窗：
- 开始：{window_start.strftime('%Y-%m-%d %H:%M %Z')}
- 结束：{now_local.strftime('%Y-%m-%d %H:%M %Z')}

任务要求：
1. 搜索过去 {config["lookback_hours"]} 小时 AI / 科技行业的公开新增动态。
2. 重点关注：AI 模型、云、半导体、数据中心、开发者工具、企业 IT、机器人，以及重点公司动态。
3. 强制优先使用高质量来源：官方博客、官方新闻稿、SEC / IR、公司官网、GitHub release、顶级科技媒体。
4. 低质量转载、无来源二手汇总、明显营销软文不要纳入。
5. 如果没有足够高置信新增，必须明确写出“无重大新增”。
6. 所有相对时间表达都改写成绝对日期。
7. 输出必须聚焦新闻事实、业务影响、产业链含义与后续观察点，避免泛泛背景介绍。

重点公司：
{companies}

纳入关键词：
{include_keywords}

排除关键词：
{exclude_keywords}

请严格输出 Markdown，包含以下部分：

# Research Notes
## Time Window
- 明确覆盖时间窗

## Key Findings
- 8-12 条高价值要点；每条必须包含：日期、事件、影响、来源链接

## Company Watch
- 如果重点公司没有新增，也要明确标注

## Evidence Table
| Date | Topic | Company | Claim | Why It Matters | Source |
| --- | --- | --- | --- | --- | --- |

## Source Quality Notes
- 标注哪些是一手源、哪些是高质量媒体源

下一步会基于以下模板成稿：
{template_text}
""".strip()


def build_final_prompt(now_local: datetime, research_notes: str, template_text: str, config: dict) -> str:
    return f"""
请基于下面的研究底稿，生成一份中文研究简报。

硬性要求：
1. 只输出最终 Markdown，不要解释过程，不要输出代码块围栏。
2. 必须严格遵守模板结构和标题顺序。
3. 风格是中文研究简报，不是宣传文，也不是口语摘要。
4. 先写结论，再写事件和影响。
5. 每条核心判断尽量附来源链接。
6. 所有相对时间表达改写为绝对日期。
7. 如果高置信新闻不足，必须明确写“无重大新增”。
8. 允许保留英文公司名、产品名、技术词与 ticker。

当前生成时间：{now_local.strftime('%Y-%m-%d %H:%M %Z')}
主题：{config["topic_name"]}

模板：
{template_text}

研究底稿：
{research_notes}
""".strip()


def cleanup_old_outputs(project_root: Path, retention_days: int, now_local: datetime) -> None:
    cutoff = now_local - timedelta(days=retention_days)
    for top_level in ("artifacts", "reports", "reviews"):
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the AI / tech noon brief.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timezone")
    parser.add_argument("--lookback-hours", type=int)
    parser.add_argument("--date", help="Override report date in YYYY-MM-DD format for backfill runs.")
    parser.add_argument("--dry-run", action="store_true", help="Use sample data instead of external APIs.")
    args = parser.parse_args()

    project_root = args.project_root.expanduser().resolve()
    config_path = (
        args.config.expanduser().resolve()
        if args.config
        else (project_root / os.environ.get("BRIEF_CONFIG_PATH", "config.json")).resolve()
    )
    config = merge_config(read_json(config_path), timezone=args.timezone, lookback_hours=args.lookback_hours)
    timezone = ZoneInfo(config["timezone"])
    now_local = datetime.now(timezone)
    if args.date:
        now_local = datetime.strptime(args.date, "%Y-%m-%d").replace(
            hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone
        )
    date_str = now_local.strftime("%Y-%m-%d")

    template_path = project_root / "templates" / "ai_tech_brief_template.md"
    reports_dir = project_root / "reports"
    artifacts_dir = project_root / "artifacts" / date_str
    report_path = reports_dir / f"{date_str}.md"
    research_path = artifacts_dir / "research_notes.md"
    metadata_path = artifacts_dir / "run_metadata.json"
    research_response_path = artifacts_dir / "research_response.json"
    final_response_path = artifacts_dir / "final_response.json"

    template_text = template_path.read_text(encoding="utf-8")

    if args.dry_run:
        research_notes = FALLBACK_RESEARCH_NOTES
        report_markdown = apply_template_defaults(FALLBACK_REPORT, now_local)
        metadata = {
            "mode": "dry-run",
            "date": date_str,
            "timezone": config["timezone"],
            "lookback_hours": config["lookback_hours"],
            "topic_name": config["topic_name"],
            "items_found": 1,
            "degraded": False,
            "config_path": str(config_path),
        }
        write_text(research_response_path, json.dumps({"mode": "dry-run"}, ensure_ascii=False, indent=2) + "\n")
        write_text(final_response_path, json.dumps({"mode": "dry-run"}, ensure_ascii=False, indent=2) + "\n")
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if api_key:
            research_payload = {
                "model": args.model,
                "reasoning": {"effort": "medium"},
                "tool_choice": "auto",
                "include": ["web_search_call.action.sources"],
                "tools": [
                    {
                        "type": "web_search",
                        "search_context_size": "high",
                        "user_location": {
                            "type": "approximate",
                            "timezone": config["timezone"],
                            "country": "CN",
                            "city": "Shanghai",
                            "region": "Shanghai",
                        },
                    }
                ],
                "input": build_research_prompt(now_local, config, template_text),
                "max_output_tokens": 6000,
            }
            research_response = request_openai(research_payload, api_key)
            research_notes = strip_markdown_fence(extract_output_text(research_response))
            if not research_notes:
                raise BriefGenerationError("Research pass returned empty output.")

            final_payload = {
                "model": args.model,
                "reasoning": {"effort": "medium"},
                "input": build_final_prompt(now_local, research_notes, template_text, config),
                "max_output_tokens": 5000,
            }
            final_response = request_openai(final_payload, api_key)
            report_markdown = apply_template_defaults(
                strip_markdown_fence(extract_output_text(final_response)),
                now_local,
            )
            if not report_markdown:
                raise BriefGenerationError("Final drafting pass returned empty output.")

            metadata = {
                "mode": "live-openai",
                "date": date_str,
                "timezone": config["timezone"],
                "lookback_hours": config["lookback_hours"],
                "topic_name": config["topic_name"],
                "config_path": str(config_path),
                "items_found": research_notes.count("|") - 2 if "|" in research_notes else 0,
                "degraded": "无重大新增" in report_markdown,
            }
            write_text(research_response_path, json.dumps(research_response, ensure_ascii=False, indent=2) + "\n")
            write_text(final_response_path, json.dumps(final_response, ensure_ascii=False, indent=2) + "\n")
        else:
            rss_items = collect_rss_items(now_local, config)
            research_notes = build_rss_research_notes(now_local, config, rss_items)
            report_markdown = build_rss_report(now_local, rss_items)
            metadata = {
                "mode": "live-rss",
                "date": date_str,
                "timezone": config["timezone"],
                "lookback_hours": config["lookback_hours"],
                "topic_name": config["topic_name"],
                "config_path": str(config_path),
                "items_found": len(rss_items),
                "degraded": not bool(rss_items),
            }
            write_text(research_response_path, json.dumps({"mode": "rss-live", "items": rss_items}, ensure_ascii=False, indent=2, default=str) + "\n")
            write_text(final_response_path, json.dumps({"mode": "rss-live"}, ensure_ascii=False, indent=2) + "\n")

    write_text(research_path, research_notes.rstrip() + "\n")
    write_text(report_path, report_markdown.rstrip() + "\n")
    write_text(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    write_text(artifacts_dir / "config_snapshot.json", json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    cleanup_old_outputs(project_root, int(config["retention_days"]), now_local)

    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
