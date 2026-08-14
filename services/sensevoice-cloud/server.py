#!/usr/bin/env python3
"""Queued SenseVoice + visual subtitle OCR + DeepSeek transcript service."""

import hashlib
import difflib
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import numpy as np
import sherpa_onnx

from deepseek_correction import (
    PROMPT_VERSION, cache_discriminator, configured_model, correct_text,
    deterministic_diff,
)


HOST = os.environ.get("SV_CLOUD_HOST", "127.0.0.1")
PORT = int(os.environ.get("SV_CLOUD_PORT", "2031"))
DATA_DIR = Path(os.environ.get("SV_CLOUD_DATA_DIR", "/var/lib/siyumenghai-sensevoice-cloud-test"))
MODEL_DIR = DATA_DIR / "models" / "sensevoice-small-int8"
MODEL = MODEL_DIR / "model.int8.onnx"
TOKENS = MODEL_DIR / "tokens.txt"
VAD_MODEL = MODEL_DIR / "silero_vad.onnx"
JOBS_DIR = DATA_DIR / "jobs"
CACHE_DIR = DATA_DIR / "cache"
TMP_DIR = DATA_DIR / "tmp"

MAX_VIDEO_SECONDS = 600
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
MIN_FREE_BYTES = 3 * 1024 * 1024 * 1024
JOB_TTL_SECONDS = 3 * 86400
CACHE_TTL_SECONDS = 7 * 86400
PIPELINE_VERSION = "sensevoice-small-int8-visual-proof-v2"
NUM_THREADS = 2
OCR_WORKER = Path(os.environ.get(
    "SV_CLOUD_OCR_WORKER", "/opt/siyumenghai-sensevoice-cloud-test/ocr_worker.py"
))
OCR_RUNTIME = os.environ.get(
    "SV_CLOUD_OCR_RUNTIME", "/opt/siyumenghai-transcriber/ocr-runtime"
)

for directory in (JOBS_DIR, CACHE_DIR, TMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)

jobs = {}
pending = []
active_by_url = {}
work_queue = queue.Queue()
lock = threading.RLock()
current_job_id = None


def now():
    return int(time.time())


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def persist(job):
    atomic_json(JOBS_DIR / f"{job['id']}.json", job)


def cache_path(share_url):
    material = PIPELINE_VERSION + "\n" + cache_discriminator() + "\n" + share_url
    digest = hashlib.sha256(material.encode()).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def valid_share_url(value):
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in {
        "weixin.qq.com", "channels.weixin.qq.com"
    }


def valid_video_url(value):
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == suffix or host.endswith("." + suffix)
        for suffix in ("qq.com", "qpic.cn", "gtimg.com")
    )


def public_job(job):
    status = job.get("status", "error")
    ahead = 0
    if status == "queued":
        try:
            ahead = pending.index(job["id"]) + (1 if current_job_id else 0)
        except ValueError:
            ahead = 0
    return {
        "id": job.get("id", ""),
        "status": status,
        "stage": job.get("stage", ""),
        "ahead": ahead,
        "text": job.get("text", ""),
        "raw_text": job.get("raw_text", job.get("text", "")),
        "corrected_text": job.get("corrected_text", ""),
        "segments": job.get("segments", []),
        "raw_segments": job.get("raw_segments", []),
        "elapsed": job.get("elapsed"),
        "asr_elapsed": job.get("asr_elapsed"),
        "correction_elapsed": job.get("correction_elapsed"),
        "total_elapsed": job.get("total_elapsed", job.get("elapsed")),
        "correction_status": job.get("correction_status", "pending"),
        "correction_error": job.get("correction_error", ""),
        "correction_changes": job.get("correction_changes", []),
        "correction_count": int(job.get("correction_count", 0) or 0),
        "correction_model": job.get("correction_model", configured_model()),
        "correction_actual_model": job.get("correction_actual_model", ""),
        "prompt_version": job.get("prompt_version", PROMPT_VERSION),
        "correction_parameters": job.get("correction_parameters", {}),
        "ocr_elapsed": job.get("ocr_elapsed"),
        "ocr_source": job.get("ocr_source", "unavailable"),
        "ocr_model": job.get("ocr_model", "unavailable"),
        "visual_evidence_available": bool(job.get("visual_subtitles", "").strip()),
        "visual_correction_count": int(job.get("visual_correction_count", 0) or 0),
        "error": job.get("error", ""),
        "duration": job.get("duration"),
        "cached": bool(job.get("cached", False)),
        "max_video_seconds": MAX_VIDEO_SECONDS,
    }


