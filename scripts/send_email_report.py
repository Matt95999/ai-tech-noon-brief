#!/usr/bin/env python3
from __future__ import annotations

import argparse
import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from brief_utils import BriefGenerationError, get_bool_env, parse_csv_list, require_env


def build_subject(report_path: Path, subject_prefix: Optional[str] = None) -> str:
    prefix = (subject_prefix or os.environ.get("EMAIL_SUBJECT_PREFIX", "AI/科技行业中午简报")).strip()
    prefix = prefix or "AI/科技行业中午简报"
    return f"{prefix}（{report_path.stem}）"


def build_message(
    report_path: Path,
    attach_markdown: bool = True,
    allow_placeholder: bool = False,
    subject_prefix: Optional[str] = None,
) -> EmailMessage:
    email_from = os.environ.get("EMAIL_FROM", "").strip()
    recipients = parse_csv_list(os.environ.get("EMAIL_TO", ""))
    if allow_placeholder:
        email_from = email_from or "dry-run@example.com"
        recipients = recipients or ["dry-run@example.com"]
    else:
        email_from = email_from or require_env("EMAIL_FROM")
        if not recipients:
            recipients = parse_csv_list(require_env("EMAIL_TO"))
    if not recipients:
        raise BriefGenerationError("EMAIL_TO must contain at least one recipient.")

    content = report_path.read_text(encoding="utf-8")
    message = EmailMessage()
    message["From"] = email_from
    message["To"] = ", ".join(recipients)
    message["Subject"] = build_subject(report_path, subject_prefix=subject_prefix)
    message.set_content(content)

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


def send_message(message: EmailMessage) -> None:
    host = require_env("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = require_env("SMTP_USERNAME")
    password = require_env("SMTP_PASSWORD")
    use_ssl = get_bool_env("SMTP_USE_SSL", False)
    use_tls = get_bool_env("SMTP_USE_TLS", True)

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=60) as server:
            server.login(username, password)
            server.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=60) as server:
        if use_tls:
            server.starttls()
        server.login(username, password)
        server.send_message(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Markdown report via SMTP email.")
    parser.add_argument("report_path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-attach", action="store_true")
    args, unknown = parser.parse_known_args()

    if unknown:
        unknown = [item for item in unknown if item != "--dry-run"]

    report_path = args.report_path.expanduser().resolve()
    message = build_message(
        report_path,
        attach_markdown=not args.no_attach,
        allow_placeholder=args.dry_run,
    )

    if args.dry_run:
        print(f"DRY RUN: would send '{message['Subject']}' to {message['To']}")
        return 0

    send_message(message)
    print(f"Sent: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
