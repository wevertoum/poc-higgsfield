#!/usr/bin/env python3
"""One-shot auth refresh for EventBridge/cron jobs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from service.hf import refresh_auth  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(refresh_auth(), indent=2, default=str))
