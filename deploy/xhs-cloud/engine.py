"""Loopback-only Xiaohongshu parser. It never logs input URLs or credentials."""

from __future__ import annotations

import html as html_module
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import string
import threading
import time
import zlib
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
WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0"
)
# Parse cache: hit path skips page/browser/ytdlp entirely. The DB lives under a
# directory the systemd unit mounts read-write; every cache operation is
# best-effort and must never break a live parse.
CACHE_DB = os.environ.get("XHS_CACHE_DB", "/var/lib/siyumenghai-xhs-engine/parse_cache.db")
CACHE_TTL = int(os.environ.get("XHS_CACHE_TTL_SECONDS", str(6 * 3600)))
_CACHE_LOCK = threading.Lock()


def _cache_connect() -> sqlite3.Connection:
    connection = sqlite3.connect(CACHE_DB, timeout=5)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS xhs_parse_records (
            note_id TEXT PRIMARY KEY,
            original_url TEXT NOT NULL,
            data TEXT NOT NULL,
            parsed_at REAL NOT NULL,
            expire_at REAL NOT NULL
        )
        """
    )
    return connection


def cache_lookup(note_id: str) -> dict[str, Any] | None:
    """Return the cached shaped result for a note, or None on miss/expiry/error."""
    if not note_id or CACHE_TTL <= 0:
        return None
    now = time.time()
    try:
        with _CACHE_LOCK, _cache_connect() as db:
            row = db.execute(
                "SELECT data, expire_at, parsed_at FROM xhs_parse_records WHERE note_id = ?",
                (note_id,),
            ).fetchone()
            if not row:
                return None
            if float(row[1]) < now or float(row[2]) + CACHE_TTL < now:
                db.execute("DELETE FROM xhs_parse_records WHERE note_id = ?", (note_id,))
                return None
            result = json.loads(row[0])
            return result if isinstance(result, dict) and result.pop("_cache_schema", None) == 2 else None
    except (sqlite3.Error, ValueError, TypeError, OSError):
        return None


def cache_store(note_id: str, original_url: str, result: dict[str, Any]) -> None:
    if not note_id or CACHE_TTL <= 0:
        return
    now = time.time()
    try:
        with _CACHE_LOCK, _cache_connect() as db:
            db.execute("DELETE FROM xhs_parse_records WHERE expire_at < ?", (now,))
            db.execute(
                "INSERT OR REPLACE INTO xhs_parse_records "
                "(note_id, original_url, data, parsed_at, expire_at) VALUES (?, ?, ?, ?, ?)",
                (note_id, original_url, json.dumps({**result, "_cache_schema": 2}, ensure_ascii=False), now, now + CACHE_TTL),
            )
    except (sqlite3.Error, ValueError, TypeError, OSError):
        return


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


def user_id_from_url(value: str) -> str:
    path = urlsplit(value).path
    match = re.search(r"/user/profile/([0-9a-zA-Z_-]{6,64})(?:/|$)", path)
    return match.group(1) if match else ""


def _cookie_header() -> str:
    try:
        value = COOKIE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return value if "\n" not in value and "\r" not in value else ""


def _synthetic_a1() -> str:
    """Build the same shaped anonymous device cookie used by XHS web clients."""
    timestamp = format(int(time.time() * 1000), "x")
    random_part = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(30))
    base = f"{timestamp}{random_part}50000"
    checksum = zlib.crc32(base.encode("utf-8")) & 0xFFFFFFFF
    return f"{base}{checksum}"[:52]


def _apply_cookie_header(client: httpx.Client, value: str) -> None:
    for part in value.split(";"):
        name, separator, cookie_value = part.strip().partition("=")
        if separator and name and cookie_value:
            client.cookies.set(name, cookie_value, domain=".xiaohongshu.com", path="/")


def _cookie_value(client: httpx.Client, name: str) -> str:
    return next((cookie.value for cookie in client.cookies.jar if cookie.name == name and cookie.value), "")


def _page_client() -> httpx.Client:
    """Create a fresh anonymous web session without inheriting host proxy settings."""
    client = httpx.Client(
        follow_redirects=False,
        timeout=20,
        trust_env=False,
        headers={
            "User-Agent": WEB_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
            "Accept-Encoding": "gzip",
        },
    )
    configured_cookie = _cookie_header()
    if configured_cookie:
        _apply_cookie_header(client, configured_cookie)
    try:
        client.get("https://www.xiaohongshu.com/explore")
    except httpx.HTTPError:
        pass
    a1 = _cookie_value(client, "a1")
    if not a1:
        a1 = _synthetic_a1()
        client.cookies.set("a1", a1, domain=".xiaohongshu.com", path="/")
    if not _cookie_value(client, "webId"):
        web_id = hashlib.md5(a1.encode("utf-8"), usedforsecurity=False).hexdigest()
        client.cookies.set("webId", web_id, domain=".xiaohongshu.com", path="/")
    return client


def resolve_url(raw: str) -> str:
    """Resolve XHS shortlinks without contacting unrelated redirect targets."""
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_INPUT_HOSTS:
        raise ParseError("仅支持小红书 HTTPS 作品链接")
    if parsed.hostname in {"xiaohongshu.com", "www.xiaohongshu.com"}:
        return raw

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
        "Accept": "text/html,application/xhtml+xml",
    }
    # Follow only platform-owned redirects. Never let public inputs access
    # arbitrary endpoints through a shortlink resolution service.
    with httpx.Client(follow_redirects=False, timeout=15, headers=headers, trust_env=False) as client:
        current = raw
        for _ in range(6):
            response = client.get(current)
            if response.status_code not in (301, 302, 303, 307, 308):
                raise ParseError("小红书分享链接跳转异常")
            location = response.headers.get("location", "")
            if not location:
                raise ParseError("小红书分享链接跳转异常")
            from urllib.parse import urljoin
            target = urljoin(current, location)
            destination = urlsplit(target)
            if (
                destination.scheme != "https"
                or destination.hostname not in ALLOWED_INPUT_HOSTS
                or destination.username
                or destination.password
                or destination.port not in (None, 443)
            ):
                raise ParseError("小红书分享链接跳转异常")
            if destination.hostname in {"xiaohongshu.com", "www.xiaohongshu.com"}:
                return target
            current = target
    raise ParseError("小红书分享链接跳转次数过多")


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
    stream_groups = _deep(note, "video.media.stream", {})
    streams = [{**item, "_group": name} for name, group in stream_groups.items() for item in _list(group)] if isinstance(stream_groups, dict) else []
    if not streams:
        return f"https://sns-video-bd.xhscdn.com/{origin}" if origin else ""
    # A higher-bitrate HEVC rendition may be video-only. Preserve sound first,
    # then prefer widely playable AVC and the best resolution in that group.
    def score(item):
        codec = str(item.get("videoCodec") or item.get("_group") or "").lower()
        audio = bool(item.get("audioCodec") or float(item.get("audioBitrate") or 0) > 0)
        compatible = codec in {"ef4", "h264", "avc", "avc1"}
        return (audio, compatible, float(item.get("height") or 0), float(item.get("videoBitrate") or 0))
    selected = max(streams, key=score)
    # XHS publishes http:// CDN URLs even though the same media supports
    # HTTPS. The public gateway accepts HTTPS only, so normalize media URLs.
    candidates = selected.get("backupUrls") or []
    if not isinstance(candidates, list):
        candidates = []
    candidates = [*candidates, selected.get("masterUrl")]
    for candidate in candidates:
        raw = _decode_url(candidate)
        if not raw:
            continue
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme in ("http", "https")
            and (host == "xhscdn.com" or host.endswith(".xhscdn.com"))
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 80, 443)
        ):
            from urllib.parse import urlunsplit
            return urlunsplit(("https", parsed.hostname, parsed.path, parsed.query, parsed.fragment))
    return ""


def parse_page(url: str) -> dict[str, Any]:
    note_id = note_id_from_url(url)
    if not note_id:
        raise ParseError("请粘贴具体作品链接，暂不支持主页或搜索页")
    # A direct visit returns server-rendered note data. Supplying an in-site
    # Referer makes Xiaohongshu treat this as SPA navigation and may redirect
    # anonymous visitors to login, so this request intentionally has none.
    client = _page_client()
    try:
        response = client.get(url)
        if response.is_redirect:
            raise ParseError("小红书拒绝了当前分享链接，请从 App 重新复制最新链接")
        response.raise_for_status()
    finally:
        client.close()
    state = load_initial_state(response.text)
    note = _select_note(state or {}, note_id)
    if not note:
        raise ParseError("页面没有返回作品详情，请重新从小红书 App 复制最新分享链接")
    return shape_note(url, note_id, note)


def shape_note(url: str, note_id: str, note: dict[str, Any]) -> dict[str, Any]:
    author = _record(note.get("user"))
    interact = _record(note.get("interactInfo"))
    images = []
    for item in _list(note.get("imageList"))[:100]:
        value = _image_url(item.get("urlDefault") or item.get("urlPre") or item.get("url"))
        if value:
            images.append(value)
    video = _video_url(note)
    duration = _deep(note, "video.capa.duration", None)
    return {
        "platform": "xiaohongshu",
        "id": note_id,
        "type": "video" if video else "image",
        "title": str(note.get("title") or "")[:500],
        "description": str(note.get("desc") or "")[:20000],
        "author": str(author.get("nickname") or ""),
        "created_at": note.get("time"),
        "duration": duration,
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


def _note_cover(item: dict[str, Any]) -> str:
    """Extract a proxy-able cover URL from a user-note-list entry."""
    cover_node = item.get("cover")
    candidates: list[Any] = []
    if isinstance(cover_node, dict):
        candidates = [cover_node.get("urlDefault"), cover_node.get("url"), cover_node.get("urlPre")]
        info_list = cover_node.get("infoList")
        if isinstance(info_list, list):
            candidates += [entry.get("url") for entry in info_list if isinstance(entry, dict)]
    images = item.get("imageList")
    if isinstance(images, list) and images:
        first = images[0] if isinstance(images[0], dict) else {}
        candidates += [first.get("urlDefault"), first.get("urlPre"), first.get("url")]
    for candidate in candidates:
        value = _image_url(candidate)
        if value:
            return value
    return ""


def _walk_notes(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect note-like entries from __INITIAL_STATE__, dedup by noteId."""
    seen: dict[str, dict[str, Any]] = {}
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            note_id = str(node.get("noteId") or "")
            if re.fullmatch(r"[0-9a-f]{20,32}", note_id, re.I) and (
                node.get("cover") is not None or node.get("imageList") or node.get("video")
            ):
                seen.setdefault(note_id.lower(), node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(state)
    return list(seen.values())[:30]


def shape_author(user_id: str, url: str, state_or_notes: dict[str, Any]) -> dict[str, Any]:
    if isinstance(state_or_notes, dict) and "noteId" not in state_or_notes:
        notes_raw = _walk_notes(state_or_notes)
    else:
        notes_raw = [state_or_notes]
    nickname = _deep(state_or_notes, "user.nickname", "") or _deep(state_or_notes, "user.userPageData.user.nickname", "")
    items = []
    for item in notes_raw:
        nid = str(item.get("noteId") or "")
        if not nid:
            continue
        has_video = bool(item.get("video")) or str(item.get("type") or "").lower() == "video"
        items.append({
            "id": nid,
            "type": "video" if has_video else "image",
            "title": str(item.get("displayTitle") or item.get("title") or "")[:200],
            "cover": _note_cover(item),
            "time": item.get("time") or item.get("lastUpdateTime"),
            "web_url": f"https://www.xiaohongshu.com/explore/{nid}",
        })
    return {
        "platform": "xiaohongshu",
        "kind": "author",
        "author": {
            "id": user_id,
            "nickname": str(nickname or ""),
            "web_url": url,
        },
        "notes": items,
    }


def parse_author_page(url: str) -> dict[str, Any]:
    user_id = user_id_from_url(url)
    if not user_id:
        raise ParseError("请粘贴博主主页链接")
    client = _page_client()
    try:
        response = client.get(url)
        if response.is_redirect:
            raise ParseError("小红书拒绝了当前博主主页链接，请从 App 重新复制")
        response.raise_for_status()
    finally:
        client.close()
    state = load_initial_state(response.text)
    notes = _walk_notes(state or {})
    if not notes:
        raise ParseError("博主主页没有返回作品列表")
    return shape_author(user_id, url, state or {})


def parse_author_browser(url: str) -> dict[str, Any]:
    user_id = user_id_from_url(url)
    if not user_id:
        raise ParseError("请粘贴博主主页链接")
    node = os.environ.get("XHS_NODE_BIN", "/opt/siyumenghai-xhs-cloud/runtime/node")
    parser = os.environ.get("XHS_AUTHOR_PARSER", "/opt/siyumenghai-xhs-cloud/browser_author.mjs")
    try:
        process = subprocess.run(
            [node, parser], input=json.dumps({"url": url}),
            capture_output=True, text=True, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ParseError("云端浏览器暂时无法读取博主主页") from None
    if process.returncode != 0 or not process.stdout or len(process.stdout) > 4_000_000:
        raise ParseError("云端浏览器未返回博主作品内容")
    try:
        payload = json.loads(process.stdout)
    except (ValueError, TypeError):
        raise ParseError("云端浏览器返回格式异常") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("notes"), list):
        raise ParseError("云端浏览器返回格式异常")
    return shape_author(user_id, url, payload)


# Short-lived cache for author lists: notes move slowly, but a re-submit should
# feel near-instant. Best-effort, in-process.
AUTHOR_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
AUTHOR_TTL = 600


def parse_work_author(raw: Any, url: str = "") -> dict[str, Any]:
    if not url:
        url = resolve_url(extract_url(raw))
    user_id = user_id_from_url(url)
    if not user_id:
        raise ParseError("请粘贴博主主页链接")
    cached = AUTHOR_CACHE.get(user_id.lower())
    if cached and time.time() - cached[0] < AUTHOR_TTL:
        result = dict(cached[1])
        result["author"] = {**cached[1]["author"], "web_url": url}
        result["cached"] = True
        return result
    try:
        result = parse_author_page(url)
    except Exception:
        result = parse_author_browser(url)
    AUTHOR_CACHE[user_id.lower()] = (time.time(), result)
    if len(AUTHOR_CACHE) > 200:
        AUTHOR_CACHE.pop(next(iter(AUTHOR_CACHE)))
    return result


def parse_browser(url: str) -> dict[str, Any]:
    """Read the requested public note from the existing loopback-only cloud browser."""
    note_id = note_id_from_url(url)
    if not note_id:
        raise ParseError("请粘贴具体作品链接")
    node = os.environ.get("XHS_NODE_BIN", "/opt/siyumenghai-xhs-cloud/runtime/node")
    parser = os.environ.get("XHS_BROWSER_PARSER", "/opt/siyumenghai-xhs-cloud/browser_parser.mjs")
    try:
        process = subprocess.run(
            [node, parser], input=json.dumps({"url": url}),
            capture_output=True, text=True, timeout=38, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ParseError("云端浏览器暂时无法读取作品") from None
    if process.returncode != 0 or not process.stdout or len(process.stdout) > 2_000_000:
        raise ParseError("云端浏览器未返回作品内容")
    try:
        note = json.loads(process.stdout)
    except (ValueError, TypeError):
        raise ParseError("云端浏览器返回格式异常") from None
    if not isinstance(note, dict) or str(note.get("noteId", "")).lower() != note_id.lower():
        raise ParseError("作品标识不匹配")
    return shape_note(url, note_id, note)


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


def parse_work(raw: Any, refresh: bool = False) -> dict[str, Any]:
    url = resolve_url(extract_url(raw))
    if user_id_from_url(url):
        return parse_work_author(raw, url)
    note_id = note_id_from_url(url)
    cached = cache_lookup(note_id) if note_id and not refresh else None
    if cached is not None:
        # Re-point the web link at the freshly resolved URL so xsec_token stays
        # valid, while all heavy media metadata comes from the cache.
        cached["web_url"] = url
        cached["cached"] = True
        return cached
    # Browser is the working fast path on this deployment. HTTP is a fallback,
    # not a failed request paid for on every cache miss.
    stages = [("browser", parse_browser), ("http", parse_page)]
    if os.environ.get("XHS_PARSE_PRIMARY") == "http":
        stages.reverse()
    if os.environ.get("XHS_YTDLP_FALLBACK") == "1":
        stages.append(("ytdlp", parse_ytdlp))
    result = None
    for stage_name, stage in stages:
        started = time.monotonic()
        try:
            result = stage(url)
            print(json.dumps({"stage": stage_name, "ok": True,
                              "seconds": round(time.monotonic() - started, 3)}), flush=True)
            break
        except Exception:
            print(json.dumps({"stage": stage_name, "ok": False,
                              "seconds": round(time.monotonic() - started, 3)}), flush=True)
    if result is None:
        raise ParseError("暂时无法读取作品，请重新复制最新分享链接后重试")
    cache_store(note_id, url, result)
    return result


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
                result = parse_work(body.get("url"), refresh=body.get("refresh") is True)
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
