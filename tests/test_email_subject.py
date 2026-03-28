from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.send_email_report import build_message


class EmailSubjectTests(unittest.TestCase):
    def test_profile_subject_prefix_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "2026-03-28.md"
            report_path.write_text("# Test\n", encoding="utf-8")

            old_env = {key: os.environ.get(key) for key in ("EMAIL_FROM", "EMAIL_TO", "EMAIL_SUBJECT_PREFIX")}
            os.environ["EMAIL_FROM"] = "sender@example.com"
            os.environ["EMAIL_TO"] = "receiver@example.com"
            os.environ["EMAIL_SUBJECT_PREFIX"] = "默认标题"
            try:
                message = build_message(
                    report_path,
                    allow_placeholder=False,
                    subject_prefix="AI 前沿晨报",
                )
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

            self.assertEqual(message["Subject"], "AI 前沿晨报（2026-03-28）")


if __name__ == "__main__":
    unittest.main()