def load_cache(share_url):
    path = cache_path(share_url)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if now() - int(value.get("completed_at", 0)) > CACHE_TTL_SECONDS:
            path.unlink(missing_ok=True)
            return None
        return value
    except (OSError, ValueError):
        return None


def cleanup_expired():
    for directory, ttl, timestamp_key in (
        (JOBS_DIR, JOB_TTL_SECONDS, "updated_at"),
        (CACHE_DIR, CACHE_TTL_SECONDS, "completed_at"),
    ):
        cutoff = now() - ttl
        for path in directory.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if int(value.get(timestamp_key, 0)) < cutoff:
                    path.unlink(missing_ok=True)
            except (OSError, ValueError):
                path.unlink(missing_ok=True)
    cutoff_tmp = now() - 6 * 3600
    for path in TMP_DIR.iterdir():
        try:
            if path.stat().st_mtime < cutoff_tmp:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
        except OSError:
            pass


def load_jobs():
    for path in JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if job.get("status") in {"queued", "running"}:
            job.update(status="error", stage="任务中止", error="测试服务曾重启，请重新提交", updated_at=now())
            atomic_json(path, job)
        jobs[job["id"]] = job


def run(command, timeout):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=True)


def download_video(url, destination):
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://channels.weixin.qq.com/",
        "Accept": "video/mp4,video/*;q=0.9,*/*;q=0.1",
        "Accept-Encoding": "identity",
    })
    transferred = 0
    with urlopen(request, timeout=45) as response, destination.open("wb") as output:
        if not valid_video_url(response.geturl()):
            raise RuntimeError("视频跳转地址无效")
        content_length = int(response.headers.get("Content-Length", "0") or 0)
        if content_length > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("视频文件过大")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            transferred += len(chunk)
            if transferred > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("视频文件过大")
            output.write(chunk)
    if transferred < 1024:
        raise RuntimeError("视频下载不完整")
    return transferred


