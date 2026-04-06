from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from urllib import error, request

from collectors.rss import collect_rss_items, filter_rss_items, serialize_items
from scripts.brief_utils import BriefGenerationError, DEFAULT_DEEPSEEK_MODEL, USER_AGENT, strip_markdown_fence


def extract_choice_text(response: dict) -> str:
    choices = response.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if text:
                parts.append(str(text))
                continue
            if item.get("type") == "text" and item.get("content"):
                parts.append(str(item["content"]))
        return "\n".join(parts).strip()
    return ""


def request_deepseek(payload: dict, api_key: str, api_url: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        api_url,
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
        if exc.code in {401, 403, 404}:
            raise ValueError(f"DeepSeek API configuration failed: {exc.code} {details}") from exc
        raise BriefGenerationError(f"DeepSeek API request failed: {exc.code} {details}") from exc
    except error.URLError as exc:
        raise BriefGenerationError(f"DeepSeek API request failed: {exc}") from exc


def format_candidates(items: list[dict]) -> str:
    lines = [
        "| Date | Source Tier | Source | Company | Impact Tags | Headline | URL |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        impact_matches = ", ".join(item.get("impact_matches", [])) or "-"
        date_str = item["published_at"].strftime("%Y-%m-%d")
        title = str(item["title"]).replace("|", "/")
        source = str(item["source"]).replace("|", "/")
        lines.append(
            f"| {date_str} | {item.get('source_tier', 'unclassified')} | {source} | "
            f"{item.get('company') or '-'} | {impact_matches} | {title} | {item['link']} |"
        )
    return "\n".join(lines)


def build_research_prompt(now_local: datetime, config: dict, items: list[dict]) -> str:
    window_start = now_local - timedelta(hours=int(config["lookback_hours"]))
    primary = ", ".join(config.get("source_policy", {}).get("primary_publishers", [])) or "无"
    secondary = ", ".join(config.get("source_policy", {}).get("secondary_publishers", [])) or "无"
    require_primary = "是" if config.get("source_policy", {}).get("require_primary_source") else "否"
    impact_keywords = ", ".join(config.get("impact_policy", {}).get("keywords", [])) or "无"
    return f"""
你是一名严谨的中文 AI 产业编辑。你只能使用我提供的候选证据，不得补充外部事实，不得猜测。

时间窗：
- 开始：{window_start.strftime('%Y-%m-%d %H:%M %Z')}
- 结束：{now_local.strftime('%Y-%m-%d %H:%M %Z')}

选题标准：
- 主题：{config["topic_name"]}
- 主信源名单：{primary}
- 二线补充信源名单：{secondary}
- 是否必须主信源：{require_primary}
- 影响力关键词：{impact_keywords}
- 若证据不足以支撑“高影响动态”，必须明确写“无重大新增”。
- 只保留真实、可归因、对 AI 产业或主要公司有明显影响的事件。
- 所有相对时间表达改写成绝对日期。

请基于下面候选证据，输出严格 Markdown，包含以下部分：

# Research Notes
## Time Window
- 明确覆盖时间窗

## Selection Summary
- 解释为什么这些事件入选，或为什么最终判断为“无重大新增”

## Key Findings
- 4-8 条；每条必须包含：日期、事实、影响、来源标题或来源名

## Evidence Table
| Date | Topic | Company | Claim | Why It Matters | Source |
| --- | --- | --- | --- | --- | --- |

## Source Quality Notes
- 标出主信源与二线信源使用情况

候选证据：
{format_candidates(items)}
""".strip()


def build_final_prompt(now_local: datetime, config: dict, template_text: str, research_notes: str) -> str:
    return f"""
请把下面研究底稿整理成最终中文晚报，必须严格遵守以下规则：

1. 只输出最终 Markdown，不要解释过程，不要输出代码块围栏。
2. 必须严格遵守模板结构与标题顺序。
3. 只能使用研究底稿中的事实，不得新增未验证细节。
4. 正文使用短 bullet，先结论后解释，不在正文插入链接。
5. 链接统一放在文末 Source Log。
6. 如果研究底稿显示高影响事件不足，明确写“无重大新增”。
7. 所有相对时间改写成绝对日期。

当前生成时间：{now_local.strftime('%Y-%m-%d %H:%M %Z')}
主题：{config["topic_name"]}

模板：
{template_text}

研究底稿：
{research_notes}
""".strip()


def build_low_signal_research_notes(now_local: datetime, config: dict, items: list[dict]) -> str:
    window_start = now_local - timedelta(hours=int(config["lookback_hours"]))
    min_items = int(config.get("impact_policy", {}).get("min_high_confidence_items", 1))
    lines = [
        "# Research Notes",
        "## Time Window",
        f"- {window_start.strftime('%Y-%m-%d %H:%M %Z')} 到 {now_local.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        "## Selection Summary",
        f"- 高置信候选仅 {len(items)} 条，低于最低门槛 {min_items} 条，本轮按“无重大新增”处理。",
    ]
    if items:
        lines.extend(["- 已保留候选供后续继续跟踪，但不作为正式高影响结论。"])
    lines.extend(
        [
            "",
            "## Key Findings",
            f"- {now_local.strftime('%Y-%m-%d')}：无重大新增。当前候选不足以支撑高影响判断。",
            "",
            "## Evidence Table",
            "| Date | Topic | Company | Claim | Why It Matters | Source |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    if items:
        for item in items:
            lines.append(
                f"| {item['published_at'].strftime('%Y-%m-%d')} | Watchlist | {item.get('company') or '-'} | "
                f"{item['title']} | 候选保留，未达高影响门槛 | {item['link']} |"
            )
    else:
        lines.append(
            f"| {now_local.strftime('%Y-%m-%d')} | No major update | - | 无重大新增 | 保持信息纪律，避免噪音 | Internal candidate filter |"
        )
    lines.extend(
        [
            "",
            "## Source Quality Notes",
            "- 候选已通过基础信源规则筛选，但数量或影响力不足，故不扩写为正式晚报结论。",
        ]
    )
    return "\n".join(lines)


def build_low_signal_report(now_local: datetime, config: dict) -> str:
    companies = config.get("focus_companies", [])[:4]
    lines = [
        f"# {config['topic_name']}",
        "",
        f"日期: {now_local.strftime('%Y-%m-%d')}",
        f"生成时间: {now_local.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        "## Executive Summary",
        "- 无重大新增。过去 24 小时未出现足够高置信、且具有较大影响力的 AI 动态。",
        "- 本轮继续保持严格信源纪律，避免把低影响或二手噪音写进正式晚报。",
        "",
        "## Major Developments",
        "- 无重大新增。",
        "- 继续观察模型发布、资本开支、监管政策与重大合作是否形成新催化。",
        "",
        "## Company Watch",
    ]
    for company in companies:
        lines.extend([f"### {company}", "- 无重大新增。", "- 继续跟踪官方发布、财报、合作与产品更新。"])
    lines.extend(
        [
            "",
            "## What Matters",
            "- 严格筛选下的“无重大新增”本身就是结论，说明市场暂无足以重估行业节奏的新事实。",
            "- 当高影响事件出现时，晚报会优先保留一手信源和可核验日期，再做简洁判断。",
            "",
            "## Source Log",
            "1. Internal candidate filter",
            "   artifacts/run_metadata.json",
        ]
    )
    return "\n".join(lines)


def collect_deepseek_report(now_local: datetime, config: dict, template_text: str, model: str | None = None) -> dict:
    items = filter_rss_items(collect_rss_items(now_local, config), config)
    min_items = int(config.get("impact_policy", {}).get("min_high_confidence_items", 1))
    if len(items) < min_items:
        return {
            "mode": "low-signal-filtered-rss",
            "research_notes": build_low_signal_research_notes(now_local, config, items),
            "report_markdown": build_low_signal_report(now_local, config),
            "research_response": {"mode": "low-signal-filtered-rss", "items": serialize_items(items)},
            "final_response": {"mode": "low-signal-filtered-rss"},
            "items_found": len(items),
            "degraded": True,
        }

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    api_url = os.environ.get("DEEPSEEK_API_URL", "").strip()
    if not api_key:
        raise ValueError("Missing DEEPSEEK_API_KEY for DeepSeek live generation.")
    if not api_url:
        raise ValueError("Missing DEEPSEEK_API_URL for DeepSeek live generation.")

    resolved_model = model or os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_DEEPSEEK_MODEL
    research_payload = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": "You are a rigorous Chinese AI industry editor."},
            {"role": "user", "content": build_research_prompt(now_local, config, items)},
        ],
        "temperature": 0.2,
    }
    research_response = request_deepseek(research_payload, api_key, api_url)
    research_notes = strip_markdown_fence(extract_choice_text(research_response))
    if not research_notes:
        raise BriefGenerationError("DeepSeek research pass returned empty output.")

    final_payload = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": "You write concise Chinese executive briefings."},
            {"role": "user", "content": build_final_prompt(now_local, config, template_text, research_notes)},
        ],
        "temperature": 0.2,
    }
    final_response = request_deepseek(final_payload, api_key, api_url)
    report_markdown = strip_markdown_fence(extract_choice_text(final_response))
    if not report_markdown:
        raise BriefGenerationError("DeepSeek drafting pass returned empty output.")

    return {
        "mode": "live-deepseek",
        "research_notes": research_notes,
        "report_markdown": report_markdown,
        "research_response": {
            "mode": "live-deepseek",
            "response": research_response,
            "items": serialize_items(items),
        },
        "final_response": final_response,
        "items_found": len(items),
        "degraded": "无重大新增" in report_markdown,
    }
