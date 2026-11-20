#!/usr/bin/env python3
"""Convert a private vault history export into a safe public daily chat file."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
import ipaddress
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
LOCAL_PATH_RE = re.compile(r"(?m)^/(?:Users|Volumes|private|var|tmp)/[^\r\n]+$")
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
    "名片": "contact",
}
UNAVAILABLE_LABELS = {
    "image": "该消息为图片，本机未保存原始附件，当前无法展示",
    "video": "该消息为视频，本机未保存原始附件，当前无法播放",
    "voice": "该消息为语音，本机未保存原始附件，当前无法播放",
    "file": "该消息为文件，本机未保存原始附件，当前无法下载",
    "sticker": "该消息为表情，无法同步到网站",
    "location": "该消息为位置信息，无法同步到网站",
    "call": "该消息为通话记录，无法同步到网站",
    "unknown": "该消息类型暂时无法同步到网站",
}


def redact(text: str) -> tuple[str, bool]:
    changed = False
    public_urls = []
    def protect_url(match):
        value = match.group(0)
        if safe_url(value):
            public_urls.append(value)
            return f"PUBLICURLPLACEHOLDER{chr(65 + len(public_urls) - 1)}END"
        return value
    text = re.sub(r"https?://[^\s<>，。；]+", protect_url, text)

    def replace(pattern: re.Pattern[str], replacement):
        nonlocal text, changed
        updated, count = pattern.subn(replacement, text)
        if count:
            text, changed = updated, True

    replace(PHONE_RE, lambda match: f"{match.group(1)}****{match.group(3)}")
    replace(ID_RE, lambda match: f"{match.group(1)}********{match.group(3)}")
    replace(BANK_RE, lambda match: f"{match.group(1)} **** **** {match.group(2)}")
    replace(SENSITIVE_LABEL_RE, lambda match: f"{match.group(1)}{match.group(2)}[已脱敏]")
    replace(re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?[^\s<>，。；]*"), "[本机预览链接，无法从其他设备访问]")
    replace(re.compile(r"/(?:Users|Volumes|private|var|tmp)/[^\s<>，。；]+"), "[本机路径已隐藏]")
    replace(re.compile(r"\bwxid_[A-Za-z0-9_]+\b"), "[微信内部标识已隐藏]")
    for index, url in enumerate(public_urls):
        text = text.replace(f"PUBLICURLPLACEHOLDER{chr(65 + index)}END", url)
    return text, changed


def safe_url(value: str) -> str | None:
    value = (value or "").strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "wxapp.tenpay.com", "support.weixin.qq.com"} or host.endswith(".local"):
        return None
    try:
        if not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        pass
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
        title = LOCAL_PATH_RE.sub("", title).strip()
        return title or "链接或文件", "", []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return "链接或文件", "", []

    title = (find_text(root, ".//appmsg/title") or find_text(root, ".//title")
             or find_text(root, ".//finderFeed/desc") or "链接或文件")
    description = find_text(root, ".//appmsg/des") or find_text(root, ".//des")
    url = safe_url(find_text(root, ".//appmsg/url") or find_text(root, ".//url"))
    return title, description, ([{"label": "打开原内容", "url": url}] if url else [])


def parse_system(content: str) -> str:
    content = re.sub(r"^[^\n<]+@chatroom:\s*", "", (content or "").strip())
    if not content.startswith("<"):
        return content or "系统消息"
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return "系统消息"

    revoke = find_text(root, ".//revokemsg/content")
    if revoke:
        return revoke
    plain = find_text(root, ".//plain") or find_text(root, ".//pc_plain")
    if plain:
        return plain
    if root.get("type") == "mmchatroomtopmsg":
        nickname = find_text(root, ".//nickname")
        return f'"{nickname}"置顶了一条消息' if nickname else "群管理员置顶了一条消息"

    template = find_text(root, ".//template")
    nicknames = [node.text.strip() for node in root.findall(".//nickname") if node.text and node.text.strip()]
    history = find_text(root, ".//link[@name='history']/newformattitle") or find_text(root, ".//link[@name='history']/title")
    if "邀请" in template and nicknames:
        if len(nicknames) == 1:
            text = f'邀请"{nicknames[0]}"加入了群聊'
        else:
            text = f'"{nicknames[0]}"邀请"{nicknames[-1]}"加入了群聊'
        return f"{text}，并分享了{history}" if history else text
    return "系统消息"


def load_avatar_map(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {item["name"]: item.get("avatar", "") for item in payload.get("members", [])}


def normalize_member_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = re.sub(r"[\s()（）【】\[\]·._#＃!！,，、~～\-—]+", "", normalized)
    for prefix in ("石董会", "生财", "跟谁学", "小鹅通"):
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
    return normalized


def resolve_avatar(avatars: dict[str, str], sender: str) -> str:
    if sender in avatars:
        return avatars[sender]
    if not sender or sender == "未知群友":
        return ""
    sender_name = normalize_member_name(sender)
    matches = []
    for member_name, avatar in avatars.items():
        normalized = normalize_member_name(member_name)
        if not avatar or not normalized:
            continue
        if sender_name == normalized or (
            min(len(sender_name), len(normalized)) >= 2
            and (sender_name in normalized or normalized in sender_name)
        ):
            matches.append(avatar)
    return matches[0] if len(matches) == 1 else ""


def convert(raw: dict, date: str, owner: str, avatars: dict[str, str], media_map: dict | None = None) -> tuple[dict, dict]:
    media_map = media_map or {}
    messages = []
    redacted_count = 0
    missing_media_count = 0
    unavailable_count = 0
    omitted_sticker_count = 0
    unresolved_link_count = 0

    for index, item in enumerate(raw.get("messages", []), start=1):
        time_value = str(item.get("time", ""))
        media_key = f"{time_value}#{item.get('local_id', '')}"
        attachment = media_map.get(media_key, media_map.get(time_value, {}))
        if not time_value.startswith(f"{date} "):
            continue
        sender = str(item.get("sender") or "未知群友").strip()
        public_type = TYPE_MAP.get(str(item.get("type", "")), "unknown")
        original_content = str(item.get("content") or "").strip()

        # Stickers are decorative and are intentionally omitted from the public archive.
        if public_type == "sticker":
            omitted_sticker_count += 1
            continue
        links: list[dict[str, str]] = []
        media = None

        if public_type == "text" and is_unreadable(original_content):
            text = "该条文字消息无法正确解码，无法同步到网站"
            unavailable_count += 1
        elif public_type == "text":
            text = original_content
            for value in re.findall(r"https?://[^\s<>，。；]+", text):
                url = safe_url(value.rstrip('）)、]'))
                if url:
                    links.append({"label": "打开分享链接", "url": url})
        elif public_type == "link":
            app_subtype = int(item.get("local_type") or 0) >> 32
            if is_unreadable(original_content):
                text = "该消息为链接或文件，内容无法正确解码，无法同步到网站"
                unavailable_count += 1
            else:
                title, description, links = parse_link(original_content)
                attachment_url = str(attachment.get("url") or "")
                if attachment.get("kind") == "file" and attachment_url.startswith("./assets/"):
                    links = [{"label": str(attachment.get("label") or "下载文件"), "url": attachment_url}]
                if app_subtype in {2000, 2001}:
                    public_type = "system"
                    links = []
                    text = "微信红包或转账消息，请在微信中查看；网页不提供领取或支付入口"
                elif app_subtype == 51 or "当前微信版本不支持展示该内容" in title:
                    readable_title = "" if "当前微信版本不支持展示该内容" in title else f"：{title}"
                    text = f"视频号内容{readable_title}\n因为微信未提供可公开访问的原始链接，当前无法同步或跳转"
                elif app_subtype == 33 and not links:
                    text = f"小程序内容：{title}\n因为微信未提供可公开访问的小程序链接，当前无法从网页跳转"
                elif app_subtype == 5 and not links:
                    text = f"公众号或网页内容：{title}\n原内容没有提供可公开访问的跳转链接"
                elif app_subtype in {57, 62} and not links:
                    # WeChat also stores some quoted/replied text as an app message.
                    public_type = "text"
                    text = title
                elif app_subtype == 6 and not links:
                    text = f"文件：{title}\n本机未保存该文件附件，当前无法下载"
                else:
                    text = title if not description else f"{title}\n{description}"
                    if not links:
                        text += "\n原内容没有可公开访问的跳转链接"
        elif public_type == "system":
            text = parse_system(original_content)
        elif public_type == "contact":
            text = str(attachment.get("text") or "微信名片无法从网页直接跳转，请在微信中查看")
        elif public_type in {"image", "video", "voice", "sticker"} and attachment:
            candidate = attachment
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
        was_redacted = was_redacted or bool(attachment.get("redacted"))
        cleaned_links = []
        for link in links:
            label, label_redacted = redact(link["label"])
            cleaned_links.append({"label": label, "url": link["url"]})
            was_redacted = was_redacted or label_redacted
        redacted_count += int(was_redacted)
        if public_type == "link" and not cleaned_links:
            unresolved_link_count += 1

        messages.append({
            "id": f"m{index:03d}",
            "time": time_value,
            "sender": sender,
            "avatar": resolve_avatar(avatars, sender),
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
        "omittedStickerCount": omitted_sticker_count,
        "redactedCount": redacted_count,
        "missingMediaCount": missing_media_count,
        "unresolvedLinkCount": unresolved_link_count,
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
