#!/usr/bin/env python3
import difflib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


OCR_RUNTIME = os.environ.get("TRANSCRIPT_OCR_RUNTIME", "/opt/siyumenghai-transcriber/ocr-runtime")
FRAME_RATE = 5


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


def choose_variant(group):
    variants = group["variants"]
    best = max(
        variants.values(),
        key=lambda item: (item["hits"] * 4 + len(item["text"]) * 1.5, len(item["text"]), item["confidence"]),
    )
    return {
        "start": round(group["start"], 2),
        "end": round(group["last"] + 1 / FRAME_RATE, 2),
        "text": best["text"],
        "confidence": round(best["confidence"], 4),
        "samples": best["hits"],
    }


def consolidate(observations):
    groups = []
    current = None
    for item in observations:
        if current is None or not any(is_same_subtitle(item["text"], value["text"]) for value in current["variants"].values()):
            if current is not None:
                groups.append(choose_variant(current))
            current = {"start": item["time"], "last": item["time"], "variants": {}}
        current["last"] = item["time"]
        variant = current["variants"].setdefault(item["text"], {
            "text": item["text"], "hits": 0, "confidence_total": 0.0, "confidence": 0.0,
        })
        variant["hits"] += 1
        variant["confidence_total"] += item["confidence"]
        variant["confidence"] = variant["confidence_total"] / variant["hits"]
    if current is not None:
        groups.append(choose_variant(current))
    return [item for item in groups if item["samples"] >= 2 or item["confidence"] >= 0.82]


def main():
    video_path, output_path = map(Path, sys.argv[1:3])
    started = time.monotonic()
    runtime = Path(OCR_RUNTIME)
    if not runtime.is_dir():
        raise RuntimeError("OCR_RUNTIME_MISSING")
    sys.path.insert(0, str(runtime))

    import numpy as np
    from PIL import Image
    from rapidocr import ModelType, RapidOCR

    frames = output_path.parent / "ocr-frames"
    frames.mkdir(parents=True, exist_ok=True)
    run([
        "/usr/bin/ffmpeg", "-nostdin", "-v", "error", "-i", str(video_path),
        "-vf", f"fps={FRAME_RATE},crop=iw:ih*0.35:0:ih*0.60,scale='min(720,iw)':-2",
        "-q:v", "3", "-y", str(frames / "%06d.jpg"),
    ], 900)

    engine = RapidOCR(params={
        "Global.use_cls": False,
        "Global.log_level": "error",
        "Det.model_type": ModelType.TINY,
        "Rec.model_type": ModelType.TINY,
        "Det.limit_side_len": 480,
        "Det.limit_type": "max",
        "EngineConfig.onnxruntime.intra_op_num_threads": 4,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    })
    observations = []
    for index, frame_path in enumerate(sorted(frames.glob("*.jpg"))):
        image = Image.open(frame_path).convert("RGB")
        result = engine(np.asarray(image))
        boxes = result.boxes if result.boxes is not None else []
        texts = result.txts if result.txts is not None else []
        scores = result.scores if result.scores is not None else []
        lines = []
        for box, text, confidence in zip(boxes, texts, scores):
            height = max(point[1] for point in box) - min(point[1] for point in box)
            if confidence < 0.78 or height < image.height * 0.08:
                continue
            cleaned = clean_text(text)
            if cleaned:
                lines.append((
                    min(point[1] for point in box),
                    max(point[1] for point in box),
                    cleaned,
                    float(confidence),
                ))
        if not lines:
            continue
        lowest_bottom = max(item[1] for item in lines)
        lines = [item for item in lines if lowest_bottom - item[1] <= image.height * 0.22]
        lines.sort(key=lambda item: item[0])
        observations.append({
            "time": index / FRAME_RATE,
            "text": "".join(item[2] for item in lines),
            "confidence": min(item[3] for item in lines),
        })

    segments = consolidate(observations)
    output_path.write_text(json.dumps({
        "text": "\n".join(item["text"] for item in segments),
        "segments": segments,
        "elapsed": round(time.monotonic() - started, 1),
        "model": "RapidOCR-PP-OCRv6-tiny",
        "frame_rate": FRAME_RATE,
    }, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
