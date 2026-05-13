from __future__ import annotations

import re
import ssl
from datetime import datetime, timedelta
from html import unescape
from urllib import error, request
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from scripts.brief_utils import BriefGenerationError


RSS_USER_AGENT = "Mozilla/5.0 (compatible; AITechPackaging/2.0; +https://github.com/Matt95999/ai-tech-noon-brief)"

DOMESTIC_FEEDS: list[tuple[str, str, str]] = [
    ("JCET Group", "https://www.jcetglobal.com/rss/feed.xml", "rss"),
    ("Tongfu Microelectronics", "https://www.tfme.com/rss/news.xml", "rss"),
    ("SEMI China", "https://www.semi.org/zh/rss.xml", "rss"),
]

DOMESTIC_SEARCH_QUERIES: list[str] = [
    "先进封装 集成电路",
    "长电科技 封装",
    "通富微电",
    "华天科技",
    "北方华创 先进封装",
    "中微公司 TSV",
    "盛美上海 封装",
    "拓荆科技 键合",
    "深南电路 载板",
    "兴森科技 FCBGA",
    "封装设备 国产化",
    "半导体 封测 产能",
    "大基金 三期 封装",
    "先进封装 国产替代",
    "Chiplet 小芯片",
    "HBM 中国 封装",
    "玻璃基板 半导体",
    "芯源微 封装",
    "华海清科 CMP",
    "混合键合 设备",
    "先进封装 检测",
]

POLICY_QUERIES: list[str] = [
    "集成电路 税收优惠 政策",
    "半导体 大基金 投资",
    "先进封装 政策支持",
    "集成电路 进出口 海关",
]


def fetch_url(url: str) -> str:
    req = request.Request(url, headers={"User-Agent": RSS_USER_AGENT}, method="GET")
    try:
        with request.urlopen(req, timeout=60) as response:
            return response.read().decode("utf-8", errors="ignore")
    except error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            insecure_context = ssl._create_unverified_context()
            with request.urlopen(req, timeout=60, context=insecure_context) as response:
                return response.read().decode("utf-8", errors="ignore")
        raise BriefGenerationError("Failed to fetch {}".format(url)) from exc


def parse_pub_date(value: str, fallback_tz: ZoneInfo) -> datetime | None:
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=fallback_tz)
            return dt.astimezone(fallback_tz)
        except ValueError:
            continue
    return None


def normalize_text(value: str) -> str:
    return re.sub(r"[\W_]+", " ", value.lower().strip(), flags=re.UNICODE).strip()


def match_keyword(haystack: str, keyword: str) -> bool:
    return bool(keyword) and normalize_text(keyword) in normalize_text(haystack)


def match_company(haystack: str, config: dict) -> str:
    alias_map = config.get("company_aliases") or {}
    if alias_map:
        for canonical, aliases in alias_map.items():
            if match_keyword(haystack, canonical):
                return canonical
            for alias in aliases:
                if match_keyword(haystack, alias):
                    return canonical
    for company in config.get("focus_companies", []):
        if match_keyword(haystack, company):
            return company
    return ""


def is_excluded(source: str, config: dict) -> bool:
    if not source:
        return False
    ns = normalize_text(source)
    for ex in config.get("source_policy", {}).get("exclude_publishers", []):
        if normalize_text(ex) in ns:
            return True
    return False


def classify_chinese_source(source: str) -> str:
    primary_kw = ["新华社", "人民日报", "工信部", "国家统计局", "海关总署", "上海证券交易所", "深圳证券交易所"]
    secondary_kw = ["财联社", "证券时报", "中国证券报", "集微网", "半导体行业观察", "电子工程专辑", "问芯", "芯智讯"]
    ns = normalize_text(source)
    for kw in primary_kw:
        if kw.lower() in ns:
            return "primary"
    for kw in secondary_kw:
        if kw.lower() in ns:
            return "secondary"
    return "unclassified"


def clean_rss_desc(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:500]


