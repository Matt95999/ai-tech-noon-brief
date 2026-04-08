#!/usr/bin/env python3
from __future__ import annotations

import argparse
import mimetypes
import os
import re
import smtplib
import socket
import sys
import time
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Optional

from brief_utils import BriefGenerationError, get_bool_env, parse_csv_list, require_env

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
REQUIRED_REPORT_SECTION_GROUPS = (
    ("## Executive Summary", "## 结论"),
    ("## Source Log", "## 来源"),
)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def build_settings() -> dict:
    settings = {
        "smtp_host": os.environ.get("SMTP_HOST", "").strip(),
        "smtp_port": os.environ.get("SMTP_PORT", "").strip() or "587",
        "smtp_username": os.environ.get("SMTP_USERNAME", "").strip(),
        "smtp_password": os.environ.get("SMTP_PASSWORD", "").strip(),
        "email_from": os.environ.get("EMAIL_FROM", "").strip(),
        "email_to": parse_csv_list(os.environ.get("EMAIL_TO", "").replace(";", ",")),
        "smtp_use_ssl": get_bool_env("SMTP_USE_SSL", False),
        "smtp_use_tls": get_bool_env("SMTP_USE_TLS", True),
        "smtp_retry_attempts": int(os.environ.get("SMTP_RETRY_ATTEMPTS", "3")),
        "smtp_retry_delay_seconds": float(os.environ.get("SMTP_RETRY_DELAY_SECONDS", "5")),
        "email_from_name": os.environ.get("EMAIL_FROM_NAME", "").strip(),
    }
    if not settings["email_from"]:
        settings["email_from"] = settings["smtp_username"]
    return settings


def validate_smtp_port(raw_port: str) -> str:
    try:
        port = int(str(raw_port).strip())
    except (TypeError, ValueError) as exc:
        raise BriefGenerationError(f"Invalid SMTP_PORT: {raw_port}") from exc
    if port < 1 or port > 65535:
        raise BriefGenerationError(f"SMTP_PORT out of range: {port}")
    return str(port)


def validate_settings(settings: dict, allow_placeholder: bool = False, require_smtp: bool = True) -> dict:
    validated = dict(settings)
    if allow_placeholder:
        validated["email_from"] = validated["email_from"] or "dry-run@example.com"
        validated["email_to"] = validated["email_to"] or ["dry-run@example.com"]
        return validated

    if not validated["email_from"]:
        raise BriefGenerationError("Missing EMAIL_FROM or SMTP_USERNAME for email delivery.")
    if not validated["email_to"]:
        raise BriefGenerationError("Missing EMAIL_TO for email delivery.")
    if require_smtp:
        if not validated["smtp_host"]:
            raise BriefGenerationError("Missing SMTP_HOST for email delivery.")
        if not validated["smtp_username"]:
            raise BriefGenerationError("Missing SMTP_USERNAME for email delivery.")
        if not validated["smtp_password"]:
            raise BriefGenerationError("Missing SMTP_PASSWORD for email delivery.")
        validated["smtp_port"] = validate_smtp_port(validated["smtp_port"])
        if validated["smtp_use_ssl"] and validated["smtp_use_tls"]:
            raise BriefGenerationError("SMTP_USE_SSL and SMTP_USE_TLS cannot both be true.")
        if validated["smtp_use_ssl"] and validated["smtp_port"] == "587":
            raise BriefGenerationError("SMTP_USE_SSL=true with SMTP_PORT=587 is likely misconfigured; use 465 or disable SSL.")
        if validated["smtp_use_tls"] and validated["smtp_port"] == "465":
            raise BriefGenerationError("SMTP_USE_TLS=true with SMTP_PORT=465 is likely misconfigured; use SSL or switch to 587.")
    return validated


def validate_report(body: str) -> None:
    missing = ["/".join(group) for group in REQUIRED_REPORT_SECTION_GROUPS if not any(section in body for section in group)]
    if missing:
        raise BriefGenerationError(f"Report validation failed; missing sections: {', '.join(missing)}")


