from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.send_email_report import (
    build_message,
    render_report_html,
    send_message,
    validate_report,
    validate_settings,
)
from brief_utils import BriefGenerationError


class FakeSMTP:
    sent_messages = 0

    def __init__(self, host: str, port: int, timeout: int = 0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        return None

    def send_message(self, message) -> None:
        FakeSMTP.sent_messages += 1


class EmailDeliveryTests(unittest.TestCase):
    def test_render_report_html_contains_summary_card(self) -> None:
        html = render_report_html(
            "AI 晚报（2026-04-06）",
            "# AI 晚报\n\n日期: 2026-04-06\n\n## Executive Summary\n- 第一条\n\n## Source Log\n1. Source\n   https://example.com\n",
        )
        self.assertIn("Executive Summary", html)
        self.assertIn("https://example.com", html)

    def test_build_message_includes_html_alternative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "2026-04-06.md"
            report_path.write_text(
                "# AI 晚报\n\n日期: 2026-04-06\n\n## Executive Summary\n- 第一条\n\n## Source Log\n1. Source\n   https://example.com\n",
                encoding="utf-8",
            )
            import os

            old_env = {key: os.environ.get(key) for key in ("EMAIL_FROM", "EMAIL_TO")}
            os.environ["EMAIL_FROM"] = "sender@example.com"
            os.environ["EMAIL_TO"] = "receiver@example.com"
            try:
                message = build_message(report_path, subject_prefix="AI 晚报")
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

        self.assertEqual(message["Subject"], "AI 晚报（2026-04-06）")
        self.assertGreaterEqual(len(message.get_payload()), 2)

    def test_render_report_html_supports_chinese_section_titles(self) -> None:
        body = (
            "# 多模型开发日报\n\n日期: 2026-04-08\n\n## 结论\n- 第一条\n\n## 来源\n"
            "1. Source\n   https://example.com\n"
        )
        validate_report(body)
        html = render_report_html("多模型开发日报（2026-04-08）", body)
        self.assertIn(">结论<", html)
        self.assertIn(">来源<", html)
        self.assertIn("https://example.com", html)

    def test_send_message_uses_retry_capable_settings(self) -> None:
        import smtplib

        original_smtp = smtplib.SMTP
        smtplib.SMTP = FakeSMTP
        FakeSMTP.sent_messages = 0
        try:
            message = "placeholder"
            settings = {
                "smtp_host": "smtp.example.com",
                "smtp_port": "587",
                "smtp_username": "user",
                "smtp_password": "pass",
                "email_from": "sender@example.com",
                "email_to": ["receiver@example.com"],
                "smtp_use_ssl": False,
                "smtp_use_tls": True,
                "smtp_retry_attempts": 2,
                "smtp_retry_delay_seconds": 0,
            }
            send_message(message, settings=settings)
        finally:
            smtplib.SMTP = original_smtp

        self.assertEqual(FakeSMTP.sent_messages, 1)

    def test_validate_settings_rejects_conflicting_ssl_and_tls(self) -> None:
        with self.assertRaises(BriefGenerationError):
            validate_settings(
                {
                    "smtp_host": "smtp.example.com",
                    "smtp_port": "465",
                    "smtp_username": "user",
                    "smtp_password": "pass",
                    "email_from": "sender@example.com",
                    "email_to": ["receiver@example.com"],
                    "smtp_use_ssl": True,
                    "smtp_use_tls": True,
                    "smtp_retry_attempts": 2,
                    "smtp_retry_delay_seconds": 0,
                }
            )

    def test_validate_settings_rejects_mismatched_tls_port(self) -> None:
        with self.assertRaises(BriefGenerationError):
            validate_settings(
                {
                    "smtp_host": "smtp.example.com",
                    "smtp_port": "465",
                    "smtp_username": "user",
                    "smtp_password": "pass",
                    "email_from": "sender@example.com",
                    "email_to": ["receiver@example.com"],
                    "smtp_use_ssl": False,
                    "smtp_use_tls": True,
                    "smtp_retry_attempts": 2,
                    "smtp_retry_delay_seconds": 0,
                }
            )


if __name__ == "__main__":
    unittest.main()
