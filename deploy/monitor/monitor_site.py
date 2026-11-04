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
RAW = f"https://raw.githubusercontent.com/{REPO}"
CANARY = "https://weixin.qq.com/sph/AKlMnWudWP"
EXPECTED_AUTHOR = "车车导演爱提问"
DEFAULT_STATE = Path.home() / "Library/Application Support/Siyumenghai Monitor/state.json"
LARK = "/Users/murphys/.npm-global/bin/lark-cli"
PARSER_SSH_HOST = os.environ.get("SIYUMENGHAI_MONITOR_SSH_HOST", "")
PARSER_SSH_KEY = os.environ.get("SIYUMENGHAI_MONITOR_SSH_KEY", "")
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


def fetch(url: str, timeout: int = 30, attempts: int = 2) -> tuple[int, bytes, str, str]:
    errors: list[str] = []
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "SiyumenghaiExternalMonitor/3", "Cache-Control": "no-cache"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read(), response.geturl(), response.headers.get("Content-Type", "")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError("；".join(errors))


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
        source_status, source, _, _ = fetch(f"{RAW}/{commit}/{path}")
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


def check_server_parser_state() -> dict[str, object]:
    if not PARSER_SSH_HOST or not PARSER_SSH_KEY:
        return {}
    command = [
        "/usr/bin/ssh",
        "-i",
        PARSER_SSH_KEY,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        PARSER_SSH_HOST,
        "sudo -n cat /var/lib/siyumenghai-video-parser/health.json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "服务器健康状态读取失败")
    payload = json.loads(result.stdout)
    return {
        "healthy": bool(payload.get("healthy")),
        "checked_at": payload.get("checked_at"),
        "last_incident_at": payload.get("last_incident_at") or payload.get("incident_started_at"),
        "last_recovery_at": payload.get("last_recovery_at"),
        "repaired": bool(payload.get("repaired")),
        "manual_test_recommended": bool(payload.get("manual_test_recommended")),
    }


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


def resolve_recipient(recipient: str) -> str:
    if recipient != "self":
        return recipient
    environment = os.environ.copy()
    environment["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    environment["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    result = subprocess.run(
        [LARK, "auth", "status", "--json", "--verify"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "飞书身份解析失败")
    payload = json.loads(result.stdout)
    user = ((payload.get("identities") or {}).get("user") or {})
    open_id = str(user.get("openId") or "").strip()
    if not payload.get("verified") or user.get("status") != "ready" or not open_id:
        raise RuntimeError("当前飞书用户身份不可用")
    return open_id


def notify(recipient: str, message: str, key: str) -> dict:
    recipient = resolve_recipient(recipient)
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
    try:
        details["server_parser"] = check_server_parser_state()
    except Exception as exc:  # noqa: BLE001
        details["server_parser"] = {"monitoring_error": f"{type(exc).__name__}: {exc}"}
    details["elapsed_seconds"] = round(time.monotonic() - started, 2)

    stamp = now().strftime("%Y-%m-%d %H:%M:%S")
    previous = load_state(args.state_file)
    previous_count = int(previous.get("consecutive_failures", 0))
    alerted = bool(previous.get("alerted", False))
    notification: dict | None = None
    event_notifications: list[dict] = []
    notification_error = ""
    server_parser = details.get("server_parser") or {}
    server_incident_at = str(server_parser.get("last_incident_at") or "")
    server_recovery_at = str(server_parser.get("last_recovery_at") or "")
    previous_server_incident_at = str(previous.get("last_server_incident_at") or "")
    previous_server_recovery_at = str(previous.get("last_server_recovery_at") or "")
    new_server_incident = bool(server_incident_at and server_incident_at != previous_server_incident_at)
    new_server_recovery = bool(server_recovery_at and server_recovery_at != previous_server_recovery_at)
    incident_marker_delivered = not new_server_incident or not args.recipient_id

    if new_server_incident and args.recipient_id and not args.no_notify:
        try:
            receipt = notify(
                args.recipient_id,
                f"【视频号解析异常】{stamp}\n服务器于 {server_incident_at} 检测到解析服务异常，已进入自动修复流程。",
                f"parser-incident-{hashlib.sha256(server_incident_at.encode()).hexdigest()[:20]}",
            )
            event_notifications.append(receipt)
            notification = receipt
            incident_marker_delivered = True
        except Exception as exc:  # noqa: BLE001
            notification_error = f"{type(exc).__name__}: {exc}"

    if failures:
        count = previous_count + 1
        last_alert_epoch = int(previous.get("last_alert_epoch", 0))
        if incident_marker_delivered and new_server_incident:
            alerted = True
            last_alert_epoch = int(time.time())
        should_alert = count >= 2 and (not alerted or time.time() - last_alert_epoch >= 7200)
        if should_alert and args.recipient_id and not args.no_notify:
            message = f"【石董会官网告警】{stamp}\n连续 {count} 次巡检失败：" + "；".join(failures[:6])
            try:
                notification = notify(args.recipient_id, message, f"site-down-{int(time.time()) // 300}")
                event_notifications.append(notification)
                alerted = True
                last_alert_epoch = int(time.time())
            except Exception as exc:  # noqa: BLE001
                notification_error = f"{type(exc).__name__}: {exc}"
        state = {
            "status": "down",
            "checked_at": stamp,
            "consecutive_failures": count,
            "alerted": alerted,
            "last_alert_epoch": last_alert_epoch,
            "failures": failures,
            "details": details,
            "notification": notification,
            "event_notifications": event_notifications,
            "notification_error": notification_error,
            "last_server_incident_at": (
                server_incident_at
                if incident_marker_delivered and server_incident_at
                else previous_server_incident_at
            ),
            "last_server_recovery_at": previous_server_recovery_at,
        }
    else:
        recovery_marker_delivered = not new_server_recovery or not args.recipient_id
        if alerted and args.recipient_id and not args.no_notify:
            try:
                notification = notify(
                    args.recipient_id,
                    f"【石董会官网恢复】{stamp}\n公网和视频号解析固定样本已经恢复正常。请你打开社群官网，手动粘贴一条视频号链接再测试一次。",
                    f"site-recovered-{int(time.time()) // 300}",
                )
                event_notifications.append(notification)
                alerted = False
            except Exception as exc:  # noqa: BLE001
                notification_error = f"{type(exc).__name__}: {exc}"
        if new_server_recovery and args.recipient_id and not args.no_notify:
            try:
                receipt = notify(
                    args.recipient_id,
                    f"【视频号解析自动恢复】{stamp}\n服务器记录到解析服务曾发生异常，并已于 {server_recovery_at} 自动恢复。请你打开社群官网，手动粘贴一条视频号链接再测试一次。",
                    f"parser-auto-recovered-{hashlib.sha256(server_recovery_at.encode()).hexdigest()[:20]}",
                )
                event_notifications.append(receipt)
                notification = receipt
                recovery_marker_delivered = True
            except Exception as exc:  # noqa: BLE001
                suffix = f"{type(exc).__name__}: {exc}"
                notification_error = f"{notification_error}；{suffix}".strip("；")
        state = {
            "status": "healthy",
            "checked_at": stamp,
            "consecutive_failures": 0,
            "alerted": alerted,
            "details": details,
            "notification": notification,
            "event_notifications": event_notifications,
            "notification_error": notification_error,
            "last_server_incident_at": (
                server_incident_at
                if incident_marker_delivered and server_incident_at
                else previous_server_incident_at
            ),
            "last_server_recovery_at": (
                server_recovery_at if recovery_marker_delivered and server_recovery_at else previous_server_recovery_at
            ),
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
            "【石董会官网监控验收】外部 5 分钟巡检已启用：连续两次失败会告警，自动或人工恢复后会再次通知，并提醒你手动复测。",
            f"site-monitor-acceptance-{int(time.time()) // 300}",
        )
        print(json.dumps({"test_alert": True, "receipt": receipt}, ensure_ascii=False))
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
