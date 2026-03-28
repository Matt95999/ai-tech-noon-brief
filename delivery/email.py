from __future__ import annotations

from pathlib import Path

from scripts.send_email_report import build_message, send_message


def send_profile_email(report_path: Path, config: dict, dry_run: bool = False) -> None:
    attach_markdown = bool(config.get("delivery", {}).get("attach_markdown", True))
    subject_prefix = config.get("delivery", {}).get("email_subject_prefix")
    message = build_message(
        report_path,
        attach_markdown=attach_markdown,
        allow_placeholder=dry_run,
        subject_prefix=subject_prefix,
    )
    if dry_run:
        print(f"DRY RUN: would send '{message['Subject']}' to {message['To']}")
        return
    send_message(message)
    print(f"Sent: {report_path}")
