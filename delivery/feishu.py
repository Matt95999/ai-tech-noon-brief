from __future__ import annotations

from pathlib import Path

from scripts.send_feishu_report import send_feishu_report


def send_profile_feishu(report_path: Path, config: dict, dry_run: bool = False) -> None:
    subject_prefix = config.get("delivery", {}).get("feishu_title_prefix") or config.get("topic_name")
    send_feishu_report(report_path, subject_prefix=subject_prefix, dry_run=dry_run)
    if dry_run:
        print(f"DRY RUN: would send Feishu card for {report_path}")
        return
    print(f"Feishu sent: {report_path}")
