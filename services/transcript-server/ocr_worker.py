#!/usr/bin/env python3
import difflib
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


OCR_RUNTIME = os.environ.get("TRANSCRIPT_OCR_RUNTIME", "/opt/siyumenghai-transcriber/ocr-runtime")
DISCOVERY_SAMPLES = 24


def run(command, timeout):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=True)


def clean_text(value):
    text = re.sub(r"\s+", "", str(value or ""))
    return text.strip("|_—-.,，。:：;；")


def comparable(value):
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", value).lower()


def is_same_subtitle(left, right):
    left_key = comparable(left)
    right_key = comparable(right)
    if not left_key or not right_key:
        return False
    if min(len(left_key), len(right_key)) >= 3 and (left_key in right_key or right_key in left_key):
        return True
    return difflib.SequenceMatcher(None, left_key, right_key).ratio() >= 0.52


def parse_timestamp(value):
    match = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", value.strip())
    if not match:
        raise ValueError("invalid subtitle timestamp")
    hours, minutes, seconds, millis = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / (10 ** len(millis))


def embedded_subtitles(video_path, output_path, started):
    try:
        probe = run([
            "/usr/bin/ffprobe", "-v", "error", "-select_streams", "s",
            "-show_entries", "stream=index,codec_name", "-of", "json", str(video_path),
        ], 30)
        streams = json.loads(probe.stdout or "{}").get("streams") or []
        if not streams:
            return False
        subtitle_path = output_path.parent / "embedded-subtitles.srt"
        run([
            "/usr/bin/ffmpeg", "-nostdin", "-v", "error", "-i", str(video_path),
            "-map", "0:s:0", "-f", "srt", "-y", str(subtitle_path),
        ], 120)
        content = subtitle_path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        segments = []
        for block in re.split(r"\n\s*\n", content):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            timing_index = next((index for index, line in enumerate(lines) if "-->" in line), -1)
            if timing_index < 0:
                continue
            start_value, end_value = (item.strip() for item in lines[timing_index].split("-->", 1))
            text = "".join(lines[timing_index + 1:])
            text = re.sub(r"<[^>]+>|\{\\[^}]+\}", "", html.unescape(text))
            text = clean_text(text)
            if not comparable(text):
                continue
            segments.append({
                "start": round(parse_timestamp(start_value), 2),
                "end": round(parse_timestamp(end_value), 2),
                "text": text,
                "confidence": 1.0,
                "samples": 1,
            })
        if len(segments) < 2 or sum(len(comparable(item["text"])) for item in segments) < 8:
            return False
        output_path.write_text(json.dumps({
            "text": "\n".join(item["text"] for item in segments),
            "segments": segments,
            "elapsed": round(time.monotonic() - started, 1),
            "model": f"embedded-{streams[0].get('codec_name', 'subtitle')}",
            "source": "embedded_subtitle",
            "frame_rate": 0,
            "region": None,
            "mean_confidence": 1.0,
        }, ensure_ascii=False), encoding="utf-8")
        return True
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        return False


def media_duration(video_path):
    result = run([
        "/usr/bin/ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
    ], 30)
    return max(0.1, float(result.stdout.strip()))


def build_engine(ModelType, model_type):
    from rapidocr import RapidOCR
    return RapidOCR(params={
        "Global.use_cls": False,
        "Global.log_level": "error",
        "Det.model_type": model_type,
        "Rec.model_type": model_type,
        "Det.limit_side_len": 720 if model_type == ModelType.SMALL else 576,
        "Det.limit_type": "max",
        "EngineConfig.onnxruntime.intra_op_num_threads": 4,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    })


def detected_lines(engine, image, minimum_confidence=0.68):
    import numpy as np
    result = engine(np.asarray(image))
    boxes = result.boxes if result.boxes is not None else []
    texts = result.txts if result.txts is not None else []
    scores = result.scores if result.scores is not None else []
    lines = []
    for box, text, confidence in zip(boxes, texts, scores):
        top = float(min(point[1] for point in box))
        bottom = float(max(point[1] for point in box))
        left = float(min(point[0] for point in box))
        right = float(max(point[0] for point in box))
        height = bottom - top
        width = right - left
        cleaned = clean_text(text)
        if (float(confidence) < minimum_confidence or not comparable(cleaned)
                or height < image.height * 0.018 or height > image.height * 0.35
                or width < image.width * 0.055):
            continue
        lines.append({
            "top": top / image.height,
            "bottom": bottom / image.height,
            "center": ((top + bottom) / 2) / image.height,
            "height": height / image.height,
            "width": width / image.width,
            "center_x": ((left + right) / 2) / image.width,
            "text": cleaned,
            "confidence": float(confidence),
        })
    return lines