def extract_report_title(report_path: Path) -> str:
    try:
        for raw_line in report_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        return ""
    return ""


def build_subject(report_path: Path, subject_prefix: Optional[str] = None) -> str:
    prefix = (
        subject_prefix
        or os.environ.get("EMAIL_SUBJECT_PREFIX", "").strip()
        or extract_report_title(report_path)
        or "AI/科技行业中午简报"
    ).strip()
    prefix = prefix or "AI/科技行业中午简报"
    return f"{prefix}（{report_path.stem}）"


def apply_inline_formatting(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', escaped)
    return escaped


def parse_report_sections(body: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    metadata: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current_title: Optional[str] = None
    current_lines: list[str] = []

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, current_lines))
            current_title = line[3:].strip()
            current_lines = []
            continue

        if current_title is None:
            if line and not line.startswith("# "):
                metadata.append(line)
            continue

        current_lines.append(line)

    if current_title is not None:
        sections.append((current_title, current_lines))
    return metadata, sections


def render_section_html(title: str, lines: list[str]) -> str:
    parts = ['<section class="section">', f"<h2>{escape(title)}</h2>"]
    in_list = False
    current_list_item: list[str] | None = None

    def flush_list_item() -> None:
        nonlocal current_list_item
        if current_list_item is None:
            return
        item_html = "<br>".join(apply_inline_formatting(part) for part in current_list_item if part)
        parts.append(f"<li>{item_html}</li>")
        current_list_item = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if in_list:
                flush_list_item()
                parts.append("</ul>")
                in_list = False
            continue

        if line.startswith("### "):
            if in_list:
                flush_list_item()
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h3>{escape(line[4:].strip())}</h3>")
            continue

        if line.startswith("- "):
            if in_list:
                flush_list_item()
            else:
                parts.append("<ul>")
                in_list = True
            current_list_item = [line[2:].strip()]
            continue

        if in_list:
            current_list_item = (current_list_item or []) + [line]
            continue

        if title in {"Source Log", "来源"} and line.startswith(("1. ", "2. ", "3. ", "4. ", "5. ", "6. ", "7. ", "8. ", "9. ")):
            parts.append(f"<p><strong>{apply_inline_formatting(line)}</strong></p>")
            continue

        parts.append(f"<p>{apply_inline_formatting(line)}</p>")

    if in_list:
        flush_list_item()
        parts.append("</ul>")

    parts.append("</section>")
    return "".join(parts)


