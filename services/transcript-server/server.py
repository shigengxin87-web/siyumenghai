#!/usr/bin/env python3
import hashlib
import json
import os
import queue
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

HOST = os.environ.get("TRANSCRIPT_HOST", "127.0.0.1")
PORT = int(os.environ.get("TRANSCRIPT_PORT", "2026"))
DATA_DIR = Path(os.environ.get("TRANSCRIPT_DATA_DIR", "/var/lib/siyumenghai-transcriber"))
WORKER = os.environ.get("TRANSCRIPT_WORKER", "/opt/siyumenghai-transcriber/worker.py")
MAX_USER_ACTIVE = 2
MAX_USER_DAILY = 5
MAX_GLOBAL_DAILY = 30
MAX_QUEUE = 20
MAX_VIDEO_SECONDS = 600
CACHE_SECONDS = 7 * 86400
JOB_SECONDS = 86400

JOBS_DIR = DATA_DIR / "jobs"
CACHE_DIR = DATA_DIR / "cache"
TMP_DIR = DATA_DIR / "tmp"
COVERS_DIR = DATA_DIR / "covers"
for directory in (JOBS_DIR, CACHE_DIR, TMP_DIR, COVERS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

jobs = {}
pending = []
active_by_url = {}
current_job_id = None
work_queue = queue.Queue()
lock = threading.RLock()


def now():
    return int(time.time())


def today_key():
    return time.strftime("%Y-%m-%d", time.localtime())


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def job_path(job_id):
    return JOBS_DIR / f"{job_id}.json"


def cache_key(share_url):
    return hashlib.sha256(share_url.encode("utf-8")).hexdigest()


def cache_path(share_url):
    return CACHE_DIR / f"{cache_key(share_url)}.json"


def client_key(address):
    return hashlib.sha256(("siyumenghai:" + address).encode("utf-8")).hexdigest()[:24]


def valid_share_url(value):
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and host in {"weixin.qq.com", "channels.weixin.qq.com"}


def valid_video_url(value):
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host.endswith(".qq.com") or host.endswith(".qpic.cn") or host.endswith(".gtimg.com"))


def valid_image_url(value):
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host.endswith(".qq.com") or host.endswith(".qpic.cn")
        or host.endswith(".gtimg.com") or host.endswith(".qlogo.cn")
    )


def cover_paths(url):
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return COVERS_DIR / f"{key}.bin", COVERS_DIR / f"{key}.json"


def load_cover(url):
    image_path, meta_path = cover_paths(url)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if now() - int(meta.get("saved_at", 0)) <= CACHE_SECONDS and image_path.stat().st_size > 0:
            return image_path.read_bytes(), meta.get("content_type", "image/jpeg")
    except (OSError, ValueError):
        pass

    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://channels.weixin.qq.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    })
    with urlopen(request, timeout=20) as response:
        content_type = str(response.headers.get_content_type() or "")
        length = int(response.headers.get("Content-Length", "0") or 0)
        if not content_type.startswith("image/") or length > 5 * 1024 * 1024:
            raise RuntimeError("封面文件无效")
        data = response.read(5 * 1024 * 1024 + 1)
    if not data or len(data) > 5 * 1024 * 1024:
        raise RuntimeError("封面文件过大")
    temp = image_path.with_suffix(".tmp")
    temp.write_bytes(data)
    temp.replace(image_path)
    atomic_json(meta_path, {"saved_at": now(), "content_type": content_type})
    return data, content_type


def persist(job):
    atomic_json(job_path(job["id"]), job)


def load_cache(share_url):
    path = cache_path(share_url)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if now() - int(value.get("completed_at", 0)) > CACHE_SECONDS:
        path.unlink(missing_ok=True)
        return None
    return value


