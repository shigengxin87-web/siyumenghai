#!/usr/bin/env python3
"""Shared, deterministic DeepSeek proofreading contract for transcript routes B/C."""

from __future__ import annotations

import difflib
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROMPT_VERSION = "production-ocr-proofread-zh-v2.0.0"
DEFAULT_MODEL = "deepseek-chat"
TEMPERATURE = 0
TOP_P = 1
MAX_TOKENS = 8192

SYSTEM_PROMPT = """你是中文逐字稿的严格校对器。输入 JSON 中包含：
- asr_text：SenseVoice 根据完整音频生成的原始逐字稿，是必须保留结构和内容的主稿。
- visual_subtitles：从视频画面提取的字幕证据，可能为空，也可能夹杂英文、标题或识别噪声。

你的唯一任务是以 asr_text 为主稿，纠正可以由上下文或可靠画面字幕共同确定的错别字、同音词、专有名词、数字表达和标点。

强制规则：
1. 禁止总结、润色、扩写、删减、改写、合并、拆分、重排句子或改变原意。
2. 必须保留全部信息、原有顺序和每一个换行；除确有错误的位置外，其他字符保持不变。
3. 画面字幕只能用于确认 asr_text 中已有语句的正确写法，禁止把画面中的标题、标签、英文翻译或无关文字加入逐字稿。
4. 只有当画面字幕与 asr_text 在相同语境中明显对应时才可采信；不确定就保留原文，不得凭空补充原文没有的信息。
5. 数字只能在上下文或对应画面字幕能确定 ASR 识别错误时修正，不能擅自换算或改写格式。
6. 只返回严格 JSON 对象，格式为 {"corrected_text":"完整校正稿"}，不要返回解释、Markdown 或差异列表。
"""


def configured_model() -> str:
    return os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def cache_discriminator() -> str:
    return f"{configured_model()}\n{PROMPT_VERSION}"


def _parse_json(value: str) -> dict:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("DeepSeek 返回的不是 JSON 对象")
    return parsed


def deterministic_diff(original: str, corrected: str, context_chars: int = 16) -> list[dict]:
    """Return program-computed edits. Model output is never trusted for change reporting."""
    matcher = difflib.SequenceMatcher(None, original, corrected, autojunk=False)
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append({
            "type": tag,
            "from": original[i1:i2],
            "to": corrected[j1:j2],
            "original_start": i1,
            "original_end": i2,
            "context_before": original[max(0, i1 - context_chars):i1],
            "context_after": original[i2:i2 + context_chars],
        })
    return changes


def _restore_original_newlines(original: str, corrected: str) -> str:
    """Project original segment breaks onto corrected text without asking the model."""
    if corrected.count("\n") == original.count("\n"):
        return corrected
    original_flat = original.replace("\n", "")
    corrected_flat = corrected.replace("\n", "")
    matcher = difflib.SequenceMatcher(None, original_flat, corrected_flat, autojunk=False)
    opcodes = matcher.get_opcodes()
    original_breaks = []
    flat_offset = 0
    for line in original.split("\n")[:-1]:
        flat_offset += len(line)
        original_breaks.append(flat_offset)

    mapped_breaks = []
    for boundary in original_breaks:
        mapped = None
        for _tag, i1, i2, j1, j2 in opcodes:
            if i1 <= boundary <= i2:
                if i2 == i1:
                    mapped = j2
                else:
                    mapped = j1 + round((boundary - i1) * (j2 - j1) / (i2 - i1))
                break
        if mapped is None:
            mapped = len(corrected_flat)
        mapped_breaks.append(max(0, min(len(corrected_flat), mapped)))

    pieces = []
    previous = 0
    for boundary in mapped_breaks:
        boundary = max(previous, boundary)
        pieces.append(corrected_flat[previous:boundary])
        previous = boundary
    pieces.append(corrected_flat[previous:])
    return "\n".join(pieces)


def _validate(original: str, corrected: str) -> list[dict]:
    if not corrected.strip():
        raise ValueError("DeepSeek 未返回完整校正稿")
    ratio = difflib.SequenceMatcher(None, original, corrected, autojunk=False).ratio()
    if ratio < 0.82:
        raise ValueError("校正幅度超过逐字校对安全阈值")
    delta = abs(len(corrected) - len(original))
    if delta > max(80, int(len(original) * 0.08)):
        raise ValueError("校正稿存在异常增删")
    changes = deterministic_diff(original, corrected)
    if len(changes) > max(240, len(original) // 3):
        raise ValueError("校正处数异常")
    for change in changes:
        before = change["from"]
        after = change["to"]
        if max(len(before), len(after)) > 48:
            raise ValueError("校正稿包含大段改写")
    return changes


def correct_text(raw_text: str, description: str = "", author: str = "", visual_subtitles: str = "") -> dict:
    started = time.monotonic()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    model = configured_model()
    base = {
        "correction_status": "failed",
        "corrected_text": "",
        "correction_changes": [],
        "correction_count": 0,
        "correction_elapsed": None,
        "correction_model": model,
        "correction_actual_model": "",
        "prompt_version": PROMPT_VERSION,
        "correction_parameters": {
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "max_tokens": MAX_TOKENS,
            "response_format": "json_object",
        },
        "correction_error": "",
    }
    if not api_key:
        return {**base, "correction_error": "DeepSeek 后端授权未配置"}
    if not raw_text.strip():
        return {**base, "correction_error": "原始识别稿为空"}

    # Metadata stays excluded: it previously tempted the model to copy labels
    # into the transcript. Visual text is explicitly marked as evidence only.
    user_text = json.dumps({
        "asr_text": raw_text,
        "visual_subtitles": str(visual_subtitles or "")[:16000],
    }, ensure_ascii=False)
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }, ensure_ascii=False).encode("utf-8")

    api_url = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions").strip()
    last_error = "DeepSeek 校正失败"
    for attempt in range(3):
        request = Request(api_url, data=payload, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "siyumenghai-transcript-bc/1.0",
        })
        try:
            with urlopen(request, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
            corrected = str(_parse_json(content).get("corrected_text") or "")
            corrected = _restore_original_newlines(raw_text, corrected)
            changes = _validate(raw_text, corrected)
            usage = result.get("usage") or {}
            return {
                **base,
                "correction_status": "completed",
                "corrected_text": corrected,
                "correction_changes": changes,
                "correction_count": len(changes),
                "correction_elapsed": round(time.monotonic() - started, 3),
                "correction_actual_model": str(result.get("model") or model),
                "correction_error": "",
                "correction_usage": {
                    "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                    "total_tokens": int(usage.get("total_tokens", 0) or 0),
                },
            }
        except HTTPError as error:
            last_error = f"DeepSeek HTTP {error.code}"
        except (URLError, TimeoutError):
            last_error = "DeepSeek 网络请求失败"
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            last_error = str(error)[:160] or "DeepSeek 响应格式不正确"
        except Exception as error:
            last_error = f"DeepSeek 校正异常：{type(error).__name__}"
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    return {
        **base,
        "correction_elapsed": round(time.monotonic() - started, 3),
        "correction_error": last_error,
    }
