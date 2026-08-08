#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

MODEL_DIR = "/var/lib/siyumenghai-transcriber/models/large-v3-turbo"
MAX_SECONDS = 600
OCR_WORKER = os.environ.get("TRANSCRIPT_OCR_WORKER", str(Path(__file__).with_name("ocr_worker.py")))
PIPELINE_VERSION = "ocr-asr-timeline-v2"

FUSION_CORRECTIONS = (
    ("Workbuddy", "WorkBuddy"),
    ("workbuddy", "WorkBuddy"),
    ("混元3模型", "混元模型"),
    ("混元三模型", "混元模型"),
    ("会员3模型", "混元模型"),
    ("会员三模型", "混元模型"),
    ("会员模型", "混元模型"),
    ("会元模型", "混元模型"),
    ("混原模型", "混元模型"),
    ("不勤不慢", "不紧不慢"),
    ("不勤慢", "不紧不慢"),
    ("KimiK3", "Kimi K3"),
    ("WorkBuddy之后", "WorkBuddy 之后"),
    ("Kimi K3的模型", "Kimi K3 的模型"),
    ("这个免费这个混元模型", "这个免费的混元模型"),
    ("而且它模型质量很差的", "而且它的模型质量很差"),
    ("AI时代", "AI 时代"),
)


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