def render_report_html(title: str, body: str) -> str:
    metadata, sections = parse_report_sections(body)
    metadata_html = "".join(f'<span class="meta-item">{apply_inline_formatting(line)}</span>' for line in metadata)
    summary_title = "Executive Summary"
    executive_summary: list[str] = []
    for section_title, lines in sections:
        if section_title in {"Executive Summary", "结论"}:
            summary_title = section_title
            executive_summary = lines
            break
    summary_items = [line[2:].strip() for line in executive_summary if line.strip().startswith("- ")]
    summary_html = "".join(f"<li>{apply_inline_formatting(item)}</li>" for item in summary_items[:5])
    sections_html = "".join(render_section_html(section_title, lines) for section_title, lines in sections)

    return f"""\
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)}</title>
    <style>
      :root {{ color-scheme: light; }}
      body {{
        margin: 0; padding: 0; background: #f6f8fa; color: #1f2328;
        font: 15px/1.7 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      }}
      .shell {{ width: 100%; padding: 24px 12px; box-sizing: border-box; }}
      .container {{
        max-width: 760px; margin: 0 auto; background: #ffffff; border: 1px solid #d0d7de;
        border-radius: 16px; overflow: hidden; box-shadow: 0 1px 2px rgba(31, 35, 40, 0.04);
      }}
      .hero {{
        padding: 28px 28px 18px; background: linear-gradient(180deg, #ffffff 0%, #f6f8fa 100%);
        border-bottom: 1px solid #d8dee4;
      }}
      .eyebrow {{
        display: inline-block; margin-bottom: 10px; padding: 4px 10px; border-radius: 999px;
        background: #ddf4ff; color: #0969da; font-size: 12px; font-weight: 600; letter-spacing: 0.02em;
      }}
      h1 {{ margin: 0 0 10px; font-size: 28px; line-height: 1.25; }}
      h3 {{ margin: 14px 0 8px; font-size: 15px; color: #1f2328; }}
      .meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
      .meta-item {{
        display: inline-block; padding: 6px 10px; border-radius: 999px; background: #f6f8fa;
        border: 1px solid #d8dee4; color: #57606a; font-size: 13px;
      }}
      .summary-card {{
        margin: 20px 28px 0; padding: 18px 20px; border: 1px solid #d8dee4;
        border-radius: 14px; background: #f6f8fa;
      }}
      .summary-card h2 {{ margin: 0 0 10px; font-size: 16px; }}
      .summary-card ul {{ margin: 0; padding-left: 20px; }}
      .content {{ padding: 8px 28px 28px; }}
      .section {{ padding-top: 22px; border-top: 1px solid #d8dee4; }}
      .section:first-child {{ border-top: 0; }}
      .section h2 {{ margin: 0 0 12px; font-size: 18px; line-height: 1.4; }}
      .section p {{ margin: 0 0 12px; }}
      .section ul {{ margin: 0 0 12px; padding-left: 20px; }}
      .section li {{ margin-bottom: 8px; }}
      code {{
        padding: 0.15em 0.35em; border-radius: 6px; background: rgba(175, 184, 193, 0.2);
        font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace; font-size: 0.92em;
      }}
      a {{ color: #0969da; text-decoration: none; }}
      @media (max-width: 640px) {{
        .hero, .content {{ padding-left: 18px; padding-right: 18px; }}
        .summary-card {{ margin-left: 18px; margin-right: 18px; }}
        h1 {{ font-size: 24px; }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="container">
        <div class="hero">
          <div class="eyebrow">AI Brief</div>
          <h1>{escape(title)}</h1>
          <div class="meta">{metadata_html}</div>
        </div>
        <div class="summary-card">
          <h2>{escape(summary_title)}</h2>
          <ul>{summary_html}</ul>
        </div>
        <div class="content">{sections_html}</div>
      </div>
    </div>
  </body>
</html>
"""


def build_message(
    report_path: Path,
    attach_markdown: bool = True,
    allow_placeholder: bool = False,
    subject_prefix: Optional[str] = None,
) -> EmailMessage:
    settings = validate_settings(build_settings(), allow_placeholder=allow_placeholder, require_smtp=False)
    content = report_path.read_text(encoding="utf-8")
    subject = build_subject(report_path, subject_prefix=subject_prefix)

    message = EmailMessage()
    message["From"] = settings["email_from"]
    message["To"] = ", ".join(settings["email_to"])
    message["Subject"] = subject
    message.set_content(content)
    message.add_alternative(render_report_html(subject, content), subtype="html")

    if attach_markdown:
        mime_type, _ = mimetypes.guess_type(report_path.name)
        maintype, subtype = (mime_type or "text/markdown").split("/", 1)
        message.add_attachment(
            content.encode("utf-8"),
            maintype=maintype,
            subtype=subtype,
            filename=report_path.name,
        )
    return message


def smtp_login(settings: dict, timeout: int = 15) -> None:
    if settings["smtp_use_ssl"]:
        with smtplib.SMTP_SSL(settings["smtp_host"], int(settings["smtp_port"]), timeout=timeout) as server:
            server.login(settings["smtp_username"], settings["smtp_password"])
        return

    with smtplib.SMTP(settings["smtp_host"], int(settings["smtp_port"]), timeout=timeout) as server:
        if settings["smtp_use_tls"]:
            server.starttls()
        server.login(settings["smtp_username"], settings["smtp_password"])