def media_duration(path):
    result = run([
        "/usr/bin/ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ], 60)
    return float(result.stdout.strip())


def extract_pcm(video_path, pcm_path):
    run([
        "/usr/bin/ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", str(pcm_path),
    ], 600)


def normalize_text(value):
    text = str(value or "")
    text = re.sub(r"<\|[^|]+\|>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", text)
    return text


def chinese_visual_text(value):
    """Keep spoken Chinese subtitle evidence and discard English/UI-only OCR."""
    output = []
    seen = set()
    for item in value.get("segments", []):
        text = str(item.get("text", ""))
        text = re.sub(r"[A-Za-z][A-Za-z0-9'’._-]*", "", text)
        text = re.sub(r"[^0-9\u3400-\u9fff，。！？、；：%％]+", "", text).strip("，。！？、；：")
        if len(re.findall(r"[\u3400-\u9fff]", text)) < 2:
            continue
        comparable = re.sub(r"[^0-9\u3400-\u9fff]", "", text)
        if comparable in seen:
            continue
        seen.add(comparable)
        output.append(f"[{float(item.get('start', 0)):.2f}s] {text}")
    return "\n".join(output)


def comparable_with_positions(value):
    characters = []
    positions = []
    for index, character in enumerate(str(value or "")):
        if re.match(r"[0-9A-Za-z\u3400-\u9fff]", character):
            characters.append(character.lower())
            positions.append(index)
    return "".join(characters), positions


def clean_visual_fragment(value):
    text = re.sub(r"[A-Za-z][A-Za-z0-9'’._-]*", "", str(value or ""))
    return re.sub(r"[^0-9\u3400-\u9fff]+", "", text)


def visual_correct_segments(raw_segments, ocr_value):
    """Apply only short OCR replacements with strong matching context on both sides."""
    ocr_segments = [
        item for item in ocr_value.get("segments", [])
        if float(item.get("confidence", 0) or 0) >= 0.85 and clean_visual_fragment(item.get("text", ""))
    ]
    output = []
    accepted = []
    for segment in raw_segments:
        current = dict(segment)
        source = str(current.get("text", ""))
        start = float(current.get("start", 0))
        end = float(current.get("end", start))
        nearby = [
            item for item in ocr_segments
            if float(item.get("end", 0)) >= start - 0.45
            and float(item.get("start", 0)) <= end + 0.45
        ]
        evidence = "".join(clean_visual_fragment(item.get("text", "")) for item in nearby)
        source_key, positions = comparable_with_positions(source)
        evidence_key, _ = comparable_with_positions(evidence)
        if not source_key or not evidence_key:
            output.append(current)
            continue
        matcher = difflib.SequenceMatcher(None, source_key, evidence_key, autojunk=False)
        opcodes = matcher.get_opcodes()
        replacements = []
        for index, (tag, i1, i2, j1, j2) in enumerate(opcodes):
            if tag != "replace" or not (1 <= i2 - i1 <= 4 and 1 <= j2 - j1 <= 4):
                continue
            previous_equal = index > 0 and opcodes[index - 1][0] == "equal" and opcodes[index - 1][2] - opcodes[index - 1][1] >= 2
            next_equal = index + 1 < len(opcodes) and opcodes[index + 1][0] == "equal" and opcodes[index + 1][2] - opcodes[index + 1][1] >= 2
            if not previous_equal or not next_equal:
                continue
            before = source_key[i1:i2]
            after = evidence_key[j1:j2]
            if before == after or any(character.isdigit() for character in before + after):
                continue
            original_start = positions[i1]
            original_end = positions[i2 - 1] + 1
            replacements.append((original_start, original_end, before, after))
        for original_start, original_end, before, after in reversed(replacements):
            source = source[:original_start] + after + source[original_end:]
            accepted.append({
                "from": before, "to": after,
                "start": round(start, 2), "end": round(end, 2),
                "source": "aligned_visual_subtitle",
            })
        current["text"] = source
        output.append(current)
    return output, accepted


def extract_visual_subtitles(video_path, output_path):
    if not OCR_WORKER.is_file() or not Path(OCR_RUNTIME).is_dir():
        return {
            "text": "", "segments": [], "elapsed": 0,
            "source": "unavailable", "model": "unavailable",
        }
    environment = os.environ.copy()
    environment.update({
        "TRANSCRIPT_HARD_SUBTITLE_OCR_ENABLED": "1",
        "TRANSCRIPT_OCR_RUNTIME": OCR_RUNTIME,
    })
    started = time.monotonic()
    try:
        subprocess.run(
            ["/usr/bin/python3", str(OCR_WORKER), str(video_path), str(output_path)],
            capture_output=True, text=True, timeout=900, check=True, env=environment,
        )
        value = json.loads(output_path.read_text(encoding="utf-8"))
        value["visual_subtitles"] = chinese_visual_text(value)
        return value
    except Exception as error:
        return {
            "text": "", "segments": [],
            "elapsed": round(time.monotonic() - started, 3),
            "source": "failed", "model": "unavailable",
            "visual_subtitles": "", "error": type(error).__name__,
        }


def create_recognizer():
    for path in (MODEL, TOKENS, VAD_MODEL):
        if not path.is_file():
            raise RuntimeError(f"missing model file: {path.name}")
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(MODEL), tokens=str(TOKENS), num_threads=NUM_THREADS,
        use_itn=True, language="zh", debug=False,
    )


def vad_segments(samples):
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(VAD_MODEL)
    config.silero_vad.threshold = 0.45
    config.silero_vad.min_silence_duration = 0.35
    config.silero_vad.min_speech_duration = 0.20
    config.silero_vad.max_speech_duration = 28.0
    config.sample_rate = 16000
    window = config.silero_vad.window_size
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=35)
    found = []
    offset = 0
    while offset + window <= len(samples):
        vad.accept_waveform(samples[offset:offset + window])
        offset += window
        while not vad.empty():
            segment = vad.front
            found.append((int(segment.start), np.asarray(segment.samples, dtype=np.float32).copy()))
            vad.pop()
    if offset < len(samples):
        padded = np.zeros(window, dtype=np.float32)
        padded[:len(samples) - offset] = samples[offset:]
        vad.accept_waveform(padded)
    vad.flush()
    while not vad.empty():
        segment = vad.front
        found.append((int(segment.start), np.asarray(segment.samples, dtype=np.float32).copy()))
        vad.pop()
    return found


