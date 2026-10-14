"""Loopback-only Xiaohongshu parser. It never logs input URLs or credentials."""

from __future__ import annotations

import html as html_module
import hmac
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yt_dlp
from lxml.etree import HTML, LxmlError


SECRET = os.environ["XHS_API_KEY"]
HOST = os.environ.get("XHS_HOST", "127.0.0.1")
PORT = int(os.environ.get("XHS_PORT", "2038"))
COOKIE_FILE = Path(os.environ.get("XHS_COOKIE_FILE", "/etc/siyumenghai-xhs/cookie.txt"))
ALLOWED_INPUT_HOSTS = {
    "www.xiaohongshu.com",
    "xiaohongshu.com",
    "xhslink.com",
    "www.xhslink.com",
    "xhslink.cn",
    "www.xhslink.cn",
}
URL_RE = re.compile(r'https://[^\s<>"“”]+', re.I)
STATE_PREFIX = "window.__INITIAL_STATE__"
LOCK = threading.Semaphore(2)
LAST_SUCCESS: str | None = None


class ParseError(Exception):
    pass


class QuietLogger:
    def debug(self, _message: str) -> None: pass
    def warning(self, _message: str) -> None: pass
    def error(self, _message: str) -> None: pass


def extract_url(value: Any) -> str:
    match = URL_RE.search(str(value or ""))
    if not match:
        raise ParseError("请粘贴小红书作品分享链接或包含链接的分享文案")
    raw = match.group(0).rstrip("，。！？；：、,.!?;:）)]}")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_INPUT_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ParseError("仅支持小红书 HTTPS 作品链接")
    return raw


def note_id_from_url(value: str) -> str:
    path = urlsplit(value).path
    match = re.search(r"/(?:explore|discovery/item)/([0-9a-f]{20,32})(?:/|$)", path, re.I)
    return match.group(1) if match else ""


def _cookie_header() -> str:
    try:
        value = COOKIE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return value if "\n" not in value and "\r" not in value else ""


def resolve_url(raw: str) -> str:
    parsed = urlsplit(raw)
    if parsed.hostname and parsed.hostname.endswith("xiaohongshu.com"):
        return raw
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
        "Accept": "text/html,application/xhtml+xml",
    }
    with httpx.Client(follow_redirects=True, timeout=15, headers=headers) as client:
        response = client.get(raw)
        response.raise_for_status()
    final = str(response.url)
    parsed = urlsplit(final)
    if parsed.scheme != "https" or parsed.hostname not in {"www.xiaohongshu.com", "xiaohongshu.com"}:
        raise ParseError("小红书分享链接跳转异常")
    return final


def _normalize_js(value: str) -> str:
    result: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(value):
        character = value[index]
        if quote:
            result.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if character in {'"', "'"}:
            quote = character
            result.append(character)
            index += 1
            continue
        if value[index:index + 9] == "undefined":
            before = value[index - 1] if index else ""
            after = value[index + 9] if index + 9 < len(value) else ""
            if not (before.isalnum() or before in "_$" or after.isalnum() or after in "_$"):
                result.append("null")
                index += 9
                continue
        result.append(character)
        index += 1
    return "".join(result)


def load_initial_state(document: str) -> dict[str, Any] | None:
    try:
        tree = HTML(document)
    except (LxmlError, TypeError, ValueError):
        return None
    if tree is None:
        return None
    scripts = [str(item).strip() for item in tree.xpath("//script/text()") if str(item).strip().startswith(STATE_PREFIX)]
    for script in reversed(scripts):
        try:
            raw = script[script.index("=") + 1:].strip().removesuffix(";")
            state = json.loads(_normalize_js(raw))
            if isinstance(state, dict):
                return state
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    return None


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _deep(value: Any, path: str, default: Any = "") -> Any:
    current = value
    for part in path.split("."):
        try:
            current = current[int(part)] if part.isdigit() else current[part]
        except (IndexError, KeyError, TypeError):
            return default
    return current if current is not None else default


def _decode_url(value: Any) -> str:
    return html_module.unescape(str(value or "")).replace("\\u002F", "/").replace("\\/", "/").replace("\\u0026", "&")


def _image_url(value: Any) -> str:
    parsed = urlsplit(_decode_url(value))
    path = parsed.path.lstrip("/")
    path = re.sub(r"^\d{12}/[0-9a-f]{32}/", "", path, count=1, flags=re.I).partition("!")[0]
    return f"https://sns-img-bd.xhscdn.com/{path}" if path else ""


def _select_note(state: dict[str, Any], note_id: str) -> dict[str, Any]:
    detail_map = _record(_record(state.get("note")).get("noteDetailMap"))
    direct = _record(detail_map.get(note_id))
    note = _record(direct.get("note"))
    if note:
        return note
    for wrapper in detail_map.values():
        candidate = _record(_record(wrapper).get("note"))
        if str(candidate.get("noteId", "")) == note_id:
            return candidate
    return {}


