from __future__ import annotations

import json
from datetime import datetime, timedelta
from urllib import error, request

from scripts.brief_utils import (
    OPENAI_API_URL,
    USER_AGENT,
    BriefGenerationError,
    extract_output_text,
    strip_markdown_fence,
)


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
1. 搜索过去 {config["lookback_hours"]} 小时与主题 {config["topic_name"]} 有关的公开新增动态。
2. 重点关注 profile 中给出的关键词、公司和主题线索。
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


def collect_openai_report(now_local: datetime, config: dict, template_text: str, model: str, api_key: str) -> dict:
    research_payload = {
        "model": model,
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
        "model": model,
        "reasoning": {"effort": "medium"},
        "input": build_final_prompt(now_local, research_notes, template_text, config),
        "max_output_tokens": 5000,
    }
    final_response = request_openai(final_payload, api_key)
    report_markdown = strip_markdown_fence(extract_output_text(final_response))
    if not report_markdown:
        raise BriefGenerationError("Final drafting pass returned empty output.")

    return {
        "mode": "live-openai",
        "research_notes": research_notes,
        "report_markdown": report_markdown,
        "research_response": research_response,
        "final_response": final_response,
        "items_found": research_notes.count("|") - 2 if "|" in research_notes else 0,
        "degraded": "无重大新增" in report_markdown,
    }