def public_job(job):
    with lock:
        status = job["status"]
        result = {
            "id": job["id"],
            "status": status,
            "stage": job.get("stage", ""),
            "created_at": job["created_at"],
            "max_video_seconds": MAX_VIDEO_SECONDS,
            "max_user_active": MAX_USER_ACTIVE,
        }
        if status == "queued":
            try:
                index = pending.index(job["id"])
            except ValueError:
                index = 0
            result["ahead"] = index + (1 if current_job_id else 0)
        elif status == "running":
            result["ahead"] = 0
        elif status == "completed":
            result.update({
                "text": job.get("text", ""),
                "duration": job.get("duration"),
                "elapsed": job.get("elapsed"),
                "model": job.get("model"),
                "cached": bool(job.get("cached")),
            })
        elif status == "error":
            result.update({"error": job.get("error", "识别失败"), "code": job.get("code", "failed")})
        return result


def active_count(owner):
    return sum(1 for job in jobs.values() if job.get("owner") == owner and job.get("status") in {"queued", "running"})


def daily_count(owner=None):
    day = today_key()
    return sum(1 for job in jobs.values() if job.get("day") == day and not job.get("cached") and (owner is None or job.get("owner") == owner))


def cleanup():
    cutoff_jobs = now() - JOB_SECONDS
    cutoff_cache = now() - CACHE_SECONDS
    for path in JOBS_DIR.glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if int(value.get("updated_at", 0)) < cutoff_jobs:
                path.unlink(missing_ok=True)
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
    for path in CACHE_DIR.glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if int(value.get("completed_at", 0)) < cutoff_cache:
                path.unlink(missing_ok=True)
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
    for path in COVERS_DIR.glob("*.json"):
        image_path = COVERS_DIR / f"{path.stem}.bin"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if int(value.get("saved_at", 0)) < cutoff_cache:
                path.unlink(missing_ok=True)
                image_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            image_path.unlink(missing_ok=True)


def load_jobs():
    for path in JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if job.get("status") in {"queued", "running"}:
            job.update(status="error", code="server_restarted", error="服务器重启，请重新提交", updated_at=now())
            atomic_json(path, job)
        jobs[job["id"]] = job