def _video_url(note: dict[str, Any]) -> str:
    origin = _deep(note, "video.consumer.originVideoKey")
    if origin:
        return f"https://sns-video-bd.xhscdn.com/{origin}"
    stream_groups = _deep(note, "video.media.stream", {})
    streams = [item for group in stream_groups.values() for item in _list(group)] if isinstance(stream_groups, dict) else []
    if not streams:
        return ""
    selected = max(streams, key=lambda item: float(item.get("videoBitrate") or item.get("height") or item.get("size") or 0))
    backups = selected.get("backupUrls")
    if isinstance(backups, list):
        first = next((item for item in backups if isinstance(item, str) and item), "")
        if first:
            return _decode_url(first)
    return _decode_url(selected.get("masterUrl"))


def parse_page(url: str) -> dict[str, Any]:
    note_id = note_id_from_url(url)
    if not note_id:
        raise ParseError("请粘贴具体作品链接，暂不支持主页或搜索页")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://www.xiaohongshu.com/",
    }
    cookie = _cookie_header()
    if cookie:
        headers["Cookie"] = cookie
    with httpx.Client(follow_redirects=True, timeout=20, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
    state = load_initial_state(response.text)
    note = _select_note(state or {}, note_id)
    if not note:
        raise ParseError("页面没有返回作品详情，请重新从小红书 App 复制最新分享链接")
    author = _record(note.get("user"))
    interact = _record(note.get("interactInfo"))
    images = []
    for item in _list(note.get("imageList"))[:100]:
        value = _image_url(item.get("urlDefault") or item.get("urlPre") or item.get("url"))
        if value:
            images.append(value)
    video = _video_url(note)
    return {
        "platform": "xiaohongshu",
        "id": note_id,
        "type": "video" if video else "image",
        "title": str(note.get("title") or "")[:500],
        "description": str(note.get("desc") or "")[:20000],
        "author": str(author.get("nickname") or ""),
        "created_at": note.get("time"),
        "stats": {
            "liked": interact.get("likedCount"),
            "collected": interact.get("collectedCount"),
            "commented": interact.get("commentCount"),
            "shared": interact.get("shareCount"),
        },
        "cover": images[0] if images else "",
        "video": video,
        "images": [] if video else images,
        "web_url": url,
    }


def parse_ytdlp(url: str) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "cachedir": False,
        "logger": QuietLogger(),
        "http_headers": {"Referer": "https://www.xiaohongshu.com/"},
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)
    if not isinstance(info, dict) or not info.get("url"):
        raise ParseError("作品没有可用的视频资源")
    note_id = str(info.get("id") or note_id_from_url(url))
    return {
        "platform": "xiaohongshu",
        "id": note_id,
        "type": "video",
        "title": str(info.get("title") or "")[:500],
        "description": str(info.get("description") or "")[:20000],
        "author": str(info.get("uploader") or info.get("channel") or ""),
        "created_at": info.get("timestamp"),
        "stats": {
            "liked": info.get("like_count"),
            "collected": None,
            "commented": info.get("comment_count"),
            "shared": None,
        },
        "cover": str(info.get("thumbnail") or ""),
        "video": str(info["url"]),
        "images": [],
        "web_url": url,
    }


def parse_work(raw: Any) -> dict[str, Any]:
    url = resolve_url(extract_url(raw))
    page_error: Exception | None = None
    try:
        return parse_page(url)
    except Exception as exc:
        page_error = exc
    try:
        return parse_ytdlp(url)
    except Exception:
        if isinstance(page_error, ParseError):
            raise page_error
        raise ParseError("暂时无法解析该作品，请使用最新的小红书 App 分享链接")


def envelope(success: bool, data: Any = None, message: str = "") -> bytes:
    body = {"success": success, "data": data} if success else {"success": False, "error": {"message": message}}
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "SiyumenghaiXHS/1"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, f"Bearer {SECRET}")

    def do_GET(self) -> None:
        if not self._authorized():
            return self._send(401, envelope(False, message="未授权"))
        if urlsplit(self.path).path != "/health":
            return self._send(404, envelope(False, message="接口不存在"))
        self._send(200, envelope(True, {"engine": "xhs-cloud", "last_success": LAST_SUCCESS, "mac_required": False}))

    def do_POST(self) -> None:
        global LAST_SUCCESS
        if not self._authorized():
            return self._send(401, envelope(False, message="未授权"))
        if urlsplit(self.path).path != "/parse":
            return self._send(404, envelope(False, message="接口不存在"))
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 16384:
                raise ParseError("输入内容过长或为空")
            body = json.loads(self.rfile.read(length))
            if not LOCK.acquire(blocking=False):
                return self._send(429, envelope(False, message="当前解析任务较多，请稍后重试"))
            try:
                result = parse_work(body.get("url"))
            finally:
                LOCK.release()
            from datetime import datetime, timezone
            LAST_SUCCESS = datetime.now(timezone.utc).isoformat()
            self._send(200, envelope(True, result))
        except ParseError as exc:
            self._send(422, envelope(False, message=str(exc)))
        except (json.JSONDecodeError, TypeError, ValueError):
            self._send(400, envelope(False, message="请求格式无效"))
        except Exception:
            self._send(502, envelope(False, message="小红书解析服务暂时不可用"))


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
