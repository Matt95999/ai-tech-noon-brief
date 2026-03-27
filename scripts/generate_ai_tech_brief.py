#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "python3",
            str(project_root / "scripts" / "run_profile.py"),
            "--project-root",
            str(project_root),
            "--profile",
            "ai-tech-daily",
        ],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