def transcribe(recognizer, pcm_path):
    samples = np.fromfile(pcm_path, dtype=np.float32)
    speech = vad_segments(samples)
    output = []
    for start_sample, segment_samples in speech:
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, segment_samples)
        recognizer.decode_stream(stream)
        text = normalize_text(stream.result.text)
        if not text:
            continue
        start = round(start_sample / 16000, 2)
        end = round((start_sample + len(segment_samples)) / 16000, 2)
        output.append({"start": start, "end": end, "text": text})
    return output


def process_job(recognizer, job, job_dir):
    video_path = job_dir / "source.mp4"
    pcm_path = job_dir / "audio.f32le"
    ocr_path = job_dir / "ocr-result.json"
    job.update(stage="正在完整下载视频", updated_at=now())
    persist(job)
    download_video(job["video_url"], video_path)
    duration = media_duration(video_path)
    job.update(duration=round(duration, 3), stage="正在提取完整音频", updated_at=now())
    persist(job)
    if duration <= 0:
        raise RuntimeError("视频时长无效")
    if duration > MAX_VIDEO_SECONDS + 0.25:
        raise RuntimeError("视频超过 10 分钟，未进行截断")
    extract_pcm(video_path, pcm_path)
    expected_samples = round(duration * 16000)
    actual_samples = pcm_path.stat().st_size // 4
    if actual_samples < expected_samples - 32000:
        raise RuntimeError("音频提取不完整")
    job.update(stage="正在读取视频画面字幕", updated_at=now())
    persist(job)
    ocr_value = extract_visual_subtitles(video_path, ocr_path)
    job.update(stage="正在识别完整音频", updated_at=now())
    persist(job)
    asr_started = time.monotonic()
    raw_segments = transcribe(recognizer, pcm_path)
    if not raw_segments:
        raise RuntimeError("未识别到可用语音")
    segments = [dict(item) for item in raw_segments]
    text = "\n".join(item["text"] for item in segments)
    visual_segments, visual_changes = visual_correct_segments(raw_segments, ocr_value)
    visual_draft_text = "\n".join(item["text"] for item in visual_segments)
    return {
        "text": text,
        "segments": segments,
        "raw_segments": raw_segments,
        "duration": round(duration, 3),
        "audio_samples": actual_samples,
        "pipeline_version": PIPELINE_VERSION,
        "asr_elapsed": round(time.monotonic() - asr_started, 3),
        "visual_subtitles": str(ocr_value.get("visual_subtitles", "")),
        "ocr_elapsed": round(float(ocr_value.get("elapsed", 0) or 0), 3),
        "ocr_source": str(ocr_value.get("source", "unavailable")),
        "ocr_model": str(ocr_value.get("model", "unavailable")),
        "visual_draft_text": visual_draft_text,
        "visual_correction_count": len(visual_changes),
        "visual_changes": visual_changes,
    }


