#!/usr/bin/env python3
"""Convert a private vault history export into a safe public daily chat file."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
ID_RE = re.compile(r"(?<!\w)(\d{6})(\d{8})(\d{3}[\dXx])(?!\w)")
BANK_RE = re.compile(r"(?<!\d)(\d{4})\d{8,11}(\d{4})(?!\d)")
SENSITIVE_LABEL_RE = re.compile(
    r"((?:收货|家庭|详细)?地址|身份证号?|银行卡号?|订单号|支付单号|交易单号)(\s*[：:]\s*)([^\s，。；;]{4,})"
)
TYPE_MAP = {
    "文本": "text",
    "链接/文件": "link",
    "图片": "image",
    "视频": "video",
    "语音": "voice",
    "文件": "file",
    "表情": "sticker",
    "位置": "location",
    "通话": "call",
    "系统": "system",
}
UNAVAILABLE_LABELS = {
    "image": "该消息为图片，无法同步到网站",
    "video": "该消息为视频，无法同步到网站",
    "voice": "该消息为语音，无法同步到网站",
    "file": "该消息为文件，无法同步到网站",
    "sticker": "该消息为表情，无法同步到网站",
    "location": "该消息为位置信息，无法同步到网站",
    "call": "该消息为通话记录，无法同步到网站",
    "unknown": "该消息类型暂时无法同步到网站",
}


def redact(text: str) -> tuple[str, bool]:
    changed = False

    def replace(pattern: re.Pattern[str], replacement):
        nonlocal text, changed
        updated, count = pattern.subn(replacement, text)
        if count:
            text, changed = updated, True

    replace(PHONE_RE, lambda match: f"{match.group(1)}****{match.group(3)}")
    replace(ID_RE, lambda match: f"{match.group(1)}********{match.group(3)}")
    replace(BANK_RE, lambda match: f"{match.group(1)} **** **** {match.group(2)}")
    replace(SENSITIVE_LABEL_RE, lambda match: f"{match.group(1)}{match.group(2)}[已脱敏]")
    return text, changed


def safe_url(value: str) -> str | None:
    value = (value or "").strip()
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def is_unreadable(value: str) -> bool:
    if not value:
        return False
    replacement_count = value.count("\ufffd")
    control_count = sum(ord(character) < 32 and character not in "\n\r\t" for character in value)
    return replacement_count / len(value) > 0.08 or control_count / len(value) > 0.03


def find_text(root: ET.Element, path: str) -> str:
    return (root.findtext(path) or "").strip()


def parse_link(content: str) -> tuple[str, str, list[dict[str, str]]]:
    if not content.lstrip().startswith("<"):
        title = re.sub(r"^\[(?:链接|文件|链接/文件|小程序)\]\s*", "", content).strip()
        return title or "链接或文件", "", []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return "链接或文件", "", []

    title = find_text(root, ".//appmsg/title") or find_text(root, ".//title") or "链接或文件"
    description = find_text(root, ".//appmsg/des") or find_text(root, ".//des")
    url = safe_url(find_text(root, ".//appmsg/url") or find_text(root, ".//url"))
    return title, description, ([{"label": "打开原内容", "url": url}] if url else [])


def load_avatar_map(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {item["name"]: item.get("avatar", "") for item in payload.get("members", [])}


def convert(raw: dict, date: str, owner: str, avatars: dict[str, str], media_map: dict | None = None) -> tuple[dict, dict]:
    media_map = media_map or {}
    messages = []
    redacted_count = 0
    missing_media_count = 0
    unavailable_count = 0

    for index, item in enumerate(raw.get("messages", []), start=1):
        time_value = str(item.get("time", ""))
        if not time_value.startswith(f"{date} "):
            continue
        sender = str(item.get("sender") or "未知群友").strip()
        public_type = TYPE_MAP.get(str(item.get("type", "")), "unknown")
        original_content = str(item.get("content") or "").strip()
        links: list[dict[str, str]] = []
        media = None

        if public_type == "text" and is_unreadable(original_content):
            text = "该条文字消息无法正确解码，无法同步到网站"
            unavailable_count += 1
        elif public_type == "text":
            text = original_content
        elif public_type == "link":
            if is_unreadable(original_content):
                text = "该消息为链接或文件，内容无法正确解码，无法同步到网站"
                unavailable_count += 1
            else:
                title, description, links = parse_link(original_content)
                text = title if not description else f"{title}\n{description}"
                if not links:
                    text += "\n原内容没有可公开访问的跳转链接"
        elif public_type == "system":
            text = original_content or "系统消息"
        elif public_type in {"image", "video", "voice", "sticker"} and time_value in media_map:
            candidate = media_map[time_value]
            media_url = str(candidate.get("url") or "")
            if media_url.startswith("./assets/"):
                media = {
                    "kind": public_type,
                    "url": media_url,
                    "alt": str(candidate.get("alt") or f"{sender}分享的{item.get('type', '媒体')}")
                }
                text = str(candidate.get("text") or "")
            else:
                text = UNAVAILABLE_LABELS.get(public_type, UNAVAILABLE_LABELS["unknown"])
                missing_media_count += 1
        else:
            text = UNAVAILABLE_LABELS.get(public_type, UNAVAILABLE_LABELS["unknown"])
            missing_media_count += 1

        text, was_redacted = redact(text)
        cleaned_links = []
        for link in links:
            label, label_redacted = redact(link["label"])
            cleaned_links.append({"label": label, "url": link["url"]})
            was_redacted = was_redacted or label_redacted
        redacted_count += int(was_redacted)

        messages.append({
            "id": f"m{index:03d}",
            "time": time_value,
            "sender": sender,
            "avatar": avatars.get(sender, ""),
            "side": "right" if sender == owner else "left",
            "type": public_type,
            "text": text,
            "links": cleaned_links,
            "media": media,
            "redacted": was_redacted,
        })

    payload = {
        "version": 1,
        "date": date,
        "timezone": "Asia/Shanghai",
        "messages": messages,
    }
    report = {
        "date": date,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sourceCount": len(raw.get("messages", [])),
        "displayedCount": len(messages),
        "redactedCount": redacted_count,
        "missingMediaCount": missing_media_count,
        "unavailableCount": unavailable_count,
    }
    return payload, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--members", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--owner", default="石更新（23:00睡觉）")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--media-manifest", type=Path)
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    media_map = json.loads(args.media_manifest.read_text(encoding="utf-8")) if args.media_manifest else {}
    payload, report = convert(raw, args.date, args.owner, load_avatar_map(args.members), media_map)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
