#!/usr/bin/env python3
"""Semantic health check and self-heal for the WeChat Channels parser."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request


ENDPOINT = "http://127.0.0.1:2027/api/channels/parse_sph"
CANARY_URL = "https://weixin.qq.com/sph/AKlMnWudWP"
STATE_FILE = Path("/var/lib/siyumenghai-video-parser/health.json")
SERVICE = "siyumenghai-video-parser.service"


def probe() -> dict[str, object]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"url": CANARY_URL, "health": int(time.time())})
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        payload = json.load(response)

    result = payload.get("data") or {}
    parsed = result.get("data") or {}
    feed = parsed.get("feedInfo") or {}
    author = parsed.get("authorInfo") or {}
    urls = [
        feed.get("videoUrl"),
        feed.get("originVideoUrl"),
        (feed.get("h264VideoInfo") or {}).get("videoUrl"),
        (feed.get("h265VideoInfo") or {}).get("videoUrl"),
    ]
    if payload.get("code") != 0 or result.get("errCode") != 0 or not any(urls):
        raise RuntimeError(
            f"semantic failure: code={payload.get('code')} errCode={result.get('errCode')} videoUrl=false"
        )
    return {
        "author": author.get("nickname") or "",
        "description_length": len(feed.get("description") or ""),
        "has_video_url": True,
    }


def write_state(state: dict[str, object]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, STATE_FILE)


def main() -> int:
    checked_at = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")
    attempts: list[dict[str, object]] = []

    for index in range(3):
        try:
            details = probe()
            state = {
                "healthy": True,
                "checked_at": checked_at,
                "repaired": index > 0,
                "attempts": attempts,
                "details": details,
            }
            write_state(state)
            print(json.dumps(state, ensure_ascii=False))
            return 0
        except Exception as exc:  # noqa: BLE001
            attempts.append({"attempt": index + 1, "error": f"{type(exc).__name__}: {exc}"})
            if index == 0:
                subprocess.run(["systemctl", "restart", SERVICE], check=False, timeout=30)
            time.sleep(3)

    state = {"healthy": False, "checked_at": checked_at, "repaired": False, "attempts": attempts}
    write_state(state)
    print(json.dumps(state, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
