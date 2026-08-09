#!/usr/bin/env python3
import difflib
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
PIPELINE_VERSION = "ocr-asr-completeness-v5"

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
    ("超盘", "操盘"),
    ("高变X", "高变现"),
    ("变X", "变现"),
    ("客难成本", "获客成本"),
    ("确确是", "确实是"),
    ("价值百W", "价值百万"),
    ("小书博主", "小红书博主"),
    ("小书广告", "小红书广告"),
    ("不自闭环", "不做闭环"),
    ("必4无疑", "必死无疑"),
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
    text = re.sub(r"[�＼]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", text)
    for wrong, right in FUSION_CORRECTIONS:
        text = text.replace(wrong, right)
    text = re.sub(r"大错特(?!错)", "大错特错", text)
    return text


def punctuation_assignments(events, words):
    assignments = {}
    for word in words:
        match = re.search(r"([,，、。.!！?？])$", word["word"])
        if not match:
            continue
        midpoint = (float(word["start"]) + float(word["end"])) / 2
        candidates = []
        word_key = alignment_key(word["word"])
        for index, event in enumerate(events):
            start = float(event["start"])
            end = float(event["end"])
            if start - 0.28 <= midpoint <= end + 0.12:
                distance = abs(float(word["end"]) - end)
                if distance <= 0.48:
                    text_similarity = best_window_similarity(word_key, alignment_key(event.get("text", "")))
                    candidates.append((-text_similarity, distance, index))
        if candidates:
            _, _, index = min(candidates)
            punctuation = {",": "，", ".": "。", "!": "！", "?": "？"}.get(match.group(1), match.group(1))
            assignments[index] = punctuation
    return assignments


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
    ordered_events = sorted(events, key=lambda item: (float(item["start"]), 0 if item.get("source") == "ocr" else 1))
    punctuation_by_event = punctuation_assignments(ordered_events, words)
    for event_index, event in enumerate(ordered_events):
        text = normalize_text(event["text"]).strip("，。！？,.!? ")
        if not text:
            continue
        punctuation = punctuation_by_event.get(event_index, "")
        if current is None:
            current = {"start": float(event["start"]), "end": float(event["end"]), "text": text, "source": event.get("source", "ocr")}
        else:
            current["text"] += text
            current["end"] = float(event["end"])
            if current["source"] != event.get("source", "ocr"):
                current["source"] = "ocr_asr"
        if punctuation in {"，", "、"}:
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


def alignment_key(value):
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", normalize_text(value)).lower()


def best_window_similarity(left, right):
    if not left or not right:
        return 0.0
    if len(right) <= len(left) + 2:
        return difflib.SequenceMatcher(None, left, right).ratio()
    best = 0.0
    for size in range(max(1, len(left) - 2), min(len(right), len(left) + 2) + 1):
        for start in range(0, len(right) - size + 1):
            best = max(best, difflib.SequenceMatcher(None, left, right[start:start + size]).ratio())
    return best


def merge_duplicate_ocr_segments(segments):
    merged = []
    for item in sorted(segments, key=lambda value: (float(value["start"]), float(value["end"]))):
        key = alignment_key(item.get("text", ""))
        duplicate = next((
            previous for previous in reversed(merged[-4:])
            if alignment_key(previous.get("text", "")) == key
            and float(item["start"]) <= float(previous["end"]) + 0.08
        ), None)
        if duplicate is None or not key:
            merged.append(dict(item))
            continue
        duplicate["start"] = min(float(duplicate["start"]), float(item["start"]))
        duplicate["end"] = max(float(duplicate["end"]), float(item["end"]))
        duplicate["confidence"] = max(float(duplicate.get("confidence", 0)), float(item.get("confidence", 0)))
        duplicate["samples"] = max(int(duplicate.get("samples", 1)), int(item.get("samples", 1)))
    return merged


def select_timeline_segments(segments):
    """Choose the strongest non-conflicting OCR path across the audio timeline.

    Dense screen recordings often contain menu labels that partially match the
    narration.  They overlap the real hard subtitle in time, so a weighted
    timeline path keeps the more complete, better-aligned caption sequence.
    """
    if len(segments) < 2:
        return segments
    ordered = sorted(segments, key=lambda item: (float(item["end"]), float(item["start"])))
    ends = [float(item["end"]) for item in ordered]
    predecessors = []
    for index, item in enumerate(ordered):
        start = float(item["start"])
        previous = index - 1
        while previous >= 0 and ends[previous] > start + 0.18:
            previous -= 1
        predecessors.append(previous)

    scores = [0.0] * (len(ordered) + 1)
    choices = [False] * len(ordered)
    for index, item in enumerate(ordered, start=1):
        text_length = len(alignment_key(item.get("text", "")))
        duration = max(0.1, float(item["end"]) - float(item["start"]))
        weight = (
            float(item.get("alignment", 0)) * 7
            + min(text_length, 24) * 0.22
            + min(duration, 3.0) * 1.1
            + float(item.get("confidence", 0))
        )
        include = weight + scores[predecessors[index - 1] + 1]
        exclude = scores[index - 1]
        if include > exclude:
            scores[index] = include
            choices[index - 1] = True
        else:
            scores[index] = exclude

    selected = []
    index = len(ordered) - 1
    while index >= 0:
        item = ordered[index]
        text_length = len(alignment_key(item.get("text", "")))
        duration = max(0.1, float(item["end"]) - float(item["start"]))
        weight = (
            float(item.get("alignment", 0)) * 7
            + min(text_length, 24) * 0.22
            + min(duration, 3.0) * 1.1
            + float(item.get("confidence", 0))
        )
        include = weight + scores[predecessors[index] + 1]
        if include > scores[index]:
            selected.append(item)
            index = predecessors[index]
        else:
            index -= 1
    return sorted(selected, key=lambda item: (float(item["start"]), float(item["end"])))


