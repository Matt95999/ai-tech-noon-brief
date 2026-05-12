from __future__ import annotations

import re
import ssl
from datetime import datetime, timedelta
from html import unescape
from urllib import error, request
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from scripts.brief_utils import BriefGenerationError


RSS_USER_AGENT = "Mozilla/5.0 (compatible; AITechPackaging/2.0; +https://github.com/Matt95999/ai-tech-noon-brief)"

OFFICIAL_RSS_FEEDS: list[tuple[str, str, str]] = [
    ("TSMC", "https://investor.tsmc.com/rss/news.xml", "rss"),
    ("Intel", "https://www.intel.com/content/www/us/en/newsroom/newsroom-rss.html", "rss"),
    ("Samsung Semiconductor", "https://semiconductor.samsung.com/newsroom/feed/", "rss"),
    ("ASE Holdings", "https://www.aseglobal.com/rss/feed.xml", "rss"),
    ("Amkor Technology", "https://www.amkor.com/news-and-events/feed/", "rss"),
    ("JCET Group", "https://www.jcetglobal.com/rss/feed.xml", "rss"),
    ("Micron Technology", "https://investors.micron.com/news-releases/rss", "rss"),
    ("SK hynix", "https://www.skhynix.com/newsroom/rss.xml", "rss"),
    ("NVIDIA", "https://nvidianews.nvidia.com/releases.xml", "rss"),
    ("AMD", "https://ir.amd.com/news-releases/rss", "rss"),
    ("Broadcom", "https://investors.broadcom.com/news-releases/rss", "rss"),
    ("Marvell", "https://www.marvell.com/company/news/feed.xml", "rss"),
    ("BESI", "https://www.besi.com/investors/press-releases/rss", "rss"),
    ("ASMPT", "https://www.asmpt.com/en/investors/press-releases/rss", "rss"),
    ("Onto Innovation", "https://www.ontoinnovation.com/investors/press-releases/rss", "rss"),
    ("Disco Corporation", "https://www.disco.co.jp/jp/news/rss.xml", "rss"),
    ("SEMI", "https://www.semi.org/rss.xml", "rss"),
    ("UCIe Consortium", "https://www.uciexpress.org/news/feed/", "rss"),
    ("IMEC", "https://www.imec-int.com/en/rss.xml", "rss"),
    ("JEDEC", "https://www.jedec.org/news/rss.xml", "rss"),
    ("Huawei", "https://www.huawei.com/en/news/rss", "rss"),
]

OFFICIAL_ATOM_FEEDS: list[tuple[str, str, str]] = [
    ("TSMC", "https://investor.tsmc.com/atom/news.xml", "atom"),
    ("NVIDIA", "https://nvidianews.nvidia.com/releases.atom", "atom"),
]


def fetch_feed(url: str) -> str:
    req = request.Request(url, headers={"User-Agent": RSS_USER_AGENT}, method="GET")
    try:
        with request.urlopen(req, timeout=60) as response:
            return response.read().decode("utf-8", errors="ignore")
    except error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            insecure_context = ssl._create_unverified_context()
            with request.urlopen(req, timeout=60, context=insecure_context) as response:
                return response.read().decode("utf-8", errors="ignore")
        raise BriefGenerationError("Failed to fetch official feed {}: {}".format(url, exc)) from exc


def clean_html(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:500]


def parse_rss_item(item_node: ET.Element, source_name: str, query_label: str, timezone: ZoneInfo) -> dict | None:
    title = (item_node.findtext("title") or "").strip()
    link = (item_node.findtext("link") or "").strip()
    pub_date_text = (item_node.findtext("pubDate") or "").strip()
    description = clean_html(item_node.findtext("description") or "")
    if not title or not link:
        return None

    pub_date = None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(pub_date_text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone)
            pub_date = dt.astimezone(timezone)
            break
        except ValueError:
            continue

    if pub_date is None:
        pub_date = datetime.now(timezone)

    return {
        "title": title,
        "link": link,
        "source": source_name,
        "description": description,
        "published_at": pub_date,
        "company": source_name,
        "query": query_label,
        "source_tier": "primary",
        "impact_matches": [],
        "high_confidence": True,
        "confidence_score": 30,
    }


def parse_atom_entry(entry_node: ET.Element, source_name: str, query_label: str, timezone: ZoneInfo, ns: str) -> dict | None:
    title_el = entry_node.find("{{{}}}title".format(ns))
    link_el = entry_node.find("{{{}}}link".format(ns))
    updated_el = entry_node.find("{{{}}}updated".format(ns))
    summary_el = entry_node.find("{{{}}}summary".format(ns))

    title = title_el.text.strip() if title_el is not None and title_el.text else ""
    link = link_el.get("href", "").strip() if link_el is not None else ""
    pub_date_text = updated_el.text.strip() if updated_el is not None and updated_el.text else ""
    description = summary_el.text.strip() if summary_el is not None and summary_el.text else ""

    if not title or not link:
        return None

    pub_date = None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(pub_date_text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone)
            pub_date = dt.astimezone(timezone)
            break
        except ValueError:
            continue

    if pub_date is None:
        pub_date = datetime.now(timezone)

    return {
        "title": title,
        "link": link,
        "source": source_name,
        "description": clean_html(description),
        "published_at": pub_date,
        "company": source_name,
        "query": query_label,
        "source_tier": "primary",
        "impact_matches": [],
        "high_confidence": True,
        "confidence_score": 30,
    }


def collect_official_rss_items(now_local: datetime, config: dict) -> list[dict]:
    timezone = ZoneInfo(config["timezone"])
    cutoff = now_local - timedelta(hours=int(config["lookback_hours"]))

    all_feeds = list(OFFICIAL_RSS_FEEDS) + list(OFFICIAL_ATOM_FEEDS)
    seen_links: set[str] = set()
    items: list[dict] = []

    for source_name, feed_url, feed_type in all_feeds:
        try:
            xml_text = fetch_feed(feed_url)
            root = ET.fromstring(xml_text)
        except Exception:
            continue

        try:
            if root.tag == "rss" or root.tag == "rdf:RDF":
                for item_node in root.findall(".//item"):
                    parsed = parse_rss_item(item_node, source_name, feed_type, timezone)
                    if parsed is None or parsed["published_at"] < cutoff or parsed["link"] in seen_links:
                        continue
                    seen_links.add(parsed["link"])
                    items.append(parsed)
            else:
                atom_ns = root.tag.split("}")[0].strip("{") if "}" in root.tag else "http://www.w3.org/2005/Atom"
                for entry_node in root.findall("{{{}}}entry".format(atom_ns)):
                    parsed = parse_atom_entry(entry_node, source_name, feed_type, timezone, atom_ns)
                    if parsed is None or parsed["published_at"] < cutoff or parsed["link"] in seen_links:
                        continue
                    seen_links.add(parsed["link"])
                    items.append(parsed)
        except Exception:
            continue

    items.sort(key=lambda i: i["published_at"], reverse=True)
    return items
