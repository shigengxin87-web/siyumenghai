#!/usr/bin/env python3
"""Isolated server-side WeChat Channels comment job service.

The browser submits only a public share URL. Provider credentials remain in a
root-readable file on the server and are never returned or logged.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable


SERVICE = "siyumenghai-video-comment-cloud"
PIPELINE_VERSION = "video-comment-cloud-v1"
HOST = os.environ.get("COMMENT_CLOUD_HOST", "127.0.0.1")
PORT = int(os.environ.get("COMMENT_CLOUD_PORT", "2033"))
DATA_DIR = Path(os.environ.get("COMMENT_CLOUD_DATA_DIR", "/var/lib/siyumenghai-video-comment-cloud"))
KEY_FILE = Path(os.environ.get("COMMENT_CLOUD_KEY_FILE", "/etc/siyumenghai-video-comment-cloud.key"))
PROVIDER_BASE = os.environ.get("COMMENT_CLOUD_PROVIDER_BASE", "https://api.getoneapi.com").rstrip("/")
DETAIL_PATH = "/api/wechat-channels-v2/fetch_video_detail"
COMMENTS_PATH = "/api/wechat-channels-v2/fetch_video_comment_list"
MAX_COMMENTS = int(os.environ.get("COMMENT_CLOUD_MAX_COMMENTS", "1000"))
MAX_PAGES = int(os.environ.get("COMMENT_CLOUD_MAX_PAGES", "50"))
MAX_ACTIVE_JOBS = int(os.environ.get("COMMENT_CLOUD_MAX_ACTIVE_JOBS", "3"))
MAX_PROVIDER_CALLS_PER_DAY = int(os.environ.get("COMMENT_CLOUD_MAX_PROVIDER_CALLS_PER_DAY", "100"))
CACHE_TTL_SECONDS = int(os.environ.get("COMMENT_CLOUD_CACHE_TTL_SECONDS", str(7 * 86400)))
PROVIDER_TIMEOUT_SECONDS = int(os.environ.get("COMMENT_CLOUD_PROVIDER_TIMEOUT_SECONDS", "90"))

JOBS_DIR = DATA_DIR / "jobs"
CACHE_DIR = DATA_DIR / "cache"
LEDGER_FILE = DATA_DIR / "provider-calls.json"
LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-comments")
JOBS: dict[str, dict[str, Any]] = {}
STARTED_AT = time.time()


class PublicError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".tmp-{os.getpid()}-{threading.get_ident()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def valid_share_url(value: str) -> str:
    value = value.strip()
    if len(value) > 500:
        raise PublicError("分享链接过长。")
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError as error:
        raise PublicError("请输入有效的视频号分享链接。") from error
    if parsed.scheme != "https" or parsed.hostname != "weixin.qq.com" or not parsed.path.startswith("/sph/"):
        raise PublicError("目前仅支持 https://weixin.qq.com/sph/ 开头的视频号分享链接。")
    return urllib.parse.urlunparse(("https", "weixin.qq.com", parsed.path.rstrip("/"), "", "", ""))


def cache_key(share_url: str) -> str:
    return hashlib.sha256(f"{PIPELINE_VERSION}\0{share_url}".encode()).hexdigest()


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "share_url", "status", "stage", "created_at", "updated_at", "finished_at",
        "elapsed_seconds", "comment_count", "reply_count", "comments", "error", "cache_hit",
        "pipeline_version",
    )
    return {key: job.get(key) for key in keys}


def save_job(job: dict[str, Any]) -> None:
    job["updated_at"] = now_iso()
    atomic_json(JOBS_DIR / f"{job['id']}.json", job)


def update_job(job_id: str, **changes: Any) -> dict[str, Any]:
    with LOCK:
        job = JOBS[job_id]
        job.update(changes)
        save_job(job)
        return dict(job)


def load_key() -> str:
    try:
        mode = KEY_FILE.stat().st_mode & 0o777
        if mode & 0o077:
            raise RuntimeError("credential file permissions are too broad")
        value = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError("credential file unavailable") from error
    if not value or len(value) > 1000 or any(char.isspace() for char in value):
        raise RuntimeError("credential file is invalid")
    return value


def read_ledger() -> dict[str, Any]:
    try:
        value = json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def provider_calls_today() -> int:
    ledger = read_ledger()
    return int(ledger.get("count") or 0) if ledger.get("date") == today_utc() else 0


def record_provider_success() -> None:
    with LOCK:
        count = provider_calls_today() + 1
        atomic_json(LEDGER_FILE, {"date": today_utc(), "count": count, "updated_at": now_iso()})


def provider_request(path: str, body: dict[str, Any]) -> dict[str, Any]:
    if MAX_PROVIDER_CALLS_PER_DAY > 0 and provider_calls_today() >= MAX_PROVIDER_CALLS_PER_DAY:
        raise PublicError("今日评论读取额度已达到安全上限，请明天再试。")
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{PROVIDER_BASE}{path}",
        data=encoded,
        method="POST",
        headers={
            "Authorization": f"Bearer {load_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"{SERVICE}/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=PROVIDER_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            raise PublicError("评论服务授权已失效，请联系管理员。") from error
        if error.code == 429:
            raise PublicError("评论请求较多，请稍后再试。") from error
        raise PublicError("评论服务暂时繁忙，请稍后再试。") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise PublicError("评论服务暂时繁忙，请稍后再试。") from error
    if not isinstance(payload, dict):
        raise PublicError("评论服务返回了无法识别的数据。")
    code = payload.get("code")
    if code is not None and int(code) != 200:
        message = str(payload.get("message") or payload.get("msg") or "").strip()
        if any(word in message.lower() for word in ("balance", "quota", "余额", "额度")):
            raise PublicError("评论服务额度不足，请联系管理员。")
        raise PublicError("评论服务暂时无法读取这条视频，请稍后再试。")
    record_provider_success()
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def first_value(value: Any, names: tuple[str, ...]) -> Any:
    for item in walk_dicts(value):
        for name in names:
            candidate = item.get(name)
            if candidate not in (None, ""):
                return candidate
    return None


def object_id_from_detail(detail: dict[str, Any]) -> str:
    value = first_value(detail, ("object_id", "objectId", "objectid"))
    if value in (None, ""):
        obj = first_value(detail, ("object", "feed"))
        if isinstance(obj, dict):
            value = obj.get("id")
    result = str(value or "").strip()
    if not result:
        raise PublicError("视频信息已取得，但没有返回评论所需的作品编号。")
    return result


def find_comment_list(value: Any) -> list[dict[str, Any]]:
    names = ("comment_list", "commentList", "comment_info", "commentInfo", "comments", "items", "list")
    for item in walk_dicts(value):
        for name in names:
            candidate = item.get(name)
            if isinstance(candidate, list) and all(isinstance(row, dict) for row in candidate):
                return candidate
    return []


def pick(item: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return value
    return default


def normalize_comment(item: dict[str, Any]) -> dict[str, Any]:
    author = pick(item, "authorContact", "author_contact", "author", default={})
    author = author if isinstance(author, dict) else {}
    region = pick(item, "ipRegionInfo", "ip_region_info", default={})
    region = region if isinstance(region, dict) else {}
    replies_raw = pick(
        item, "levelTwoComment", "level_two_comment", "reply_list", "replyList", "replies", default=[]
    )
    replies = [normalize_comment(reply) for reply in replies_raw if isinstance(reply, dict)] if isinstance(replies_raw, list) else []
    nickname = str(pick(item, "nickname", "nick_name", "user_name", "username") or pick(author, "nickname", "nick_name") or "匿名用户")
    return {
        "commentId": str(pick(item, "commentId", "comment_id", "id")),
        "content": str(pick(item, "content", "comment_content", "text", "replyContent")),
        "nickname": nickname,
        "likeCount": int(pick(item, "likeCount", "like_count", "like_num", default=0) or 0),
        "createtime": int(pick(item, "createtime", "create_time", "createTime", "timestamp", default=0) or 0),
        "ipRegionInfo": {"regionText": str(pick(region, "regionText", "region_text", "name"))},
        "replyNickname": str(pick(item, "replyNickname", "reply_nickname", "to_nickname")),
        "levelTwoComment": replies,
    }


def cursor_from_page(page: dict[str, Any]) -> str:
    value = first_value(page, ("last_buffer", "lastBuffer", "next_cursor", "nextCursor", "cursor"))
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value or "")


def has_more(page: dict[str, Any], cursor: str, item_count: int) -> bool:
    value = first_value(page, ("down_continue", "downContinue", "downContinueFlag", "has_more", "hasMore", "is_end"))
    if value is None:
        return bool(cursor and item_count)
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"false", "0", "no", "end"}:
            return False
        if value in {"true", "1", "yes"}:
            return True
    if first_value(page, ("is_end",)) is not None:
        return not bool(value)
    return bool(value)


def load_cache(share_url: str) -> dict[str, Any] | None:
    path = CACHE_DIR / f"{cache_key(share_url)}.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - path.stat().st_mtime
    except (OSError, json.JSONDecodeError):
        return None
    if age > CACHE_TTL_SECONDS or cached.get("share_url") != share_url or cached.get("pipeline_version") != PIPELINE_VERSION:
        return None
    return cached if isinstance(cached.get("comments"), list) else None


def fetch_comments(share_url: str, job_id: str) -> list[dict[str, Any]]:
    detail = provider_request(
        DETAIL_PATH,
        {"object_id": "", "export_id": "", "object_nonce_id": "", "share_url": share_url, "raw": False},
    )
    object_id = object_id_from_detail(detail)
    comments: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_cursors: set[str] = set()
    cursor = ""
    for _ in range(MAX_PAGES):
        update_job(job_id, stage=f"正在读取评论，已获得 {len(comments)} 条")
        page = provider_request(
            COMMENTS_PATH,
            {"object_id": object_id, "last_buffer": cursor, "comment_id": "", "raw": False},
        )
        rows = find_comment_list(page)
        for row in rows:
            normalized = normalize_comment(row)
            identity = normalized["commentId"] or hashlib.sha256(
                f"{normalized['nickname']}\0{normalized['createtime']}\0{normalized['content']}".encode()
            ).hexdigest()
            if identity not in seen_ids and len(comments) < MAX_COMMENTS:
                seen_ids.add(identity)
                comments.append(normalized)
        next_cursor = cursor_from_page(page)
        if len(comments) >= MAX_COMMENTS or not rows or not has_more(page, next_cursor, len(rows)):
            break
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return comments


def process(job_id: str) -> None:
    started = time.monotonic()
    job = update_job(job_id, status="processing", stage="正在读取视频信息", error="")
    try:
        share_url = str(job["share_url"])
        cached = load_cache(share_url)
        if cached:
            update_job(
                job_id,
                comments=cached["comments"],
                comment_count=cached["comment_count"],
                reply_count=cached["reply_count"],
                elapsed_seconds=round(time.monotonic() - started, 3),
                status="completed",
                stage="已完成",
                cache_hit=True,
                finished_at=now_iso(),
            )
            return
        comments = fetch_comments(share_url, job_id)
        reply_count = sum(len(item.get("levelTwoComment") or []) for item in comments)
        result = {
            "share_url": share_url,
            "pipeline_version": PIPELINE_VERSION,
            "comments": comments,
            "comment_count": len(comments),
            "reply_count": reply_count,
            "cached_at": now_iso(),
        }
        atomic_json(CACHE_DIR / f"{cache_key(share_url)}.json", result)
        update_job(
            job_id,
            **result,
            elapsed_seconds=round(time.monotonic() - started, 3),
            status="completed",
            stage="已完成",
            cache_hit=False,
            finished_at=now_iso(),
        )
    except PublicError as error:
        update_job(
            job_id, status="failed", stage="读取失败", error=str(error), finished_at=now_iso(),
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
    except Exception:
        update_job(
            job_id, status="failed", stage="服务异常", error="评论服务暂时异常，请稍后重试。",
            finished_at=now_iso(), elapsed_seconds=round(time.monotonic() - started, 3),
        )


def enqueue(share_url: str) -> dict[str, Any]:
    with LOCK:
        for existing in JOBS.values():
            if existing.get("share_url") == share_url and existing.get("status") in {"queued", "processing"}:
                return public_job(existing)
        active = sum(1 for job in JOBS.values() if job.get("status") in {"queued", "processing"})
        if active >= MAX_ACTIVE_JOBS:
            raise PublicError("当前评论任务较多，请稍后再试。")
        job_id = secrets.token_urlsafe(18)
        job = {
            "id": job_id,
            "share_url": share_url,
            "status": "queued",
            "stage": "等待处理",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "finished_at": "",
            "elapsed_seconds": 0,
            "comment_count": 0,
            "reply_count": 0,
            "comments": [],
            "error": "",
            "cache_hit": False,
            "pipeline_version": PIPELINE_VERSION,
        }
        JOBS[job_id] = job
        save_job(job)
    EXECUTOR.submit(process, job_id)
    return public_job(job)


def restore_jobs() -> None:
    for path in (DATA_DIR, JOBS_DIR, CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
    for path in JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        job_id = str(job.get("id") or "")
        if job_id:
            JOBS[job_id] = job
    for job_id, job in list(JOBS.items()):
        if job.get("status") in {"queued", "processing"}:
            job["status"] = "queued"
            job["stage"] = "服务恢复后继续处理"
            save_job(job)
            EXECUTOR.submit(process, job_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoComments/1.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/healthz":
            with LOCK:
                active = sum(1 for job in JOBS.values() if job.get("status") in {"queued", "processing"})
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": SERVICE,
                    "pipeline_version": PIPELINE_VERSION,
                    "active_jobs": active,
                    "provider_calls_today": provider_calls_today(),
                    "max_provider_calls_per_day": MAX_PROVIDER_CALLS_PER_DAY,
                    "uptime_seconds": round(time.time() - STARTED_AT),
                },
            )
            return
        if path.startswith("/jobs/"):
            job_id = path[len("/jobs/"):].strip("/")
            with LOCK:
                job = JOBS.get(job_id)
            if not job:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "任务不存在或已经清理。"})
                return
            self.send_json(HTTPStatus.OK, public_job(job))
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在。"})

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path != "/jobs":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在。"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 8192:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "请求内容无效。"})
            return
        try:
            body = json.loads(self.rfile.read(length))
            share_url = valid_share_url(str(body.get("share_url") or ""))
            job = enqueue(share_url)
        except (json.JSONDecodeError, PublicError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self.send_json(HTTPStatus.ACCEPTED, job)


def main() -> None:
    restore_jobs()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
