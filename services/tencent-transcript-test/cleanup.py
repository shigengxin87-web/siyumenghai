#!/usr/bin/env python3
"""Remove only expired files owned by the isolated Tencent test service."""

from __future__ import annotations

import os
import time
from pathlib import Path


ROOT = Path(os.environ.get("TENCENT_TEST_DATA_DIR", "/var/lib/siyumenghai-transcript-tencent-test"))
CUTOFF = time.time() - int(os.environ.get("TENCENT_TEST_RETENTION_SECONDS", str(7 * 86400)))

for directory in (ROOT / "jobs", ROOT / "cache"):
    if not directory.is_dir():
        continue
    for path in directory.glob("*.json"):
        try:
            if path.stat().st_mtime < CUTOFF:
                path.unlink()
        except FileNotFoundError:
            pass