def discover_region(video_path, frames, engine, duration, Image):
    discovery_rate = min(2.0, max(0.04, DISCOVERY_SAMPLES / duration))
    run([
        "/usr/bin/ffmpeg", "-nostdin", "-v", "error", "-i", str(video_path),
        "-vf", f"fps={discovery_rate:.6f},scale='min(720,iw)':-2",
        "-frames:v", str(DISCOVERY_SAMPLES), "-q:v", "4", "-y", str(frames / "discover-%04d.jpg"),
    ], 300)
    candidates = []
    paths = sorted(frames.glob("discover-*.jpg"))
    for frame_index, frame_path in enumerate(paths):
        image = Image.open(frame_path).convert("RGB")
        for line in detected_lines(engine, image):
            candidates.append({**line, "frame": frame_index, "key": comparable(line["text"])})
    if not candidates:
        return {"y": 0.60, "height": 0.38, "center": 0.79, "score": 0.0, "fallback": True}

    best = None
    for anchor in candidates:
        nearby = [item for item in candidates if abs(item["center"] - anchor["center"]) <= 0.045]
        frames_seen = len({item["frame"] for item in nearby})
        variant_groups = []
        for item in nearby:
            matching = next((group for group in variant_groups if is_same_subtitle(group["text"], item["text"])), None)
            if matching is None:
                variant_groups.append({"text": item["text"], "hits": 1})
            else:
                matching["hits"] += 1
        distinct = len(variant_groups)
        dominant = max((group["hits"] for group in variant_groups), default=0)
        changing_ratio = 1 - dominant / max(1, len(nearby))
        confidence = sum(item["confidence"] for item in nearby) / len(nearby)
        mean_height = sum(item["height"] for item in nearby) / len(nearby)
        mean_width = sum(item["width"] for item in nearby) / len(nearby)
        center_distance = sum(abs(item["center_x"] - 0.5) for item in nearby) / len(nearby)
        # Dialogue subtitles recur across frames but change over time. Static logos/titles do not.
        score = (
            frames_seen * 1.2 + min(distinct, 16) * 1.5 + changing_ratio * 7 + confidence * 2
            + min(mean_height, 0.10) * 240 + min(mean_width, 0.85) * 4 - center_distance * 5
        )
        if frames_seen < 2:
            score -= 8
        if distinct < 2:
            score -= 9
        value = (score, frames_seen, distinct, mean_height, confidence, anchor["center"])
        if best is None or value > best:
            best = value
    score, frames_seen, distinct, mean_height, confidence, center = best
    if score < 4 or frames_seen < 2:
        return {"y": 0.60, "height": 0.38, "center": 0.79, "score": round(score, 2), "fallback": True}
    crop_height = 0.38
    crop_y = min(1 - crop_height, max(0.0, center - crop_height / 2))
    return {
        "y": round(crop_y, 4), "height": crop_height, "center": round(center, 4),
        "score": round(score, 2), "frames": frames_seen, "variants": distinct,
        "confidence": round(confidence, 4), "mean_line_height": round(mean_height, 4), "fallback": False,
    }


def frame_subtitle(engine, image, target_center):
    lines = detected_lines(engine, image, minimum_confidence=0.72)
    candidates = [item for item in lines if abs(item["center"] - target_center) <= 0.22]
    if not candidates:
        return None
    # Keep the dominant large, horizontally centred text band. This prevents
    # smaller app labels in the same crop from being concatenated with captions.
    anchor = max(
        candidates,
        key=lambda item: item["height"] * 8 + item["width"] * 1.5 - abs(item["center_x"] - 0.5),
    )
    selected = [
        item for item in candidates
        if abs(item["center"] - anchor["center"]) <= 0.16
        and item["height"] >= anchor["height"] * 0.58
    ]
    selected.sort(key=lambda item: item["top"])
    return {
        "text": "".join(item["text"] for item in selected),
        "confidence": min(item["confidence"] for item in selected),
    }


def choose_variant(group, frame_rate):
    variants = group["variants"]
    best = max(
        variants.values(),
        key=lambda item: (item["hits"] * 4 + len(item["text"]) * 1.5, len(item["text"]), item["confidence"]),
    )
    return {
        "start": round(group["start"], 2),
        "end": round(group["last"] + 1 / frame_rate, 2),
        "text": best["text"],
        "confidence": round(best["confidence"], 4),
        "samples": best["hits"],
        "frame_index": best["frame_index"],
    }


