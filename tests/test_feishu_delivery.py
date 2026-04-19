from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from brief_utils import BriefGenerationError
from scripts import send_feishu_report


class FakeHTTPResponse:
    def __init__(self, body: str) -> None:
        self.body = body

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self.body.encode("utf-8")


def write_sample_report(tmpdir: str) -> Path:
    report_path = Path(tmpdir) / "2026-04-19.md"
    report_path.write_text(
        "\n".join(
            [
                "# 集成电路先进封装每日简报",
                "",
                "日期: 2026-04-19",
                "生成时间: 2026-04-19 08:30 CST",
                "",
                "## Executive Summary",
                "- 先进封装供给侧出现新增。",
                "- HBM 与 CoWoS 仍是主线。",
                "",
                "## Latest Developments",
                "- TSMC 更新 CoWoS 产能。",
                "- Intel 更新 Foveros 路线。",
                "",
                "## What Matters",
                "- 瓶颈继续从封装转向系统级交付。",
                "",
                "## Source Log",
                "1. TSMC source",
                "   https://example.com/tsmc",
            ]
        ),
        encoding="utf-8",
    )
    return report_path


class FeishuDeliveryTests(unittest.TestCase):
    def test_build_feishu_card_payload_contains_title_and_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = write_sample_report(tmpdir)
            payload = send_feishu_report.build_feishu_card_payload(
                report_path,
                subject_prefix="集成电路先进封装每日简报",
            )

        markdown = payload["card"]["elements"][0]["content"]
        self.assertEqual(payload["msg_type"], "interactive")
        self.assertEqual(payload["card"]["header"]["title"]["content"], "集成电路先进封装每日简报（2026-04-19）")
        self.assertIn("Executive Summary", markdown)
        self.assertIn("Latest Developments", markdown)
        self.assertIn("Source Log", markdown)

    def test_long_card_markdown_is_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "2026-04-19.md"
            report_path.write_text(
                "# R\n\n"
                + "监控范围: "
                + ("先进封装 " * 2500)
                + "\n\n## Executive Summary\n"
                + "\n".join(f"- item {idx} {'x' * 500}" for idx in range(100)),
                encoding="utf-8",
            )
            payload = send_feishu_report.build_feishu_card_payload(report_path)

        markdown = payload["card"]["elements"][0]["content"]
        self.assertLessEqual(len(markdown), send_feishu_report.MAX_MARKDOWN_CHARS)
        self.assertIn("完整 Markdown", markdown)

    def test_sign_payload_adds_timestamp_and_signature(self) -> None:
        payload = send_feishu_report.sign_payload({"msg_type": "interactive"}, sign_secret="secret")

        self.assertIn("timestamp", payload)
        self.assertIn("sign", payload)

    def test_check_feishu_config_does_not_require_network(self) -> None:
        old_env = {key: os.environ.get(key) for key in ("FEISHU_WEBHOOK_URL", "FEISHU_SIGN_SECRET")}
        os.environ["FEISHU_WEBHOOK_URL"] = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
        os.environ["FEISHU_SIGN_SECRET"] = "secret"
        try:
            result = send_feishu_report.check_feishu_config()
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertTrue(result["webhook_configured"])
        self.assertTrue(result["signed"])

    def test_send_feishu_report_dry_run_does_not_post(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = write_sample_report(tmpdir)
            with mock.patch.object(send_feishu_report, "post_feishu_payload") as mocked_post:
                result = send_feishu_report.send_feishu_report(report_path, dry_run=True)

        mocked_post.assert_not_called()
        self.assertTrue(result["dry_run"])

    def test_post_feishu_payload_accepts_success_response(self) -> None:
        with mock.patch.object(
            send_feishu_report.request,
            "urlopen",
            return_value=FakeHTTPResponse('{"StatusCode":0,"StatusMessage":"success"}'),
        ):
            result = send_feishu_report.post_feishu_payload(
                "https://open.feishu.cn/open-apis/bot/v2/hook/test",
                {"msg_type": "interactive"},
            )

        self.assertEqual(result["StatusCode"], 0)

    def test_assert_feishu_success_maps_common_errors(self) -> None:
        with self.assertRaisesRegex(BriefGenerationError, "keyword"):
            send_feishu_report.assert_feishu_success({"code": 19024, "msg": "Key Words Not Found"})


if __name__ == "__main__":
    unittest.main()
