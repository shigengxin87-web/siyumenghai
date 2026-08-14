#!/usr/bin/env python3
"""Isolated Tencent ASR job service for the 48-hour transcript test."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import secrets
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tencentcloud.asr.v20190614 import asr_client, models
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile


SERVICE = "siyumenghai-transcript-tencent-test"
PIPELINE_VERSION = "tencent-asr-2.0-raw-v1"
ENGINE = "16k_zh_en_2.0"
HOST = os.environ.get("TENCENT_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("TENCENT_TEST_PORT", "2032"))
DATA_DIR = Path(
    os.environ.get("TENCENT_TEST_DATA_DIR", "/var/lib/siyumenghai-transcript-tencent-test")
)
KEY_FILE = Path(
    os.environ.get("TENCENT_TEST_KEY_FILE", "/etc/siyumenghai-transcript-tencent-test.csv")
)
PROFILE_API = os.environ.get(
    "TENCENT_TEST_PROFILE_API", "https://siyumenghai.cn/api/video/profile"
)
TEST_EXPIRES_EPOCH = int(os.environ.get("TENCENT_TEST_EXPIRES_EPOCH", "0"))
MAX_VIDEO_SECONDS = int(os.environ.get("TENCENT_TEST_MAX_VIDEO_SECONDS", "600"))
MAX_BILLED_SECONDS = int(os.environ.get("TENCENT_TEST_MAX_BILLED_SECONDS", "3600"))
MAX_WORKERS = int(os.environ.get("TENCENT_TEST_MAX_WORKERS", "1"))
POLL_TIMEOUT_SECONDS = int(os.environ.get("TENCENT_TEST_POLL_TIMEOUT_SECONDS", "900"))
JOBS_DIR = DATA_DIR / "jobs"
CACHE_DIR = DATA_DIR / "cache"


LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="tencent-asr")
JOBS: dict[str, dict[str, Any]] = {}
STARTED_AT = time.time()


class PublicError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".tmp-{os.getpid()}-{threading.get_ident()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "share_url",
        "status",
        "stage",
        "created_at",
        "updated_at",
        "finished_at",
        "elapsed_seconds",
        "video_duration_seconds",
        "coverage_end_seconds",
        "char_count",
        "text",
        "error",
        "cache_hit",
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
    return value


def valid_media_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError as error:
        raise PublicError("视频解析结果无效，请重新查询。") from error
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        hostname == "video.qq.com" or hostname.endswith(".video.qq.com")
    ):
        raise PublicError("视频解析结果不是受信任的腾讯视频地址。")
    return value


def resolve_video(share_url: str) -> tuple[str, str]:
    query = urllib.parse.urlencode({"url": share_url})
    request = urllib.request.Request(
        f"{PROFILE_API}?{query}", headers={"User-Agent": f"{SERVICE}/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.load(response)
        feed = payload["data"]["data"]["feedInfo"]
    except Exception as error:  # noqa: BLE001 - converted to safe public message
        raise PublicError("视频解析暂时失败，请稍后重试。") from error
    video_url = (
        (feed.get("h264VideoInfo") or {}).get("videoUrl")
        or feed.get("videoUrl")
        or feed.get("originVideoUrl")
    )
    if not video_url:
        raise PublicError("视频解析成功，但没有取得完整视频地址。")
    return valid_media_url(str(video_url)), str(feed.get("description") or "")


def probe_duration(video_url: str) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_url,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        duration = float(result.stdout.strip())
    except Exception as error:  # noqa: BLE001
        raise PublicError("无法确认视频时长，请重新查询后再试。") from error
    if duration <= 0:
        raise PublicError("视频时长无效。")
    return duration


def cache_key(share_url: str) -> str:
    value = f"{PIPELINE_VERSION}\0{share_url}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def load_cache(share_url: str) -> dict[str, Any] | None:
    path = CACHE_DIR / f"{cache_key(share_url)}.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if (
        cached.get("share_url") != share_url
        or cached.get("pipeline_version") != PIPELINE_VERSION
        or not str(cached.get("text") or "").strip()
    ):
        return None
    return cached


def billed_seconds() -> float:
    total = 0.0
    for path in CACHE_DIR.glob("*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            total += float(item.get("video_duration_seconds") or 0)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    with LOCK:
        for job in JOBS.values():
            if job.get("status") in {"queued", "processing"}:
                total += float(job.get("video_duration_seconds") or 0)
    return total


def load_credentials() -> tuple[str, str]:
    with KEY_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    secret_id = str(row.get("SecretId") or "").strip()
    secret_key = str(row.get("SecretKey") or "").strip()
    if not secret_id or not secret_key:
        raise RuntimeError("credential file is incomplete")
    return secret_id, secret_key


def client() -> asr_client.AsrClient:
    secret_id, secret_key = load_credentials()
    cred = credential.Credential(secret_id, secret_key)
    http = HttpProfile()
    http.endpoint = "asr.tencentcloudapi.com"
    profile = ClientProfile(httpProfile=http)
    return asr_client.AsrClient(cred, "ap-guangzhou", profile)


def create_task(api: asr_client.AsrClient, video_url: str) -> int:
    request = models.CreateRecTaskRequest()
    request.from_json_string(
        json.dumps(
            {
                "EngineModelType": ENGINE,
                "ChannelNum": 1,
                "ResTextFormat": 3,
                "SourceType": 0,
                "Url": video_url,
                "SpeakerDiarization": 0,
                "ConvertNumMode": 1,
                "FilterDirty": 0,
                "FilterPunc": 0,
                "FilterModal": 0,
            },
            ensure_ascii=False,
        )
    )
    response = api.CreateRecTask(request)
    return int(response.Data.TaskId)


def poll_task(api: asr_client.AsrClient, task_id: int) -> dict[str, Any]:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        request = models.DescribeTaskStatusRequest()
        request.from_json_string(json.dumps({"TaskId": task_id}))
        response = api.DescribeTaskStatus(request)
        data = json.loads(response.Data.to_json_string())
        status = int(data.get("Status", -1))
        if status == 2:
            return data
        if status == 3:
            raise PublicError(f"识别失败：{data.get('ErrorMsg') or '上游任务失败'}")
        time.sleep(2)
    raise PublicError("识别等待超时，请稍后在历史任务中查看。")


def process(job_id: str) -> None:
    started = time.monotonic()
    job = update_job(job_id, status="processing", stage="正在解析视频", error="")
    try:
        share_url = str(job["share_url"])
        cached = load_cache(share_url)
        if cached:
            update_job(
                job_id,
                **{
                    key: cached.get(key)
                    for key in (
                        "text",
                        "char_count",
                        "video_duration_seconds",
                        "coverage_end_seconds",
                        "elapsed_seconds",
                    )
                },
                status="completed",
                stage="已完成",
                cache_hit=True,
                finished_at=now_iso(),
            )
            return

        video_url, description = resolve_video(share_url)
        update_job(job_id, stage="正在检查视频时长")
        duration = probe_duration(video_url)
        update_job(job_id, video_duration_seconds=round(duration, 3))
        if duration > MAX_VIDEO_SECONDS + 0.05:
            raise PublicError(
                f"视频时长 {duration / 60:.1f} 分钟，超过本次测试的10分钟上限；未提交识别，也没有截断。"
            )
        if billed_seconds() > MAX_BILLED_SECONDS:
            raise PublicError("48小时测试额度已用完，未产生本次识别费用。")

        update_job(job_id, stage="正在提交识别任务")
        api = client()
        upstream_id = create_task(api, video_url)
        update_job(job_id, stage="正在生成逐字稿", upstream_task_id=upstream_id)
        data = poll_task(api, upstream_id)
        text = str(data.get("Result") or "").strip()
        if not text:
            raise PublicError("识别任务已结束，但没有返回逐字稿。")
        details = data.get("ResultDetail") or []
        coverage_end = 0.0
        for detail in details:
            try:
                coverage_end = max(coverage_end, float(detail.get("EndMs") or 0) / 1000)
            except (TypeError, ValueError):
                continue
        elapsed = round(time.monotonic() - started, 3)
        finished = {
            "share_url": share_url,
            "description": description,
            "pipeline_version": PIPELINE_VERSION,
            "text": text,
            "char_count": len("".join(text.split())),
            "video_duration_seconds": round(duration, 3),
            "coverage_end_seconds": round(coverage_end, 3),
            "elapsed_seconds": elapsed,
            "cached_at": now_iso(),
        }
        atomic_json(CACHE_DIR / f"{cache_key(share_url)}.json", finished)
        update_job(
            job_id,
            **finished,
            status="completed",
            stage="已完成",
            cache_hit=False,
            finished_at=now_iso(),
        )
    except PublicError as error:
        update_job(
            job_id,
            status="failed",
            stage="处理失败",
            error=str(error),
            finished_at=now_iso(),
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
    except TencentCloudSDKException as error:
        update_job(
            job_id,
            status="failed",
            stage="接口调用失败",
            error=f"腾讯云接口错误：{error.code}",
            finished_at=now_iso(),
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
    except Exception:  # noqa: BLE001 - secrets and signed URLs must never reach clients
        update_job(
            job_id,
            status="failed",
            stage="服务异常",
            error="逐字稿服务暂时异常，请稍后重试。",
            finished_at=now_iso(),
            elapsed_seconds=round(time.monotonic() - started, 3),
        )


def enqueue(share_url: str) -> dict[str, Any]:
    if TEST_EXPIRES_EPOCH and time.time() >= TEST_EXPIRES_EPOCH:
        raise PublicError("48小时测试期已结束，当前不再接受新任务。")
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
        "video_duration_seconds": 0,
        "coverage_end_seconds": 0,
        "char_count": 0,
        "text": "",
        "error": "",
        "cache_hit": False,
        "pipeline_version": PIPELINE_VERSION,
    }
    with LOCK:
        JOBS[job_id] = job
        save_job(job)
    EXECUTOR.submit(process, job_id)
    return public_job(job)


def restore_jobs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    os.chmod(JOBS_DIR, 0o700)
    os.chmod(CACHE_DIR, 0o700)
    for path in JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        job_id = str(job.get("id") or "")
        if not job_id:
            continue
        JOBS[job_id] = job
    for job_id, job in list(JOBS.items()):
        if job.get("status") in {"queued", "processing"}:
            job["status"] = "queued"
            job["stage"] = "服务恢复后继续处理"
            save_job(job)
            EXECUTOR.submit(process, job_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "TranscriptTest/1.0"

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
                active = sum(
                    1 for job in JOBS.values() if job.get("status") in {"queued", "processing"}
                )
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": SERVICE,
                    "pipeline_version": PIPELINE_VERSION,
                    "active_jobs": active,
                    "uptime_seconds": round(time.time() - STARTED_AT),
                    "expires_at_epoch": TEST_EXPIRES_EPOCH,
                    "billed_seconds": round(billed_seconds(), 3),
                    "max_billed_seconds": MAX_BILLED_SECONDS,
                },
            )
            return
        if path.startswith("/jobs/"):
            job_id = path[len("/jobs/") :].strip("/")
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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    restore_jobs()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
