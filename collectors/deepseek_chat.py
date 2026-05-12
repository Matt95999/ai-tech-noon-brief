from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from urllib import error, request
from urllib.parse import urlsplit, urlunsplit

from collectors.rss import (
    build_source_audit,
    collect_rss_items_with_audit,
    filter_rss_items,
    format_source_audit_notes,
    serialize_items,
)
from collectors.official_rss import collect_official_rss_items
from collectors.domestic_sources import collect_domestic_sources_items
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
            "Authorization": "Bearer " + api_key,
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
            raise ValueError("DeepSeek API configuration failed: " + str(exc.code) + " " + details) from exc
        raise BriefGenerationError("DeepSeek API request failed: " + str(exc.code) + " " + details) from exc
    except error.URLError as exc:
        raise BriefGenerationError("DeepSeek API request failed: " + str(exc)) from exc


def normalize_deepseek_api_url(api_url: str, purpose: str) -> str:
    raw_url = api_url.strip()
    if not raw_url:
        raise ValueError("Missing DEEPSEEK_API_URL for " + purpose + ".")

    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("Invalid DEEPSEEK_API_URL for " + purpose + ": " + raw_url)

    path = parsed.path.rstrip("/")
    if path in {"", "/"}:
        path = "/chat/completions"
    elif path == "/v1":
        path = "/v1/chat/completions"
    elif not path.endswith("/chat/completions"):
        raise ValueError(
            "DEEPSEEK_API_URL must point to a chat completions endpoint, for example "
            "https://api.deepseek.com/chat/completions ."
        )

    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


def resolve_deepseek_config(model: str | None = None, purpose: str = "DeepSeek operation") -> dict:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ValueError("Missing DEEPSEEK_API_KEY for " + purpose + ".")

    api_url = normalize_deepseek_api_url(os.environ.get("DEEPSEEK_API_URL", ""), purpose)
    resolved_model = model or os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_DEEPSEEK_MODEL
    return {
        "api_key": api_key,
        "api_url": api_url,
        "model": resolved_model,
    }


def check_deepseek_config(model: str | None = None) -> dict:
    resolved = resolve_deepseek_config(model=model, purpose="DeepSeek config check")
    payload = {
        "model": resolved["model"],
        "messages": [
            {"role": "system", "content": "Return a short plain-text health confirmation."},
            {"role": "user", "content": "Reply with OK only."},
        ],
        "temperature": 0,
        "max_tokens": 8,
    }
    response = request_deepseek(payload, resolved["api_key"], resolved["api_url"])
    output = extract_choice_text(response)
    if not output:
        raise BriefGenerationError("DeepSeek config check returned empty output.")
    return {
        "api_url": resolved["api_url"],
        "model": resolved["model"],
        "output": output,
    }


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
            "| " + date_str + " | " + item.get("source_tier", "unclassified") + " | " + source + " | "
            + (item.get("company") or "-") + " | " + impact_matches + " | " + title + " | " + item["link"] + " |"
        )
    return "\n".join(lines)


