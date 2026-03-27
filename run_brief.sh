#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PROFILE="${BRIEF_PROFILE:-ai-tech-daily}"

ARGS=("$@")
if [[ "${SKIP_EMAIL:-0}" == "1" ]]; then
  ARGS+=(--skip-delivery)
fi

python3 "$ROOT/scripts/run_profile.py" --project-root "$ROOT" --profile "$PROFILE" "${ARGS[@]}"
