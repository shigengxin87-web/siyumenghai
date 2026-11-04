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
CANARY_URLS = (
    "https://weixin.qq.com/sph/AKlMnWudWP",
    "https://weixin.qq.com/sph/A4JRXiahvr",
)
STATE_FILE = Path("/var/lib/siyumenghai-video-parser/health.json")
SERVICE = "siyumenghai-video-parser.service"
RESTART_WINDOW_SECONDS = 1800
MAX_RESTARTS = 2
PROBE_ATTEMPTS = 3
PROBE_DELAY_SECONDS = 5


class ProbeFailure(RuntimeError):
    """A redacted, classifiable semantic probe failure."""


def safe_message(payload: dict, result: dict) -> str:
    value = payload.get("msg") or payload.get("errMsg") or result.get("msg") or result.get("errMsg") or ""
    return " ".join(str(value).split())[:160]


def probe_one(canary_url: str, index: int) -> dict[str, object]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"url": canary_url, "health": int(time.time())})
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise ProbeFailure(f"transport: HTTP {response.status}")
            payload = json.load(response)
    except ProbeFailure:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProbeFailure(f"transport: {type(exc).__name__}: {exc}") from exc

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
        message = safe_message(payload, result)
        raise ProbeFailure(
            f"semantic: canary={index} code={payload.get('code')} errCode={result.get('errCode')} "
            f"videoUrl={bool(any(urls))} message={message or '-'}"
        )
    return {
        "canary": index,
        "author": author.get("nickname") or "",
        "description_length": len(feed.get("description") or ""),
        "has_video_url": True,
    }


def probe() -> dict[str, object]:
    failures: list[str] = []
    for index, canary_url in enumerate(CANARY_URLS, start=1):
        try:
            return probe_one(canary_url, index)
        except ProbeFailure as exc:
            failures.append(str(exc))
    raise ProbeFailure("all canaries failed: " + " | ".join(failures))


def write_state(state: dict[str, object]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, STATE_FILE)


def load_state() -> dict[str, object]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def restart_service() -> tuple[int, int]:
    """Clear systemd's failed/start-limit state before trying a recovery restart."""
    reset = subprocess.run(["systemctl", "reset-failed", SERVICE], check=False, timeout=15)
    restart = subprocess.run(["systemctl", "restart", SERVICE], check=False, timeout=45)
    return reset.returncode, restart.returncode


def main() -> int:
    checked_at = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")
    attempts: list[dict[str, object]] = []
    previous = load_state()
    now_epoch = int(time.time())
    restart_history = [
        int(value)
        for value in previous.get("restart_history", [])
        if now_epoch - int(value) < RESTART_WINDOW_SECONDS
    ]
    restart_suppressed = False
    previous_healthy = bool(previous.get("healthy", True))

    for index in range(PROBE_ATTEMPTS):
        try:
            details = probe()
            state = {
                "healthy": True,
                "checked_at": checked_at,
                "repaired": False,
                "attempts": attempts,
                "details": details,
                "consecutive_failures": 0,
                "restart_history": restart_history,
                "restart_suppressed": restart_suppressed,
                "recovered_from_incident": not previous_healthy,
                "manual_test_recommended": not previous_healthy or bool(previous.get("manual_test_recommended")),
                "last_incident_at": previous.get("last_incident_at") or previous.get("incident_started_at"),
                "last_recovery_at": checked_at if not previous_healthy else previous.get("last_recovery_at"),
            }
            write_state(state)
            print(json.dumps(state, ensure_ascii=False))
            return 0
        except Exception as exc:  # noqa: BLE001
            attempts.append({"attempt": index + 1, "error": f"{type(exc).__name__}: {exc}"})
            if index + 1 < PROBE_ATTEMPTS:
                time.sleep(PROBE_DELAY_SECONDS)

    repaired = False
    if len(restart_history) < MAX_RESTARTS:
        reset_returncode, restart_returncode = restart_service()
        restart_history.append(now_epoch)
        attempts.append(
            {
                "action": "restart",
                "reset_failed_returncode": reset_returncode,
                "returncode": restart_returncode,
            }
        )
        if restart_returncode == 0:
            time.sleep(4)
            try:
                details = probe()
                repaired = True
                state = {
                    "healthy": True,
                    "checked_at": checked_at,
                    "repaired": True,
                    "attempts": attempts,
                    "details": details,
                    "consecutive_failures": 0,
                    "restart_history": restart_history,
                    "restart_suppressed": False,
                    "recovered_from_incident": True,
                    "manual_test_recommended": True,
                    "last_incident_at": previous.get("incident_started_at") or checked_at,
                    "last_recovery_at": checked_at,
                }
                write_state(state)
                print(json.dumps(state, ensure_ascii=False))
                return 0
            except Exception as exc:  # noqa: BLE001
                attempts.append({"attempt": "post_restart", "error": f"{type(exc).__name__}: {exc}"})
    else:
        restart_suppressed = True

    state = {
        "healthy": False,
        "checked_at": checked_at,
        "repaired": repaired,
        "attempts": attempts,
        "consecutive_failures": int(previous.get("consecutive_failures", 0)) + 1,
        "restart_history": restart_history,
        "restart_suppressed": restart_suppressed,
        "incident_started_at": previous.get("incident_started_at") or checked_at,
        "manual_test_recommended": False,
        "last_incident_at": previous.get("last_incident_at") or previous.get("incident_started_at") or checked_at,
        "last_recovery_at": previous.get("last_recovery_at"),
    }
    write_state(state)
    print(json.dumps(state, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