def send_message(message: EmailMessage, settings: Optional[dict] = None) -> None:
    resolved_settings = validate_settings(settings or build_settings(), require_smtp=True)
    last_error: Exception | None = None

    for attempt in range(1, resolved_settings["smtp_retry_attempts"] + 1):
        try:
            if resolved_settings["smtp_use_ssl"]:
                with smtplib.SMTP_SSL(
                    resolved_settings["smtp_host"], int(resolved_settings["smtp_port"]), timeout=30
                ) as server:
                    server.login(resolved_settings["smtp_username"], resolved_settings["smtp_password"])
                    server.send_message(message)
                return

            with smtplib.SMTP(resolved_settings["smtp_host"], int(resolved_settings["smtp_port"]), timeout=30) as server:
                if resolved_settings["smtp_use_tls"]:
                    server.starttls()
                server.login(resolved_settings["smtp_username"], resolved_settings["smtp_password"])
                server.send_message(message)
            return
        except socket.gaierror as exc:
            raise RuntimeError(f"SMTP DNS 解析失败: {resolved_settings['smtp_host']}") from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise RuntimeError("SMTP 登录失败，请检查邮箱账号或授权码。") from exc
        except TimeoutError as exc:
            last_error = RuntimeError(f"SMTP 连接超时: {resolved_settings['smtp_host']}:{resolved_settings['smtp_port']}")
        except ConnectionRefusedError as exc:
            last_error = RuntimeError(
                f"SMTP 连接被拒绝: {resolved_settings['smtp_host']}:{resolved_settings['smtp_port']}"
            )
        except (OSError, smtplib.SMTPException) as exc:
            last_error = exc

        if attempt < resolved_settings["smtp_retry_attempts"]:
            time.sleep(resolved_settings["smtp_retry_delay_seconds"] * attempt)

    raise RuntimeError(f"SMTP 发送失败: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Markdown report via SMTP email.")
    parser.add_argument("report_path", type=Path, nargs="?")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-attach", action="store_true")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--check-smtp", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--skip-validate", action="store_true")
    parser.add_argument("--subject-prefix")
    args = parser.parse_args()

    load_dotenv(args.env_file.expanduser().resolve())
    settings = validate_settings(build_settings(), allow_placeholder=args.dry_run, require_smtp=not args.dry_run)

    if args.check_config:
        print(f"SMTP config OK: {settings['smtp_host']}:{settings['smtp_port']}")
        print(f"From: {settings['email_from']}")
        print(f"To: {', '.join(settings['email_to'])}")
        return 0

    if args.check_smtp or args.probe:
        try:
            smtp_login(settings)
        except socket.gaierror as exc:
            raise RuntimeError(f"SMTP DNS 解析失败: {settings['smtp_host']}") from exc
        print(f"SMTP login OK: {settings['smtp_host']}:{settings['smtp_port']}")
        print(f"From: {settings['email_from']}")
        print(f"To: {', '.join(settings['email_to'])}")
        return 0

    if args.report_path is None:
        raise BriefGenerationError("Missing report path.")

    report_path = args.report_path.expanduser().resolve()
    body = report_path.read_text(encoding="utf-8")
    if not args.skip_validate:
        validate_report(body)

    message = build_message(
        report_path,
        attach_markdown=not args.no_attach,
        allow_placeholder=args.dry_run,
        subject_prefix=args.subject_prefix,
    )

    if args.dry_run:
        print(message["Subject"])
        print("=" * len(str(message["Subject"])))
        print(f"From: {message['From']}")
        print(f"To: {message['To']}")
        print("")
        print(body[:1200].rstrip())
        return 0

    send_message(message, settings=settings)
    print(f"Sent: {report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BriefGenerationError, RuntimeError, OSError, smtplib.SMTPException, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