def cache_value(job):
    keys = (
        "text", "raw_text", "corrected_text", "segments", "raw_segments",
        "elapsed", "asr_elapsed", "correction_elapsed", "total_elapsed",
        "correction_status", "correction_error", "correction_changes",
        "correction_count", "correction_model", "correction_actual_model",
        "prompt_version", "correction_parameters", "correction_usage",
        "duration", "audio_samples", "pipeline_version", "completed_at",
        "visual_subtitles", "ocr_elapsed", "ocr_source", "ocr_model",
        "visual_draft_text", "visual_correction_count", "visual_changes",
    )
    return {key: job.get(key) for key in keys}


def worker_loop():
    global current_job_id
    recognizer = None
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
            job.update(status="running", stage="正在准备识别", updated_at=now())
            persist(job)
        started = time.monotonic()
        job_dir = TMP_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        try:
            if recognizer is None:
                recognizer = create_recognizer()
            value = process_job(recognizer, job, job_dir)
            asr_elapsed = float(value.pop("asr_elapsed", 0) or 0)
            raw_text = value["text"]
            with lock:
                job.update(value, raw_text=raw_text, asr_elapsed=asr_elapsed,
                           stage="原始识别完成，正在进行 DeepSeek 二次校正",
                           correction_status="running", updated_at=now())
                persist(job)
            correction = correct_text(
                value.get("visual_draft_text", raw_text),
                job.get("description", ""), job.get("author", ""),
                value.get("visual_subtitles", ""),
            )
            corrected_text = correction.get("corrected_text", "")
            if not corrected_text and value.get("visual_correction_count", 0):
                corrected_text = value.get("visual_draft_text", raw_text)
            if corrected_text:
                changes = deterministic_diff(raw_text, corrected_text)
                correction.update(correction_changes=changes, correction_count=len(changes))
            total_elapsed = round(time.monotonic() - started, 3)
            completed = {
                **value, **correction, "raw_text": raw_text,
                "corrected_text": corrected_text, "text": corrected_text or raw_text,
                "asr_elapsed": asr_elapsed, "total_elapsed": total_elapsed,
                "elapsed": total_elapsed, "completed_at": now(),
            }
            with lock:
                job.update(
                    completed, status="completed",
                    stage="已完成" if correction["correction_status"] == "completed" else "原始识别已完成，DeepSeek 校正失败",
                    error="", cached=False, updated_at=now(),
                )
                persist(job)
                atomic_json(cache_path(job["share_url"]), cache_value(job))
        except Exception as error:
            with lock:
                job.update(status="error", stage="识别失败", error=str(error)[-300:], elapsed=round(time.monotonic() - started, 3), updated_at=now())
                persist(job)
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
            with lock:
                active_by_url.pop(job.get("share_url"), None)
                current_job_id = None
            work_queue.task_done()


