#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 _agent_kb/articles 的 128 个案例文件名解析元数据，生成 Dify 知识库可用的 CSV。
文件名格式：NNN__标签_标题.md
  - NNN        : 案例编号（001-130，中间有缺号）
  - 标签        : 平台/主题标签（如 小红书引流、私域社群）
  - 标题        : 案例标题
输出 CSV 列：case_id, platform, topic, title, filename
  - platform   : 粗分类（小红书/私域/视频号/抖音/直播/通用），用于 Dify 元数据过滤
  - topic      : 文件名中的细分标签
用法：
  python3 build_metadata.py [源目录] [输出csv]
源目录默认：/Users/murphys/DoubaoWork/chats/2026-09-17/new-chat/_agent_kb/articles
"""
import os
import re
import csv
import sys
from collections import Counter

DEFAULT_SRC = "/Users/murphys/DoubaoWork/chats/2026-09-17/new-chat/_agent_kb/articles"
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb_metadata.csv")

# 主平台分类（按优先级，命中第一个即定为该案例的主平台）
PLATFORM_RULES = [
    ("小红书", ["小红书"]),
    ("视频号", ["视频号"]),
    ("抖音", ["抖音"]),
    ("快手", ["快手"]),
    ("得物", ["得物"]),
    ("闲鱼", ["闲鱼"]),
    ("私域", ["私域", "社群", "会员", "分销", "公转私", "低转高", "复购", "增购", "SCRM"]),
    ("直播", ["直播"]),
    ("通用", ["全平台", "全渠道", "矩阵", "搜索", "GEO", "Agent", "AI搜索", "内容", "爆品",
             "电商", "公转域", "获客", "引流", "IP", "门店", "开店", "新品", "业务规划",
             "团队管理", "运营管理", "预算", "个人成长", "知识付费", "教培", "医生", "素人"]),
]


def classify_platform(topic: str, title: str) -> str:
    text = topic + " " + title
    for platform, keys in PLATFORM_RULES:
        if any(k in text for k in keys):
            return platform
    return "通用"


def parse_filename(fn: str):
    name = fn[:-3] if fn.endswith(".md") else fn
    m = re.match(r"^(\d{1,3})__(.+)$", name)
    if not m:
        return None
    case_id = m.group(1).zfill(3)
    rest = m.group(2)
    topic, title = rest.split("_", 1) if "_" in rest else (rest, "")
    platform = classify_platform(topic, title)
    return case_id, platform, topic, title, fn


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    if not os.path.isdir(src):
        print(f"[ERROR] 源目录不存在: {src}")
        sys.exit(1)

    rows = []
    for fn in sorted(os.listdir(src)):
        if not fn.endswith(".md") or fn == ".DS_Store":
            continue
        parsed = parse_filename(fn)
        if parsed:
            rows.append(parsed)

    rows.sort(key=lambda r: int(r[0]))
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "platform", "topic", "title", "filename"])
        for r in rows:
            w.writerow(r)

    pc = Counter(r[1] for r in rows)
    print(f"共解析 {len(rows)} 个案例 → {out}")
    print("主平台分布：")
    for k, v in pc.most_common():
        print(f"  {k:<8} {v}")


if __name__ == "__main__":
    main()