def collect_from_google_cn(queries: list[str], now_local: datetime, config: dict,
                           seen_links: set[str], timezone: ZoneInfo, cutoff: datetime,
                           source_tier_override: str, query_prefix: str,
                           score_base: int) -> list[dict]:
    items = []
    impact_keywords = config.get("impact_policy", {}).get("keywords", [])
    for query in queries:
        try:
            url = ("https://news.google.com/rss/search?q="
                   "{}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans".format(quote_plus(query)))
            xml_text = fetch_url(url)
            root = ET.fromstring(xml_text)
            for node in root.findall(".//item"):
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                pub_date_text = (node.findtext("pubDate") or "").strip()
                source = (node.findtext("source") or "").strip()
                description = clean_rss_desc(node.findtext("description") or "")
                pub_date = parse_pub_date(pub_date_text, timezone)
                if not title or not link or not pub_date or pub_date < cutoff:
                    continue
                if link in seen_links or is_excluded(source, config):
                    continue
                seen_links.add(link)
                haystack = "{} {} {}".format(title, source, description)
                company = match_company(haystack, config)
                tier = "primary" if source_tier_override == "primary" else classify_chinese_source(source)
                matches = [kw for kw in impact_keywords if match_keyword(haystack, kw)]
                confidence = len(matches) > 0 and tier in ("primary", "secondary")
                score = score_base if tier == "primary" else (score_base - 5 if tier == "secondary" else score_base - 12)
                items.append({
                    "title": title, "link": link, "source": source or "Google News CN",
                    "description": description, "published_at": pub_date, "company": company,
                    "query": "{}-{}".format(query_prefix, query[:20]),
                    "source_tier": tier, "impact_matches": matches,
                    "high_confidence": confidence, "confidence_score": score,
                })
        except Exception:
            continue
    return items


def collect_domestic_sources_items(now_local: datetime, config: dict) -> list[dict]:
    timezone = ZoneInfo(config["timezone"])
    cutoff = now_local - timedelta(hours=int(config["lookback_hours"]))
    seen_links: set[str] = set()
    all_items: list[dict] = []

    # Part 1: Domestic feeds
    for source_name, feed_url, feed_type in DOMESTIC_FEEDS:
        try:
            xml_text = fetch_url(feed_url)
            root = ET.fromstring(xml_text)
            for item_node in root.findall(".//item"):
                title = (item_node.findtext("title") or "").strip()
                link = (item_node.findtext("link") or "").strip()
                pub_date_text = (item_node.findtext("pubDate") or "").strip()
                source = (item_node.findtext("source") or "").strip() or source_name
                description = clean_rss_desc(item_node.findtext("description") or "")
                pub_date = parse_pub_date(pub_date_text, timezone)
                if not title or not link or not pub_date or pub_date < cutoff:
                    continue
                if link in seen_links:
                    continue
                seen_links.add(link)
                haystack = "{} {} {}".format(title, source, description)
                company = match_company(haystack, config)
                impact_keywords = config.get("impact_policy", {}).get("keywords", [])
                matches = [kw for kw in impact_keywords if match_keyword(haystack, kw)]
                all_items.append({
                    "title": title, "link": link, "source": source,
                    "description": description, "published_at": pub_date,
                    "company": company, "query": "domestic-feed-{}".format(source_name),
                    "source_tier": "primary", "impact_matches": matches,
                    "high_confidence": len(matches) > 0, "confidence_score": 25,
                })
        except Exception:
            continue

    # Part 2: Chinese news via Google CN
    cn_items = collect_from_google_cn(
        DOMESTIC_SEARCH_QUERIES, now_local, config, seen_links,
        timezone, cutoff, "secondary", "domestic-search", 20
    )
    all_items.extend(cn_items)

    # Part 3: Policy queries
    policy_items = collect_from_google_cn(
        POLICY_QUERIES, now_local, config, seen_links,
        timezone, cutoff, "secondary", "policy", 12
    )
    all_items.extend(policy_items)

    all_items.sort(key=lambda i: i["published_at"], reverse=True)
    return all_items