def worker_loop():
    global current_job_id
    while True:
        job_id = work_queue.get()
        with lock:
            job = jobs.get(job_id)
            if not job:
                work_queue.task_done()
                continue
            if job_id in pending:
                pending.remove(job_id)
            current_job_id = job_id
            job.update(status="running", stage="正在解析并下载音频", started_at=now(), updated_at=now())
            persist(job)

        job_dir = TMP_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        output_path = job_dir / "result.json"
        started = time.monotonic()
        try:
            process = subprocess.run(
                [
                    "/usr/bin/python3", WORKER, job["share_url"], str(job_dir), str(output_path), job["video_url"],
                    job.get("description", ""), job.get("author", ""),
                ],
                capture_output=True,
                text=True,
                timeout=3600,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            if process.returncode != 0:
                message = (process.stderr or process.stdout or "识别失败").strip().splitlines()[-1]
                code = "video_too_long" if "VIDEO_TOO_LONG" in message else "transcription_failed"
                if code == "video_too_long":
                    message = "视频超过 10 分钟，无法提交识别"
                raise RuntimeError(f"{code}|{message}")
            value = json.loads(output_path.read_text(encoding="utf-8"))
            elapsed = round(time.monotonic() - started, 1)
            completed = {
                "share_url": job["share_url"],
                "text": value["text"],
                "duration": value.get("duration"),
                "elapsed": elapsed,
                "model": value.get("model", "large-v3-turbo"),
                "completed_at": now(),
            }
            atomic_json(cache_path(job["share_url"]), completed)
            with lock:
                job.update(completed, status="completed", stage="识别完成", cached=False, updated_at=now())
                persist(job)
        except subprocess.TimeoutExpired:
            with lock:
                job.update(status="error", code="timeout", error="识别超时，请稍后重试", updated_at=now())
                persist(job)
        except Exception as error:
            raw = str(error)
            code, _, message = raw.partition("|")
            if not message:
                code, message = "transcription_failed", raw
            with lock:
                job.update(status="error", code=code, error=message[-300:], updated_at=now())
                persist(job)
        finally:
            subprocess.run(["/usr/bin/find", str(job_dir), "-type", "f", "!", "-name", "result.json", "-delete"], check=False)
            with lock:
                active_by_url.pop(job.get("share_url"), None)
                current_job_id = None
            work_queue.task_done()


class Handler(BaseHTTPRequestHandler):
    server_version = "SiyumenghaiTranscript/1.0"

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} {fmt % args}", flush=True)

    def send_json(self, status, value):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def owner(self):
        forwarded = self.headers.get("X-Real-IP", "").strip()
        return client_key(forwarded or self.client_address[0])

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/healthz":
            with lock:
                self.send_json(200, {
                    "ok": True, "model": "large-v3-turbo", "running": bool(current_job_id), "queued": len(pending),
                    "today": daily_count(), "daily_limit": MAX_GLOBAL_DAILY,
                    "user_daily_limit": MAX_USER_DAILY, "user_active_limit": MAX_USER_ACTIVE,
                    "max_video_seconds": MAX_VIDEO_SECONDS,
                })
            return
        if parsed_path.path == "/covers":
            url = parse_qs(parsed_path.query).get("url", [""])[0].strip()
            if not valid_image_url(url):
                self.send_json(400, {"error": "封面地址无效"})
                return
            try:
                data, content_type = load_cover(url)
            except Exception:
                self.send_json(502, {"error": "封面读取失败"})
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=604800, immutable")
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed_path.path.startswith("/jobs/"):
            job_id = parsed_path.path.split("/", 2)[2]
            with lock:
                job = jobs.get(job_id)
                if not job:
                    self.send_json(404, {"error": "任务不存在或已过期"})
                    return
                self.send_json(200, public_job(job))
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/jobs":
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 4096:
                raise ValueError("invalid body")
            body = json.loads(self.rfile.read(length))
            share_url = str(body.get("share_url", "")).strip()
            video_url = str(body.get("video_url", "")).strip()
            description = str(body.get("description", "")).strip()[:500]
            author = str(body.get("author", "")).strip()[:80]
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "请求格式不正确"})
            return
        if not valid_share_url(share_url):
            self.send_json(400, {"error": "请提交有效的视频号分享链接"})
            return
        if not valid_video_url(video_url):
            self.send_json(400, {"error": "视频文件地址无效或来源不受支持"})
            return

        owner = self.owner()
        with lock:
            duplicate_id = active_by_url.get(share_url)
            if duplicate_id and duplicate_id in jobs:
                self.send_json(200, public_job(jobs[duplicate_id]))
                return
            cached = load_cache(share_url)
            if cached:
                job_id = secrets.token_urlsafe(18)
                job = {
                    "id": job_id, "owner": owner, "status": "completed", "stage": "已读取缓存",
                    "share_url": share_url, "created_at": now(), "updated_at": now(), "cached": True, **cached,
                }
                jobs[job_id] = job
                persist(job)
                self.send_json(200, public_job(job))
                return
            if active_count(owner) >= MAX_USER_ACTIVE:
                self.send_json(429, {"error": "每人最多同时排队 2 条，请等待已有任务完成", "code": "user_limit"})
                return
            if daily_count(owner) >= MAX_USER_DAILY:
                self.send_json(429, {"error": "每人每天最多识别 5 条，请明天再试", "code": "user_daily_limit"})
                return
            if daily_count() >= MAX_GLOBAL_DAILY:
                self.send_json(503, {"error": "今日全站识别额度已用完，请明天再试", "code": "global_daily_limit"})
                return
            if len(pending) >= MAX_QUEUE:
                self.send_json(503, {"error": "当前排队人数较多，请稍后重试", "code": "queue_full"})
                return

            job_id = secrets.token_urlsafe(18)
            job = {
                "id": job_id, "owner": owner, "status": "queued", "stage": "等待识别",
                "share_url": share_url, "video_url": video_url,
                "description": description, "author": author,
                "created_at": now(), "updated_at": now(), "day": today_key(),
            }
            jobs[job_id] = job
            pending.append(job_id)
            active_by_url[share_url] = job_id
            persist(job)
            work_queue.put(job_id)
            self.send_json(202, public_job(job))


if __name__ == "__main__":
    load_jobs()
    cleanup()
    threading.Thread(target=worker_loop, daemon=True).start()
    print(f"transcript service listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
