#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from urllib import error, request

from brief_utils import BriefGenerationError

try:
    from send_email_report import load_dotenv
except ImportError:
    from scripts.send_email_report import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
MAX_MARKDOWN_CHARS = 12000
MAX_SECTION_ITEMS = 5


def resolve_webhook_url(allow_placeholder: bool = False) -> str:
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if webhook_url:
        return webhook_url
    if allow_placeholder:
        return "https://open.feishu.cn/open-apis/bot/v2/hook/dry-run"
    raise BriefGenerationError("Missing FEISHU_WEBHOOK_URL for Feishu delivery.")


def build_title(report_path: Path, subject_prefix: str | None = None) -> str:
    prefix = (subject_prefix or os.environ.get("FEISHU_TITLE_PREFIX") or "集成电路先进封装每日简报").strip()
    return f"{prefix}（{report_path.stem}）"


def parse_markdown_sections(body: str) -> tuple[list[str], dict[str, list[str]]]:
    metadata: list[str] = []
    sections: dict[str, list[str]] = {}
    current_title: str | None = None

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current_title = line[3:].strip()
            sections.setdefault(current_title, [])
            continue
        if current_title is None:
            if line and not line.startswith("# "):
                metadata.append(line)
            continue
        sections[current_title].append(line)
    return metadata, sections


def compact_section(lines: list[str], max_items: int = MAX_SECTION_ITEMS) -> list[str]:
    compacted: list[str] = []
    item_count = 0
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("### "):
            compacted.append(f"**{line[4:].strip()}**")
            continue
        if line.startswith("- "):
            item_count += 1
            if item_count > max_items:
                continue
            compacted.append(line)
            continue
        if item_count <= max_items:
            compacted.append(line)
    return compacted


def build_card_markdown(report_path: Path, title: str) -> str:
    body = report_path.read_text(encoding="utf-8")
    metadata, sections = parse_markdown_sections(body)

    parts: list[str] = []
    if metadata:
        parts.extend(metadata[:3])
        parts.append("")

    for section_name in ("Executive Summary", "Latest Developments", "What Matters", "Source Log"):
        lines = compact_section(sections.get(section_name, []))
        if not lines:
            continue
        parts.append(f"**{section_name}**")
        parts.extend(lines)
        parts.append("")

    if not parts:
        parts = [title, "", body[:MAX_MARKDOWN_CHARS]]

    markdown = "\n".join(parts).strip()
    if len(markdown) > MAX_MARKDOWN_CHARS:
        markdown = markdown[: MAX_MARKDOWN_CHARS - 80].rstrip() + "\n\n_内容较长，完整 Markdown 请查看 GitHub Actions artifact。_"
    return markdown


def sign_payload(payload: dict, sign_secret: str | None = None) -> dict:
    secret = (sign_secret or os.environ.get("FEISHU_SIGN_SECRET", "")).strip()
    if not secret:
        return payload
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    signed_payload = dict(payload)
    signed_payload["timestamp"] = timestamp
    signed_payload["sign"] = base64.b64encode(digest).decode("utf-8")
    return signed_payload


def build_feishu_card_payload(report_path: Path, subject_prefix: str | None = None) -> dict:
    title = build_title(report_path, subject_prefix=subject_prefix)
    markdown = build_card_markdown(report_path, title)
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": markdown,
                }
            ],
        },
    }


def parse_feishu_response(response_body: str) -> dict:
    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise BriefGenerationError("Feishu webhook returned a non-JSON response.") from exc


def assert_feishu_success(result: dict) -> None:
    code = result.get("code", result.get("StatusCode", 0))
    message = result.get("msg", result.get("StatusMessage", ""))
    if code in {0, "0"}:
        return

    known_errors = {
        19001: "Feishu webhook invalid.",
        19021: "Feishu webhook signature validation failed.",
        19022: "Feishu webhook IP is not allowed.",
        19024: "Feishu webhook keyword validation failed.",
    }
    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        numeric_code = -1
    detail = known_errors.get(numeric_code, "Feishu webhook delivery failed.")
    raise BriefGenerationError(f"{detail} code={code} msg={message}")


def post_feishu_payload(webhook_url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            result = parse_feishu_response(response.read().decode("utf-8", errors="ignore"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise BriefGenerationError(f"Feishu webhook HTTP request failed: {exc.code} {details}") from exc
    except error.URLError as exc:
        raise BriefGenerationError(f"Feishu webhook request failed: {exc.reason}") from exc
    assert_feishu_success(result)
    return result


def check_feishu_config(allow_placeholder: bool = False) -> dict:
    webhook_url = resolve_webhook_url(allow_placeholder=allow_placeholder)
    payload = sign_payload(
        {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {"title": {"tag": "plain_text", "content": "Feishu config check"}, "template": "blue"},
                "elements": [{"tag": "markdown", "content": "Feishu config payload can be built."}],
            },
        }
    )
    return {
        "webhook_configured": bool(webhook_url),
        "signed": "sign" in payload,
        "msg_type": payload["msg_type"],
    }


def send_feishu_report(
    report_path: Path,
    subject_prefix: str | None = None,
    dry_run: bool = False,
    allow_placeholder: bool = False,
) -> dict:
    webhook_url = resolve_webhook_url(allow_placeholder=allow_placeholder or dry_run)
    payload = sign_payload(build_feishu_card_payload(report_path, subject_prefix=subject_prefix))
    if dry_run:
        return {"dry_run": True, "payload": payload}
    return post_feishu_payload(webhook_url, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Markdown report to Feishu via custom bot webhook.")
    parser.add_argument("report_path", nargs="?", type=Path)
    parser.add_argument("--subject-prefix")
    parser.add_argument("--check-feishu", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(DEFAULT_ENV_PATH)

    if args.check_feishu:
        result = check_feishu_config(allow_placeholder=args.dry_run)
        print(f"Feishu config OK: webhook_configured={result['webhook_configured']} signed={result['signed']}")
        return 0

    if not args.report_path:
        raise BriefGenerationError("Missing report_path for Feishu delivery.")
    result = send_feishu_report(args.report_path, subject_prefix=args.subject_prefix, dry_run=args.dry_run)
    if args.dry_run:
        print("DRY RUN: Feishu payload built.")
    else:
        print(f"Feishu sent: {args.report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BriefGenerationError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