class Handler(BaseHTTPRequestHandler):
    server_version = "SenseVoiceCloud/2.0"

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

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/healthz":
            self.send_json(200, {
                "ok": True, "service": "transcripts-test-cloud", "running": bool(current_job_id),
                "queued": len(pending), "max_video_seconds": MAX_VIDEO_SECONDS,
                "free_disk_bytes": shutil.disk_usage(DATA_DIR).free,
                "correction_model": configured_model(), "prompt_version": PROMPT_VERSION,
                "deepseek_configured": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
                "pipeline_version": PIPELINE_VERSION,
                "visual_subtitle_ocr": OCR_WORKER.is_file() and Path(OCR_RUNTIME).is_dir(),
            })
            return
        if path.startswith("/jobs/"):
            job_id = path.split("/", 2)[2]
            with lock:
                job = jobs.get(job_id)
                if not job:
                    self.send_json(404, {"id": job_id, "status": "error", "stage": "", "ahead": 0, "text": "", "segments": [], "raw_segments": [], "elapsed": None, "error": "任务不存在或已过期"})
                    return
                self.send_json(200, public_job(job))
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/jobs/") and path.endswith("/correction"):
            job_id = path[len("/jobs/"):-len("/correction")].strip("/")
            with lock:
                job = jobs.get(job_id)
            if not job:
                self.send_json(404, {"error": "任务不存在"})
                return
            raw_text = str(job.get("raw_text") or "")
            if job.get("status") != "completed" or not raw_text:
                self.send_json(409, {"error": "原始识别尚未完成"})
                return
            with lock:
                job.update(stage="正在重试 DeepSeek 二次校正", correction_status="running", correction_error="", updated_at=now())
                persist(job)
            correction = correct_text(
                job.get("visual_draft_text", raw_text),
                job.get("description", ""), job.get("author", ""),
                job.get("visual_subtitles", ""),
            )
            corrected_text = correction.get("corrected_text", "")
            if not corrected_text and job.get("visual_correction_count", 0):
                corrected_text = job.get("visual_draft_text", raw_text)
            if corrected_text:
                changes = deterministic_diff(raw_text, corrected_text)
                correction.update(correction_changes=changes, correction_count=len(changes))
            with lock:
                job.update(correction)
                total_elapsed = round(float(job.get("asr_elapsed") or 0) + float(correction.get("correction_elapsed") or 0), 3)
                job.update(
                    text=corrected_text or raw_text, corrected_text=corrected_text,
                    total_elapsed=total_elapsed, elapsed=total_elapsed,
                    stage="已完成" if correction["correction_status"] == "completed" else "原始识别已完成，DeepSeek 校正失败",
                    completed_at=now(), updated_at=now(), cached=False,
                )
                persist(job)
                atomic_json(cache_path(job["share_url"]), cache_value(job))
                self.send_json(200, public_job(job))
            return
        if path != "/jobs":
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 8192:
                raise ValueError("invalid body")
            body = json.loads(self.rfile.read(length))
            share_url = str(body.get("share_url", "")).strip()
            video_url = str(body.get("video_url", "")).strip()
            description = str(body.get("description", ""))[:1000]
            author = str(body.get("author", ""))[:200]
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "请求格式不正确"})
            return
        if not valid_share_url(share_url):
            self.send_json(400, {"error": "请提交有效的视频号分享链接"})
            return
        if not valid_video_url(video_url):
            self.send_json(400, {"error": "视频文件地址无效或来源不受支持"})
            return
        if shutil.disk_usage(DATA_DIR).free < MIN_FREE_BYTES:
            self.send_json(503, {"error": "测试服务磁盘空间不足"})
            return
        with lock:
            active_id = active_by_url.get(share_url)
            if active_id and active_id in jobs:
                self.send_json(200, public_job(jobs[active_id]))
                return
            cached = load_cache(share_url)
            job_id = secrets.token_urlsafe(18)
            if cached:
                job = {"id": job_id, "share_url": share_url, "status": "completed", "stage": "已读取测试缓存", "cached": True, "updated_at": now(), **cached}
                jobs[job_id] = job
                persist(job)
                self.send_json(200, public_job(job))
                return
            if len(pending) >= 8:
                self.send_json(503, {"error": "测试队列已满"})
                return
            job = {
                "id": job_id, "share_url": share_url, "video_url": video_url,
                "description": description, "author": author, "status": "queued",
                "stage": "等待识别", "created_at": now(), "updated_at": now(),
                "raw_text": "", "corrected_text": "", "correction_status": "pending",
                "correction_model": configured_model(), "prompt_version": PROMPT_VERSION,
            }
            jobs[job_id] = job
            pending.append(job_id)
            active_by_url[share_url] = job_id
            persist(job)
            work_queue.put(job_id)
            self.send_json(202, public_job(job))


if __name__ == "__main__":
    load_jobs()
    cleanup_expired()
    threading.Thread(target=worker_loop, daemon=True).start()
    print(f"cloud test service listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
