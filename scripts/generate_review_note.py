#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from brief_utils import write_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a self-review note for the latest report run.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report-path", type=Path, required=True)
    args = parser.parse_args()

    project_root = args.project_root.expanduser().resolve()
    report_path = args.report_path.expanduser().resolve()
    date_str = report_path.stem
    metadata_path = project_root / "artifacts" / date_str / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}

    degraded = bool(metadata.get("degraded"))
    mode = metadata.get("mode", "unknown")
    items_found = metadata.get("items_found", 0)
    risk_lines = [
        "- 检查报告是否存在“无重大新增”时的降级说明。",
        "- 检查邮件配置是否通过环境变量提供，避免凭据写入仓库。",
        "- 检查报告与 artifacts 是否已保留，确保失败时可补发与排查。",
    ]
    if mode == "dry-run":
        risk_lines.append("- 当前为 dry-run，尚未验证真实新闻抓取质量与模型输出稳定性。")
    if degraded:
        risk_lines.append("- 本次报告包含降级输出，建议复核是否确实缺少高置信新闻。")
    if not items_found:
        risk_lines.append("- 未统计到有效条目数量，建议检查 research notes 结构是否变化。")

    review_note = f"""# Self Review - {date_str}

## Goal

- 生成 AI / 科技行业中午简报，并为邮件发送保留可追溯 artifacts。

## Scope

- `scripts/generate_ai_tech_brief.py`
- `scripts/send_email_report.py`
- `reports/{date_str}.md`
- `artifacts/{date_str}/`

## Validation

- 生成报告文件
- 写入 research notes、metadata、API response 或 dry-run 占位数据
- 生成自审记录

## Non-Goals

- 不保证新闻一定充足
- 不在此步骤内处理人工编辑润色
- 不在邮件失败时自动重试多次

## Run Summary

- Mode: `{mode}`
- Items found: `{items_found}`
- Degraded output: `{degraded}`

## Review Checklist

- 正确性：报告日期、时区、文件路径是否一致。
- 回归风险：邮件失败时报告与 artifacts 是否仍保留。
- 边界情况：无新闻、单条来源异常、模型输出为空时是否能明确报错或降级。
- 配置安全：SMTP 与 API 密钥是否只通过环境变量传入。
- 测试缺口：是否至少跑过一次 `--dry-run` 与一次邮件 dry-run。

## Risks And Follow-Ups

{chr(10).join(risk_lines)}
"""

    review_path = project_root / "reviews" / f"{date_str}-self-review.md"
    summary_path = project_root / "summaries" / f"{date_str}.md"
    write_text(review_path, review_note.rstrip() + "\n")
    write_text(summary_path, f"# Summary - {date_str}\n\n- Report: `{report_path}`\n- Review: `{review_path}`\n")
    print(review_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
