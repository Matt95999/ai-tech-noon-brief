#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

REPORT_PATH=$(python3 "$ROOT/scripts/generate_ai_tech_brief.py" --project-root "$ROOT" "$@")
python3 "$ROOT/scripts/generate_review_note.py" --project-root "$ROOT" --report-path "$REPORT_PATH"

if [[ "${SKIP_EMAIL:-0}" == "1" ]]; then
  echo "Skipping email because SKIP_EMAIL=1"
  exit 0
fi

python3 "$ROOT/scripts/send_email_report.py" "$REPORT_PATH" "$@"