def consolidate(observations, frame_rate):
    groups = []
    current = None
    for item in observations:
        gap = item["time"] - current["last"] if current is not None else 0
        same = current is not None and any(
            is_same_subtitle(item["text"], value["text"]) for value in current["variants"].values()
        )
        if current is None or gap > max(0.9, 3 / frame_rate) or not same:
            if current is not None:
                groups.append(choose_variant(current, frame_rate))
            current = {"start": item["time"], "last": item["time"], "variants": {}}
        current["last"] = item["time"]
        variant = current["variants"].setdefault(item["text"], {
            "text": item["text"], "hits": 0, "confidence_total": 0.0,
            "confidence": 0.0, "frame_index": item["frame_index"], "max_confidence": 0.0,
        })
        variant["hits"] += 1
        variant["confidence_total"] += item["confidence"]
        variant["confidence"] = variant["confidence_total"] / variant["hits"]
        if item["confidence"] >= variant["max_confidence"]:
            variant["max_confidence"] = item["confidence"]
            variant["frame_index"] = item["frame_index"]
    if current is not None:
        groups.append(choose_variant(current, frame_rate))
    return [item for item in groups if item["samples"] >= 2 or item["confidence"] >= 0.82]


def verify_segments(segments, frame_paths, ModelType, Image, target_center):
    if not segments:
        return segments, False
    small_engine = build_engine(ModelType, ModelType.SMALL)
    used = False
    for segment in segments:
        index = min(max(0, int(segment.pop("frame_index", 0))), len(frame_paths) - 1)
        image = Image.open(frame_paths[index]).convert("RGB")
        checked = frame_subtitle(small_engine, image, target_center)
        if not checked:
            continue
        original = segment["text"]
        similar = is_same_subtitle(original, checked["text"])
        length_ok = len(comparable(checked["text"])) >= max(2, int(len(comparable(original)) * 0.65))
        if length_ok and (similar or checked["confidence"] >= segment["confidence"] - 0.04):
            segment["text"] = checked["text"]
            segment["confidence"] = round(checked["confidence"], 4)
            used = True
    return segments, used


def main():
    video_path, output_path = map(Path, sys.argv[1:3])
    started = time.monotonic()
    if embedded_subtitles(video_path, output_path, started):
        return

    runtime = Path(OCR_RUNTIME)
    if not runtime.is_dir():
        raise RuntimeError("OCR_RUNTIME_MISSING")
    sys.path.insert(0, str(runtime))

    from PIL import Image
    from rapidocr import ModelType

    duration = media_duration(video_path)
    frame_rate = 4.0 if duration <= 180 else (3.0 if duration <= 360 else 2.5)
    frames = output_path.parent / "ocr-frames"
    frames.mkdir(parents=True, exist_ok=True)
    tiny_engine = build_engine(ModelType, ModelType.TINY)
    region = discover_region(video_path, frames, tiny_engine, duration, Image)

    run([
        "/usr/bin/ffmpeg", "-nostdin", "-v", "error", "-i", str(video_path),
        "-vf", (
            f"fps={frame_rate},crop=iw:ih*{region['height']}:0:ih*{region['y']},"
            "scale='min(720,iw)':-2"
        ),
        "-q:v", "3", "-y", str(frames / "scan-%06d.jpg"),
    ], 900)

    target_center = (region["center"] - region["y"]) / region["height"]
    observations = []
    frame_paths = sorted(frames.glob("scan-*.jpg"))
    for index, frame_path in enumerate(frame_paths):
        image = Image.open(frame_path).convert("RGB")
        value = frame_subtitle(tiny_engine, image, target_center)
        if value:
            observations.append({
                "time": index / frame_rate,
                "frame_index": index,
                **value,
            })

    segments = consolidate(observations, frame_rate)
    segments, used_small = verify_segments(segments, frame_paths, ModelType, Image, target_center)
    for item in segments:
        item.pop("frame_index", None)
    mean_confidence = sum(item["confidence"] for item in segments) / len(segments) if segments else 0
    output_path.write_text(json.dumps({
        "text": "\n".join(item["text"] for item in segments),
        "segments": segments,
        "elapsed": round(time.monotonic() - started, 1),
        "model": "RapidOCR-PP-OCRv6-tiny+small" if used_small else "RapidOCR-PP-OCRv6-tiny",
        "source": "hard_subtitle_ocr",
        "frame_rate": frame_rate,
        "region": region,
        "mean_confidence": round(mean_confidence, 4),
    }, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
