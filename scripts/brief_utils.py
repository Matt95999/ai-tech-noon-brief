from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_LOOKBACK_HOURS = 24
OPENAI_API_URL = "https://api.openai.com/v1/responses"
USER_AGENT = "AITechNoonBrief/1.0"


class BriefGenerationError(Exception):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise BriefGenerationError(f"Missing required environment variable: {name}")
    return value


def get_bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return parse_csv_list(value.replace(";", ","))
    return [str(value).strip()] if str(value).strip() else []


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def extract_output_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if output_text:
        return str(output_text).strip()

    texts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                texts.append(content["text"])
    return "\n".join(texts).strip()


def strip_markdown_fence(text: str) -> str:
    fenced = re.match(r"^```(?:markdown)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    return fenced.group(1).strip() if fenced else text.strip()


def apply_template_defaults(text: str, now_local: datetime) -> str:
    rendered = text.replace("{{date}}", now_local.strftime("%Y-%m-%d"))
    rendered = rendered.replace("{{generated_at}}", now_local.strftime("%Y-%m-%d %H:%M %Z"))
    return rendered


def merge_config(
    base_config: dict[str, Any],
    timezone: str | None = None,
    lookback_hours: int | None = None,
) -> dict[str, Any]:
    config = dict(base_config)
    config["timezone"] = timezone or os.environ.get("REPORT_TIMEZONE") or config.get("timezone") or DEFAULT_TIMEZONE
    config["lookback_hours"] = (
        lookback_hours
        if lookback_hours is not None
        else int(os.environ.get("LOOKBACK_HOURS", str(config.get("lookback_hours", DEFAULT_LOOKBACK_HOURS))))
    )
    config["topic_name"] = config.get("topic_name", "AI/科技行业中午简报")
    config["focus_companies"] = normalize_string_list(config.get("focus_companies", []))
    config["include_keywords"] = normalize_string_list(config.get("include_keywords", []))
    config["exclude_keywords"] = normalize_string_list(config.get("exclude_keywords", []))
    config["retention_days"] = int(config.get("retention_days", 14))
    delivery = dict(config.get("delivery", {}))
    delivery["email_subject_prefix"] = delivery.get("email_subject_prefix", config["topic_name"])
    delivery["attach_markdown"] = bool(delivery.get("attach_markdown", True))
    config["delivery"] = delivery

    source_policy = dict(config.get("source_policy", {}))
    source_policy["primary_publishers"] = normalize_string_list(source_policy.get("primary_publishers", []))
    source_policy["secondary_publishers"] = normalize_string_list(source_policy.get("secondary_publishers", []))
    source_policy["require_primary_source"] = bool(source_policy.get("require_primary_source", False))
    config["source_policy"] = source_policy

    impact_policy = dict(config.get("impact_policy", {}))
    impact_policy["keywords"] = normalize_string_list(impact_policy.get("keywords", []))
    impact_policy["max_candidates"] = int(impact_policy.get("max_candidates", 12))
    impact_policy["raw_candidate_limit"] = int(
        impact_policy.get("raw_candidate_limit", max(24, impact_policy["max_candidates"] * 6))
    )
    impact_policy["min_high_confidence_items"] = int(impact_policy.get("min_high_confidence_items", 1))
    impact_policy["allow_low_signal_fallback"] = bool(impact_policy.get("allow_low_signal_fallback", True))
    config["impact_policy"] = impact_policy
    return config