def aligned_ocr_segments(ocr_segments, asr_segments, asr_words):
    if not asr_segments and not asr_words:
        return [{**item, "alignment": 1.0} for item in ocr_segments]
    selected = []
    for item in ocr_segments:
        start = float(item["start"]) - 0.75
        end = float(item["end"]) + 0.75
        nearby_words = [
            word["word"] for word in asr_words
            if float(word["end"]) >= start and float(word["start"]) <= end
        ]
        nearby_segments = [
            segment["text"] for segment in asr_segments
            if float(segment["end"]) >= start and float(segment["start"]) <= end
        ]
        nearby = alignment_key("".join(nearby_words) or "".join(nearby_segments))
        text_key = alignment_key(item.get("text", ""))
        similarity = best_window_similarity(text_key, nearby)
        confidence = float(item.get("confidence", 0))
        text_length = len(text_key)
        if similarity >= 0.42 or (
            similarity >= 0.34 and confidence >= 0.90 and text_length >= 4
        ):
            selected.append({**item, "alignment": round(similarity, 4)})
    return select_timeline_segments(selected)


def fuse_transcript(ocr_value, asr_segments, asr_words):
    raw_ocr_segments = merge_duplicate_ocr_segments(list(ocr_value.get("segments") or []))
    asr_text = normalize_text("".join(item["text"] for item in asr_segments))
    asr_chars = len(re.sub(r"\s", "", asr_text))
    source = ocr_value.get("source")
    ocr_segments = raw_ocr_segments if source == "embedded_subtitle" else aligned_ocr_segments(
        raw_ocr_segments, asr_segments, asr_words,
    )
    selected_text = "".join(item.get("text", "") for item in ocr_segments)
    ocr_chars = len(re.sub(r"\s", "", selected_text))
    ocr_key = alignment_key(selected_text)
    asr_key = alignment_key(asr_text)
    similarity = difflib.SequenceMatcher(None, ocr_key, asr_key).ratio() if asr_key else 1.0
    region = ocr_value.get("region")
    ocr_quality_ok = source == "embedded_subtitle" or (
        isinstance(region, dict)
        and not region.get("fallback")
        and float(ocr_value.get("mean_confidence", 0)) >= 0.74
    )
    use_ocr = (
        len(ocr_segments) >= 2
        and ocr_chars >= max(6, int(asr_chars * 0.22))
        and ocr_quality_ok
        and similarity >= 0.35
    )
    if not use_ocr:
        segments = [{
            "start": item["start"], "end": item["end"],
            "text": normalize_text(item["text"]), "source": "asr",
        } for item in asr_segments if normalize_text(item["text"])]
        return segments, "asr", round(similarity, 4), []

    events = [{**item, "source": "ocr"} for item in ocr_segments]
    events.extend(asr_gap_segments(asr_words, ocr_segments))
    fused_segments = sentence_segments(events, asr_words)
    fused_chars = len(alignment_key("".join(item.get("text", "") for item in fused_segments)))

    # OCR timestamps only prove that a subtitle was visible; they do not prove
    # that the OCR text captured every spoken word in that time range.  The old
    # fusion treated all ASR words inside an OCR interval as already covered and
    # could silently drop most of a video.  Never publish a fused transcript
    # that is materially shorter than the complete ASR backbone.
    if asr_chars and fused_chars < int(asr_chars * 0.88):
        segments = [{
            "start": item["start"], "end": item["end"],
            "text": normalize_text(item["text"]), "source": "asr",
        } for item in asr_segments if normalize_text(item["text"])]
        return segments, "asr_completeness_fallback", round(similarity, 4), ocr_segments

    return fused_segments, "ocr_asr_fusion", round(similarity, 4), ocr_segments


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
        "-i", video_url, "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?",
        "-c", "copy", "-y", str(source),
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

    has_audio = True
    try:
        run([
            "/usr/bin/ffmpeg", "-nostdin", "-v", "error", "-i", str(source),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(audio),
        ], 300)
    except subprocess.SubprocessError:
        has_audio = False

    whisper_segments = []
    if has_audio:
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
        transcript, _ = model.transcribe(
            str(audio), language="zh", task="transcribe",
            temperature=0, beam_size=5, condition_on_previous_text=False,
            repetition_penalty=1.1, no_repeat_ngram_size=3,
            initial_prompt=prompt, vad_filter=False, word_timestamps=True,
        )
        whisper_segments = list(transcript)
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
    if not audio_text and not str(ocr_value.get("text", "")).strip():
        raise RuntimeError("没有识别到清晰人声")
    fused_segments, source_type, fusion_similarity, selected_ocr_segments = fuse_transcript(
        ocr_value, asr_segments, asr_words,
    )
    text = "\n".join(item["text"] for item in fused_segments).strip() or audio_text
    Path(output_path).write_text(json.dumps({
        "text": text,
        "segments": fused_segments,
        "audio_text": audio_text,
        "ocr_text": "\n".join(item.get("text", "") for item in selected_ocr_segments).strip(),
        "source": source_type,
        "duration": round(duration, 1),
        "elapsed": round(time.monotonic() - started, 1),
        "model": f"{ocr_value.get('model', 'OCR-unavailable')} + large-v3-turbo-int8",
        "pipeline_version": PIPELINE_VERSION,
        "ocr_elapsed": ocr_value.get("elapsed", 0),
        "ocr_source": ocr_value.get("source", "unavailable"),
        "ocr_region": ocr_value.get("region"),
        "ocr_confidence": ocr_value.get("mean_confidence", 0),
        "fusion_similarity": fusion_similarity,
    }, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
