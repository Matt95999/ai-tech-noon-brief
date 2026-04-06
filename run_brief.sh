#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PROFILE="${BRIEF_PROFILE:-${BRIEF_DEFAULT_PROFILE:-ai-frontier-daily}}"

ARGS=("$@")
if [[ "${SKIP_EMAIL:-0}" == "1" ]]; then
  ARGS+=(--skip-delivery)
fi

python3 "$ROOT/scripts/run_profile.py" --project-root "$ROOT" --profile "$PROFILE" "${ARGS[@]}"