def build_research_prompt(now_local: datetime, config: dict, items: list[dict], source_audit: dict | None = None) -> str:
    hours_val = str(config.get("lookback_hours", 24))
    window_start = now_local - timedelta(hours=int(hours_val))

    def _safe_get(cfg, k1, k2, fallback=""):
        v = cfg.get(k1, {})
        if isinstance(v, dict):
            return ", ".join(v.get(k2, [])) or fallback
        return fallback

    primary = _safe_get(config, "source_policy", "primary_publishers", "-")
    secondary = _safe_get(config, "source_policy", "secondary_publishers", "-")
    impact_keywords = _safe_get(config, "impact_policy", "keywords", "-")

    audit_notes = "\n".join(format_source_audit_notes(source_audit or {}))

    sources_used = source_audit.get("multi_source_merge", []) if source_audit else []
    source_desc = " + ".join(sources_used) if sources_used else "RSS"
    tier0_count = sum(1 for i in items if i.get("source_tier") == "primary")
    tier1_count = sum(1 for i in items if i.get("source_tier") == "secondary")
    total = len(items)

    topic_name = config.get("topic_name", "先进封装每日研究")

    lines = []
    lines.append("你是一名严谨的中文半导体产业研究编辑，专精于先进封装赛道。你只能使用我提供的候选证据，不得补充外部事实，不得猜测。")
    lines.append("")
    lines.append("时间窗：")
    lines.append("- 开始：" + window_start.strftime("%Y-%m-%d %H:%M %Z"))
    lines.append("- 结束：" + now_local.strftime("%Y-%m-%d %H:%M %Z"))
    lines.append("")
    lines.append("报告定位：" + topic_name)
    lines.append("")
    lines.append("信源采集说明：")
    lines.append("- 本日候选共 " + str(total) + " 条，其中 TIER 0（官方一手源）" + str(tier0_count) + " 条，TIER 1/2（权威媒体/研究）" + str(tier1_count) + " 条")
    lines.append("- 采集渠道：" + source_desc)
    lines.append("  - RSS = Google News RSS 泛行业搜索")
    lines.append("  - official_rss = 企业官网/IR/新闻室直接订阅")
    lines.append("  - domestic_sources = 中国国内信源（政策/企业/行业媒体）")
    lines.append("")
    lines.append("主信源名单：" + primary)
    lines.append("二线补充信源名单：" + secondary)
    lines.append("影响力关键词：" + impact_keywords)
    lines.append("")
    lines.append("输出规则：")
    lines.append("- 若证据不足以支撑[高影响动态]，必须明确写[无重大新增]")
    lines.append("- primary 和 secondary 可用于支撑正式结论；unclassified 只能作为观察线索")
    lines.append("- 所有相对时间改写成绝对日期")
    lines.append("- 每条结论标注置信度（高/中/低）")
    lines.append("")
    lines.append("请输出严格 Markdown，包含以下部分：")
    lines.append("")
    lines.append("# Research Notes")
    lines.append("## Time Window")
    lines.append("- 明确覆盖时间窗")
    lines.append("")
    lines.append("## Selection Summary")
    lines.append("- 解释入选逻辑或[无重大新增]判定理由")
    lines.append("")
    lines.append("## Key Findings")
    lines.append("- 每条必须包含：日期、事实、影响、来源名（TIER层级）")
    lines.append("")
    lines.append("## Evidence Table")
    lines.append("| Date | Topic | Company | Claim | Why It Matters | Source |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    lines.append("")
    lines.append("## Source Quality Notes")
    lines.append("- 标出 TIER 0/1/2 使用情况")
    lines.append("")
    lines.append("信源审计：")
    lines.append(audit_notes)
    lines.append("")
    lines.append("候选证据：")
    lines.append(format_candidates(items))

    return "\n".join(lines)


def build_final_prompt(now_local: datetime, config: dict, template_text: str, research_notes: str) -> str:
    topic_name = config.get("topic_name", "先进封装每日研究")

    lines = []
    lines.append("请把下面研究底稿整理成最终中文产业观察日报，必须严格遵守以下规则：")
    lines.append("")
    lines.append("1. 只输出最终 Markdown，不要解释过程，不要输出代码块围栏。")
    lines.append("2. 必须严格遵守模板结构与标题顺序。")
    lines.append("3. 只能使用研究底稿中的事实，不得新增未验证细节。")
    lines.append("4. 正文使用短 bullet，先结论后解释，不在正文插入链接。")
    lines.append("5. 所有判断必须标注置信度（高/中/低）。")
    lines.append("6. 链接统一放在文末 Source Log，按 Source ID 编号。")
    lines.append("7. 如果研究底稿显示高影响事件不足，明确写[无重大新增]。")
    lines.append("8. 所有相对时间改写成绝对日期。")
    lines.append("9. 每条结论尾部标注 [Source ID]，与 Source Log 对应。")
    lines.append("")
    lines.append("当前生成时间：" + now_local.strftime("%Y-%m-%d %H:%M %Z"))
    lines.append("主题：" + topic_name)
    lines.append("")
    lines.append("模板：")
    lines.append(template_text)
    lines.append("")
    lines.append("研究底稿：")
    lines.append(research_notes)

    return "\n".join(lines)


def build_low_signal_research_notes(now_local: datetime, config: dict, items: list[dict]) -> str:
    hours_val = str(config.get("lookback_hours", 24))
    window_start = now_local - timedelta(hours=int(hours_val))
    min_items = int(config.get("impact_policy", {}).get("min_high_confidence_items", 1))
    lines = [
        "# Research Notes",
        "## Time Window",
        "- " + window_start.strftime("%Y-%m-%d %H:%M %Z") + " 到 " + now_local.strftime("%Y-%m-%d %H:%M %Z"),
        "",
        "## Selection Summary",
        "- 高置信候选仅 " + str(len(items)) + " 条，低于最低门槛 " + str(min_items) + " 条，本轮按[无重大新增]处理。",
    ]
    if items:
        lines.extend(["- 已保留候选供后续继续跟踪，但不作为正式高影响结论。"])
    lines.extend(
        [
            "",
            "## Key Findings",
            "- " + now_local.strftime("%Y-%m-%d") + "：无重大新增。当前候选不足以支撑高影响判断。",
            "",
            "## Evidence Table",
            "| Date | Topic | Company | Claim | Why It Matters | Source |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    if items:
        for item in items:
            lines.append(
                "| " + item["published_at"].strftime("%Y-%m-%d") + " | Watchlist | " + (item.get("company") or "-") + " | "
                + item["title"] + " | 候选保留，未达高影响门槛 | " + item["link"] + " |"
            )
    else:
        lines.append(
            "| " + now_local.strftime("%Y-%m-%d") + " | No major update | - | 无重大新增 | 保持信息纪律，避免噪音 | Internal candidate filter |"
        )
    lines.extend(
        [
            "",
            "## Source Quality Notes",
            "- 候选已通过基础信源规则筛选，但数量或影响力不足，故不扩写为正式日报结论。",
        ]
    )
    return "\n".join(lines)


def append_source_audit_to_research_notes(research_notes: str, source_audit: dict) -> str:
    notes = format_source_audit_notes(source_audit)
    if not notes:
        return research_notes
    return "\n".join(
        [
            research_notes.rstrip(),
            "",
            "## Source Audit",
            *notes,
        ]
    )


def build_low_signal_report(now_local: datetime, config: dict) -> str:
    slug = config.get("slug")
    companies = config.get("focus_companies", [])[:4]
    if slug == "us-iran-conflict-daily":
        summary_lines = [
            "- 无重大新增。过去 24 小时未出现足够高置信、且具有较大影响力的美国-伊朗冲突新增。",
            "- 本轮继续保持严格信源纪律，避免把未充分核验的战事、外交或能源噪音写进正式简报。",
        ]
    else:
        topic_name = config.get("topic_name", "行业简报")
        summary_lines = [
            "- 无重大新增。过去 24 小时未出现足够高置信、且具有较大影响力的" + topic_name + "新增。",
            "- 本轮继续保持严格信源纪律，避免把低影响或二手噪音写进正式日报。",
        ]
    lines = [
        "# " + config.get("topic_name", "行业简报"),
        "",
        "日期: " + now_local.strftime("%Y-%m-%d"),
        "生成时间: " + now_local.strftime("%Y-%m-%d %H:%M %Z"),
        "",
        "## Executive Summary",
    ]
    lines.extend(summary_lines)
    lines.append("")
    if slug == "us-iran-conflict-daily":
        lines.extend(
            [
                "## Latest Developments",
                "- 无重大新增。过去 24 小时未出现足够高置信、且具有较大影响力的战事、外交或能源新增。",
                "- 继续观察停火、霍尔木兹通航、制裁与核设施风险是否形成新催化。",
                "",
                "## Country / Geopolitical Impact",
                "### United States",
                "- 无重大新增。",
                "- 继续跟踪美国官方表态与军事部署变化。",
                "",
                "### Iran",
                "- 无重大新增。",
                "- 继续跟踪伊朗官方表态、反制动作与能源设施风险。",
                "",
                "### Israel / Gulf / Major Powers",
                "- 无重大新增。",
                "- 继续跟踪以色列、海湾国家及主要大国的外交与安全动作。",
                "",
                "## Financial / Macro Pulse",
                "- 无重大新增。暂未形成足以改变市场定价的高置信新增。",
                "- 继续跟踪原油、天然气、黄金、美元、美债与航运保险价格变化。",
                "",
            ]
        )
    elif slug == "advanced-packaging-daily":
        lines.extend(
            [
                "## Latest Developments",
                "- 无重大新增。过去 24 小时未出现足够高置信、且具有较大影响力的先进封装行业新增。",
                "- 继续观察扩产、量产、客户导入、平台发布、产业政策与供应链瓶颈是否形成新催化。",
                "",
                "## Global Leader Watch",
                "### TSMC / Intel / Samsung",
                "- 无重大新增。",
                "- 继续跟踪 CoWoS、SoIC、Foveros、I-Cube、X-Cube 与 HBM 协同节奏。",
                "",
                "### ASE / Amkor / 其他全球 OSAT",
                "- 无重大新增。",
                "- 继续跟踪 2.5D/3D、扇出、先进测试、区域化交付与北美/东南亚布局。",
                "",
                "## China Watch",
                "### 长电科技 / 通富微电 / 华天科技",
                "- 无重大新增。",
                "- 继续跟踪 XDFOI、Chiplet、2.5D/3D、先进测试与大客户导入。",
                "",
                "### 深南电路 / 载板材料 / 本土供应链",
                "- 无重大新增。",
                "- 继续跟踪 FC-BGA、ABF、封装材料、热管理与验证放量。",
                "",
                "## Supply Chain Radar",
                "### Demand Side",
                "- 无重大新增。",
                "- 继续跟踪 NVIDIA、AMD、Broadcom、Marvell、华为及云厂商的先进封装需求牵引。",
                "",
                "### Substrates / Materials",
                "- 无重大新增。",
                "- 继续跟踪 ABF 载板、FCBGA、玻璃基板、封装材料与热界面材料。",
                "",
                "### Equipment / Test / Thermal / Photonics",
                "- 无重大新增。",
                "- 继续跟踪键合、混合键合、先进测试、液冷、硅光与 CPO 新增。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Major Developments",
                "- 无重大新增。",
                "- 继续观察模型发布、资本开支、监管政策与重大合作是否形成新催化。",
                "",
                "## Company Watch",
            ]
        )
        for company in companies:
            lines.extend(["### " + company, "- 无重大新增。", "- 继续跟踪官方发布、财报、合作与产品更新。"])
    lines.extend(
        [
            "",
            "## What Matters",
            "- 严格筛选下的[无重大新增]本身就是结论，说明市场暂无足以重估行业节奏的新事实。",
            "- 当高影响事件出现时，日报会优先保留一手信源和可核验日期，再做简洁判断。",
            "",
            "## Source Log",
            "1. Internal candidate filter",
            "   artifacts/run_metadata.json",
        ]
    )
    return "\n".join(lines)


def collect_deepseek_report(now_local: datetime, config: dict, template_text: str, model: str | None = None) -> dict:
    resolved = resolve_deepseek_config(model=model, purpose="DeepSeek live generation")

    # ---- Multi-source merge ----
    collectors_config = config.get("collectors", ["rss"])
    all_raw: list[dict] = []
    all_audit: dict = {"sources_used": [], "source_counts": {}}

    # Source 1: Google News RSS
    if "rss" in collectors_config:
        try:
            rss_raw, rss_collect_audit = collect_rss_items_with_audit(now_local, config)
            all_raw.extend(rss_raw)
            all_audit["rss"] = rss_collect_audit
            all_audit["sources_used"].append("rss")
        except Exception:
            pass

    # Source 2: TIER 0 official RSS/Atom feeds
    if "official_rss" in collectors_config:
        try:
            official_raw = collect_official_rss_items(now_local, config)
            all_raw.extend(official_raw)
            all_audit["official_rss_count"] = len(official_raw)
            all_audit["sources_used"].append("official_rss")
        except Exception:
            pass

    # Source 3: Chinese domestic sources
    if "domestic_sources" in collectors_config:
        try:
            domestic_raw = collect_domestic_sources_items(now_local, config)
            all_raw.extend(domestic_raw)
            all_audit["domestic_sources_count"] = len(domestic_raw)
            all_audit["sources_used"].append("domestic_sources")
        except Exception:
            pass

    # Deduplicate by link
    seen_links: set[str] = set()
    deduped: list[dict] = []
    for item in sorted(all_raw, key=lambda i: i.get("confidence_score", 0), reverse=True):
        link = item.get("link", "")
        if link and link in seen_links:
            continue
        if link:
            seen_links.add(link)
        deduped.append(item)

    # Re-score merged items
    for item in deduped:
        tw = {"primary": 3, "secondary": 2, "unclassified": 1}.get(item.get("source_tier", "unclassified"), 0)
        cw = 2 if item.get("company") else 0
        iw = min(len(item.get("impact_matches", [])), 5)
        item["confidence_score"] = tw * 10 + cw * 4 + iw * 3

    deduped.sort(key=lambda i: (i.get("confidence_score", 0), i["published_at"].timestamp() if i.get("published_at") else 0), reverse=True)

    max_candidates = int(config.get("impact_policy", {}).get("max_candidates", 15))
    items = filter_rss_items(deduped[:max_candidates], config)
    source_audit = build_source_audit(all_raw, items, all_audit)
    source_audit["multi_source_merge"] = all_audit["sources_used"]

    min_items = int(config.get("impact_policy", {}).get("min_high_confidence_items", 2))
    if len(items) < min_items:
        research_notes = append_source_audit_to_research_notes(
            build_low_signal_research_notes(now_local, config, items),
            source_audit,
        )
        return {
            "mode": "low-signal-filtered-rss",
            "research_notes": research_notes,
            "report_markdown": build_low_signal_report(now_local, config),
            "research_response": {
                "mode": "low-signal-filtered-rss",
                "items": serialize_items(items),
                "source_audit": source_audit,
            },
            "final_response": {"mode": "low-signal-filtered-rss"},
            "items_found": len(items),
            "degraded": True,
            "source_audit": source_audit,
        }

    research_payload = {
        "model": resolved["model"],
        "messages": [
            {"role": "system", "content": "You are a rigorous Chinese semiconductor industry research editor specializing in advanced packaging."},
            {"role": "user", "content": build_research_prompt(now_local, config, items, source_audit)},
        ],
        "temperature": 0.2,
    }
    research_response = request_deepseek(research_payload, resolved["api_key"], resolved["api_url"])
    research_notes = strip_markdown_fence(extract_choice_text(research_response))
    if not research_notes:
        raise BriefGenerationError("DeepSeek research pass returned empty output.")
    research_notes = append_source_audit_to_research_notes(research_notes, source_audit)

    final_payload = {
        "model": resolved["model"],
        "messages": [
            {"role": "system", "content": "You are a Chinese semiconductor investment research analyst writing data-anchored executive summaries."},
            {"role": "user", "content": build_final_prompt(now_local, config, template_text, research_notes)},
        ],
        "temperature": 0.2,
    }
    final_response = request_deepseek(final_payload, resolved["api_key"], resolved["api_url"])
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
            "source_audit": source_audit,
        },
        "final_response": final_response,
        "items_found": len(items),
        "degraded": "无重大新增" in report_markdown,
        "source_audit": source_audit,
    }
