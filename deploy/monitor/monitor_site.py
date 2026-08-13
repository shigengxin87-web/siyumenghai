#!/usr/bin/env python3
"""Independent semantic monitor with Feishu incident deduplication."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request


BASE = os.environ.get("SIYUMENGHAI_MONITOR_BASE", "https://siyumenghai.cn").rstrip("/")
REPO = "shigengxin87-web/siyumenghai"
API = f"https://api.github.com/repos/{REPO}"
CDN = f"https://cdn.jsdelivr.net/gh/{REPO}"
CANARY = "https://weixin.qq.com/sph/AKlMnWudWP"
EXPECTED_AUTHOR = "车车导演爱提问"
DEFAULT_STATE = Path.home() / "Library/Application Support/Siyumenghai Monitor/state.json"
LARK = "/Users/murphys/.npm-global/bin/lark-cli"
CRITICAL = {
    "index.html": ("text/html", 1_000),
    "member-view/index.html": ("text/html", 5_000),
    "member-view/app.js": ("javascript", 20_000),
    "member-view/members.json": ("json", 500),
    "member-view/video-downloader-20260808-17.html": ("text/html", 5_000),
    "member-view/video-downloader-app.js": ("javascript", 20_000),
    "member-view/video-downloader-app-v35.js": ("javascript", 20),
}


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))


def fetch(url: str, timeout: int = 30) -> tuple[int, bytes, str, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SiyumenghaiExternalMonitor/2", "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read(), response.geturl(), response.headers.get("Content-Type", "")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_public() -> tuple[list[str], dict[str, object]]:
    failures: list[str] = []
    details: dict[str, object] = {}
    commit = json.loads(fetch(f"{API}/commits/main")[1])["sha"]
    for path, (content_type, minimum) in CRITICAL.items():
        cache = f"monitor={int(time.time())}-{os.getpid()}"
        public_url = f"{BASE}/{path}?{cache}"
        status, body, final_url, actual_type = fetch(public_url)
        source_status, source, _, _ = fetch(f"{CDN}@{commit}/{path}")
        public_hash = sha256(body)
        source_hash = sha256(source)
        details[path] = {
            "status": status,
            "content_type": actual_type,
            "bytes": len(body),
            "sha256": public_hash,
            "source_sha256": source_hash,
            "final_url": final_url,
        }
        if status != 200 or source_status != 200:
            failures.append(f"{path} HTTP异常")
        if not final_url.startswith("https://"):
            failures.append(f"{path} 未保持HTTPS")
        if content_type not in actual_type.lower():
            failures.append(f"{path} Content-Type错误({actual_type})")
        if len(body) < minimum:
            failures.append(f"{path} 长度异常({len(body)})")
        if public_hash != source_hash:
            failures.append(f"{path} SHA-256与GitHub main不一致")

    members = json.loads(fetch(f"{BASE}/member-view/members.json?monitor={int(time.time())}")[1])
    if members.get("count") != len(members.get("members", [])) or not members.get("members"):
        failures.append("群友名录为空或人数不一致")
    details["members"] = len(members.get("members", []))

    homepage = fetch(f"{BASE}/?monitor={int(time.time())}")[1].decode("utf-8", errors="replace")
    if "网站升级中" not in homepage or "【石董会】" in homepage or "群聊学习情报" in homepage:
        failures.append("根域名不是预留占位页")

    parser_url = f"{BASE}/api/video/profile?" + urllib.parse.urlencode(
        {"url": CANARY, "monitor": int(time.time())}
    )
    status, body, final_url, actual_type = fetch(parser_url, timeout=45)
    payload = json.loads(body)
    result = payload.get("data") or {}
    parsed = result.get("data") or {}
    feed = parsed.get("feedInfo") or {}
    author = parsed.get("authorInfo") or {}
    video_url = feed.get("videoUrl") or feed.get("originVideoUrl") or ""
    parser_ok = (
        status == 200
        and final_url.startswith("https://")
        and "json" in actual_type.lower()
        and payload.get("code") == 0
        and result.get("errCode") == 0
        and author.get("nickname") == EXPECTED_AUTHOR
        and str(video_url).startswith("http")
    )
    details["parser"] = {
        "status": status,
        "author": author.get("nickname") or "",
        "video_url_length": len(str(video_url)),
        "ok": parser_ok,
    }
    if not parser_ok:
        failures.append("固定样本解析未返回预期作者和视频地址")
    return failures, details


def check_local_comments() -> tuple[list[str], dict[str, object]]:
    failures: list[str] = []
    details: dict[str, object] = {}
    try:
        url = "http://127.0.0.1:2022/api/channels/feed/profile?" + urllib.parse.urlencode({"url": CANARY})
        payload = json.loads(fetch(url, timeout=20)[1])
        obj = (((payload.get("data") or {}).get("data") or {}).get("object") or {})
        oid, nid = str(obj.get("id") or ""), str(obj.get("objectNonceId") or "")
        if not oid or not nid:
            raise RuntimeError("profile没有作品编号")
        comment_url = "http://127.0.0.1:2022/api/channels/feed/comment/list?" + urllib.parse.urlencode(
            {"oid": oid, "nid": nid}
        )
        comments_payload = json.loads(fetch(comment_url, timeout=30)[1])
        result = comments_payload.get("data") or {}
        comments = ((result.get("data") or {}).get("commentInfo") or [])
        if comments_payload.get("code") != 0 or result.get("errCode") != 0 or not comments:
            raise RuntimeError("评论接口没有返回真实评论")
        details = {"ok": True, "comments": len(comments), "object_id": oid}
    except Exception as exc:  # noqa: BLE001
        failures.append(f"本地评论链路失败({type(exc).__name__}: {exc})")
        details = {"ok": False, "error": str(exc)}
    return failures, details


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def notify(recipient: str, message: str, key: str) -> dict:
    command = [
        LARK,
        "im",
        "+messages-send",
        "--as",
        "bot",
        "--user-id",
        recipient,
        "--text",
        message,
        "--idempotency-key",
        key[:50],
        "--format",
        "json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "飞书发送失败")
    return json.loads(result.stdout)


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    failures: list[str] = []
    details: dict[str, object] = {}
    try:
        public_failures, public_details = check_public()
        failures.extend(public_failures)
        details["public"] = public_details
    except Exception as exc:  # noqa: BLE001
        failures.append(f"公网巡检失败({type(exc).__name__}: {exc})")
    if args.check_local_comments:
        comment_failures, comment_details = check_local_comments()
        failures.extend(comment_failures)
        details["comments"] = comment_details
    details["elapsed_seconds"] = round(time.monotonic() - started, 2)

    stamp = now().strftime("%Y-%m-%d %H:%M:%S")
    previous = load_state(args.state_file)
    previous_count = int(previous.get("consecutive_failures", 0))
    alerted = bool(previous.get("alerted", False))
    notification: dict | None = None
    if failures:
        count = previous_count + 1
        last_alert_epoch = int(previous.get("last_alert_epoch", 0))
        should_alert = count >= 2 and (not alerted or time.time() - last_alert_epoch >= 7200)
        if should_alert and args.recipient_id and not args.no_notify:
            message = f"【石董会官网告警】{stamp}\n连续 {count} 次巡检失败：" + "；".join(failures[:6])
            notification = notify(args.recipient_id, message, f"site-down-{int(time.time()) // 300}")
            alerted = True
            last_alert_epoch = int(time.time())
        state = {
            "status": "down",
            "checked_at": stamp,
            "consecutive_failures": count,
            "alerted": alerted,
            "last_alert_epoch": last_alert_epoch,
            "failures": failures,
            "details": details,
            "notification": notification,
        }
    else:
        if alerted and args.recipient_id and not args.no_notify:
            notification = notify(
                args.recipient_id,
                f"【石董会官网恢复】{stamp}\n公网、解析与评论固定样本均已恢复正常。",
                f"site-recovered-{int(time.time()) // 300}",
            )
        state = {
            "status": "healthy",
            "checked_at": stamp,
            "consecutive_failures": 0,
            "alerted": False,
            "details": details,
            "notification": notification,
        }
    save_state(args.state_file, state)
    print(json.dumps(state, ensure_ascii=False))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipient-id", default=os.environ.get("SIYUMENGHAI_FEISHU_OPEN_ID", ""))
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--check-local-comments", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--test-alert", action="store_true")
    args = parser.parse_args()
    if args.test_alert:
        if not args.recipient_id:
            raise SystemExit("test alert requires recipient id")
        receipt = notify(
            args.recipient_id,
            "【石董会官网监控验收】外部 5 分钟巡检、连续两次告警、去重与恢复通知链路已启用。",
            f"site-monitor-acceptance-{int(time.time()) // 300}",
        )
        print(json.dumps({"test_alert": True, "receipt": receipt}, ensure_ascii=False))
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
