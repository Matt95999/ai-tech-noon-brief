from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.brief_utils import apply_template_defaults, merge_config, parse_csv_list, read_json


class BriefUtilsTests(unittest.TestCase):
    def test_apply_template_defaults(self) -> None:
        now = datetime(2026, 3, 27, 12, 0)
        rendered = apply_template_defaults("Date {{date}} at {{generated_at}}", now)
        self.assertIn("2026-03-27", rendered)

    def test_parse_csv_list(self) -> None:
        self.assertEqual(parse_csv_list("a,b, c "), ["a", "b", "c"])
        self.assertEqual(parse_csv_list(""), [])

    def test_merge_config_uses_defaults(self) -> None:
        os.environ.pop("REPORT_TIMEZONE", None)
        os.environ.pop("LOOKBACK_HOURS", None)
        merged = merge_config({})
        self.assertEqual(merged["timezone"], "Asia/Shanghai")
        self.assertEqual(merged["lookback_hours"], 24)
        self.assertTrue(merged["delivery"]["attach_markdown"])

    def test_read_json_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing.json"
            self.assertEqual(read_json(path), {})


if __name__ == "__main__":
    unittest.main()

