#!/usr/bin/env python3
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

MODEL_DIR = "/var/lib/siyumenghai-transcriber/models/large-v3-turbo"
MAX_SECONDS = 600


def validate_video_url(video_url):
    parsed = urlparse(video_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host.endswith(".qq.com") or host.endswith(".qpic.cn") or host.endswith(".gtimg.com")):
        raise RuntimeError("视频来源不受支持")


def run(command, timeout):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=True)


def media_duration(video_url):
    result = run([
        "/usr/bin/ffprobe", "-v", "error", "-rw_timeout", "20000000",
        "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_url,
    ], 60)
    return float(result.stdout.strip())


def simplify(text):
    try:
        from opencc import OpenCC
        return OpenCC("t2s").convert(text)
    except Exception:
        return text


def main():
    share_url, work_dir, output_path, video_url = sys.argv[1:5]
    description = sys.argv[5] if len(sys.argv) > 5 else ""
    author = sys.argv[6] if len(sys.argv) > 6 else ""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    audio = work / "audio.wav"
    started = time.monotonic()

    validate_video_url(video_url)
    duration = media_duration(video_url)
    if duration > MAX_SECONDS + 0.5:
        raise RuntimeError(f"VIDEO_TOO_LONG:{duration:.1f}")

    run([
        "/usr/bin/ffmpeg", "-nostdin", "-v", "error", "-rw_timeout", "30000000",
        "-i", video_url, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(audio),
    ], 300)

    from faster_whisper import WhisperModel
    model = WhisperModel(
        MODEL_DIR,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        num_workers=1,
    )
    prompt = "普通话口播逐字稿，使用简体中文。常见词：微信、视频号、小红书、私域、IP、AI、Agent、元宝。"
    if author:
        prompt += f"作者：{author}。"
    if description:
        prompt += f"视频说明：{description[:300]}。"
    segments, _ = model.transcribe(
        str(audio), language="zh", task="transcribe",
        temperature=0, beam_size=5, condition_on_previous_text=True,
        initial_prompt=prompt, vad_filter=False,
    )
    text = simplify("".join(segment.text for segment in segments)).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        raise RuntimeError("没有识别到清晰人声")
    Path(output_path).write_text(json.dumps({
        "text": text,
        "duration": round(duration, 1),
        "elapsed": round(time.monotonic() - started, 1),
        "model": "large-v3-turbo-int8",
    }, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