def normalize_text(value):
    text = simplify(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", text)
    for wrong, right in FUSION_CORRECTIONS:
        text = text.replace(wrong, right)
    text = re.sub(r"大错特(?!错)", "大错特错", text)
    return text


def punctuation_at(start, end, words):
    candidates = []
    for word in words:
        match = re.search(r"([,，。.!！?？])$", word["word"])
        if not match:
            continue
        midpoint = (float(word["start"]) + float(word["end"])) / 2
        if not start - 0.12 <= midpoint <= end + 0.06:
            continue
        distance = abs(float(word["end"]) - end)
        if distance <= 0.48:
            candidates.append((distance, match.group(1)))
    if not candidates:
        return ""
    punctuation = min(candidates)[1]
    return {",": "，", ".": "。", "!": "！", "?": "？"}.get(punctuation, punctuation)


def asr_gap_segments(words, ocr_segments):
    uncovered = []
    current = None
    for word in words:
        midpoint = (float(word["start"]) + float(word["end"])) / 2
        covered = any(float(item["start"]) - 0.32 <= midpoint <= float(item["end"]) + 0.32 for item in ocr_segments)
        if covered:
            if current:
                uncovered.append(current)
                current = None
            continue
        cleaned = normalize_text(word["word"])
        if not cleaned:
            continue
        if current and float(word["start"]) - current["end"] <= 0.36:
            current["text"] += cleaned
            current["end"] = float(word["end"])
        else:
            if current:
                uncovered.append(current)
            current = {"start": float(word["start"]), "end": float(word["end"]), "text": cleaned, "source": "asr"}
    if current:
        uncovered.append(current)
    return [item for item in uncovered if len(re.sub(r"\W", "", item["text"])) >= 2]


def sentence_segments(events, words):
    output = []
    current = None
    for event in sorted(events, key=lambda item: (float(item["start"]), 0 if item.get("source") == "ocr" else 1)):
        text = normalize_text(event["text"]).strip("，。！？,.!? ")
        if not text:
            continue
        punctuation = punctuation_at(float(event["start"]), float(event["end"]), words)
        if current is None:
            current = {"start": float(event["start"]), "end": float(event["end"]), "text": text, "source": event.get("source", "ocr")}
        else:
            current["text"] += text
            current["end"] = float(event["end"])
            if current["source"] != event.get("source", "ocr"):
                current["source"] = "ocr_asr"
        if punctuation in {"，"}:
            current["text"] += punctuation
        elif punctuation in {"。", "！", "？"}:
            current["text"] += punctuation
            output.append(current)
            current = None
    if current:
        if not re.search(r"[。！？]$", current["text"]):
            current["text"] += "。"
        output.append(current)
    for item in output:
        item["text"] = normalize_text(item["text"])
        item["start"] = round(item["start"], 2)
        item["end"] = round(item["end"], 2)
    return output


def fuse_transcript(ocr_value, asr_segments, asr_words):
    ocr_segments = list(ocr_value.get("segments") or [])
    ocr_chars = len(re.sub(r"\s", "", ocr_value.get("text", "")))
    asr_text = normalize_text("".join(item["text"] for item in asr_segments))
    asr_chars = len(re.sub(r"\s", "", asr_text))
    use_ocr = len(ocr_segments) >= 2 and ocr_chars >= max(8, int(asr_chars * 0.38))
    if not use_ocr:
        segments = [{
            "start": item["start"], "end": item["end"],
            "text": normalize_text(item["text"]), "source": "asr",
        } for item in asr_segments if normalize_text(item["text"])]
        return segments, "asr"

    events = [{**item, "source": "ocr"} for item in ocr_segments]
    events.extend(asr_gap_segments(asr_words, ocr_segments))
    return sentence_segments(events, asr_words), "ocr_asr_fusion"


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
    source = work / "source.mp4"
    audio = work / "audio.wav"
    ocr_output = work / "ocr-result.json"
    started = time.monotonic()

    validate_video_url(video_url)
    duration = media_duration(video_url)
    if duration > MAX_SECONDS + 0.5:
        raise RuntimeError(f"VIDEO_TOO_LONG:{duration:.1f}")

    run([
        "/usr/bin/ffmpeg", "-nostdin", "-v", "error", "-rw_timeout", "30000000",
        "-i", video_url, "-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-y", str(source),
    ], 300)
    ocr_value = {"text": "", "segments": [], "model": "unavailable", "elapsed": 0}
    try:
        ocr_process = subprocess.run(
            ["/usr/bin/python3", OCR_WORKER, str(source), str(ocr_output)],
            capture_output=True, text=True, timeout=1200,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        if ocr_process.returncode == 0:
            ocr_value = json.loads(ocr_output.read_text(encoding="utf-8"))
    except Exception:
        pass

    run([
        "/usr/bin/ffmpeg", "-nostdin", "-v", "error", "-i", str(source),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(audio),
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
    whisper_segments, _ = model.transcribe(
        str(audio), language="zh", task="transcribe",
        temperature=0, beam_size=5, condition_on_previous_text=True,
        initial_prompt=prompt, vad_filter=False, word_timestamps=True,
    )
    whisper_segments = list(whisper_segments)
    asr_segments = [{
        "start": round(float(segment.start), 2),
        "end": round(float(segment.end), 2),
        "text": normalize_text(segment.text),
    } for segment in whisper_segments]
    asr_words = [{
        "start": round(float(word.start), 2),
        "end": round(float(word.end), 2),
        "word": simplify(word.word),
    } for segment in whisper_segments for word in (segment.words or [])]
    audio_text = normalize_text("".join(item["text"] for item in asr_segments))
    if not audio_text:
        raise RuntimeError("没有识别到清晰人声")
    fused_segments, source_type = fuse_transcript(ocr_value, asr_segments, asr_words)
    text = "\n".join(item["text"] for item in fused_segments).strip() or audio_text
    Path(output_path).write_text(json.dumps({
        "text": text,
        "segments": fused_segments,
        "audio_text": audio_text,
        "ocr_text": str(ocr_value.get("text", "")).strip(),
        "source": source_type,
        "duration": round(duration, 1),
        "elapsed": round(time.monotonic() - started, 1),
        "model": f"{ocr_value.get('model', 'OCR-unavailable')} + large-v3-turbo-int8",
        "pipeline_version": PIPELINE_VERSION,
        "ocr_elapsed": ocr_value.get("elapsed", 0),
    }, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
