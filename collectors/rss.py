from __future__ import annotations

import json
import ssl
from datetime import datetime, timedelta
from urllib import error, request
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from scripts.brief_utils import BriefGenerationError

RSS_USER_AGENT = "Mozilla/5.0 (compatible; AITechNoonBrief/1.0)"


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
        query_pool = [config["topic_name"], "research brief", "industry news", "company update"]
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
- {now_local.strftime('%Y-%m-%d')}：无重大新增，公开 RSS 信号未显示足够高置信的 {config["topic_name"]} 相关事件。

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
        why = f"反映 {config['topic_name']} 近期产品、资本开支、产业链或公司动作。"
        key_findings.append(f"- {date_str}：{claim} 来源：{item['source']} {item['link']}")
        evidence_rows.append(f"| {date_str} | News | {company} | {claim} | {why} | {item['link']} |")
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


def build_rss_report(now_local: datetime, config: dict, items: list[dict]) -> str:
    header = [
        f"# {config['topic_name']}",
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
                f"- 过去 {config['lookback_hours']} 小时公开 RSS 信号未显示足够高置信的主题新增。",
                "- 建议继续关注重点公司、监管、财报与产品发布动向。",
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
        "- 需继续跟踪关键主题的供需、采用速度、资本开支与外部政策变化是否形成共振。",
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


def collect_rss_report(now_local: datetime, config: dict) -> dict:
    items = collect_rss_items(now_local, config)
    return {
        "mode": "live-rss",
        "research_notes": build_rss_research_notes(now_local, config, items),
        "report_markdown": build_rss_report(now_local, config, items),
        "research_response": {"mode": "rss-live", "items": items},
        "final_response": {"mode": "rss-live"},
        "items_found": len(items),
        "degraded": not bool(items),
    }

