#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把知识库按「内容性质」拆成 4 个目录（幂等，可重复执行）。

  cases/share/   石更新主题分享（周一分享、AI工具、公域获客、私域转化、线下课复盘…）
  cases/qa/      石更新个性化答疑（社群问答 + 未来上传的私信/群内答疑）
  cases/course/  石更新课程内容
  cases/peers/   同行案例（运营研究社等，非本人经验）

规则：
- 根目录散落的 .md → peers/
- sdh/ 下按文件名「sdhXXX__类别_标题.md」的类别段判断：含"问答/答疑"→ qa/，其余 → share/
- 已在 share/qa/course/peers 里的文件不动
"""
import re
import shutil
import sys
from pathlib import Path

CASES = Path("/opt/siyumenghai-rag-lite/cases")
GROUPS = ["share", "qa", "course", "peers"]
QA_HINTS = ("问答", "答疑", "问与答", "Q&A", "Q＆A")


def category_of(stem: str) -> str:
    """从 sdhXXX__类别_标题 里取类别段。"""
    if "__" not in stem:
        return ""
    rest = stem.split("__", 1)[1]
    return re.split(r"[_\s]", rest, 1)[0]


def main() -> int:
    if not CASES.exists():
        print("ERROR: cases 目录不存在")
        return 1
    for g in GROUPS:
        (CASES / g).mkdir(exist_ok=True)

    moved = {"peers": 0, "qa": 0, "share": 0}
    errors = []

    # 1) 根目录散落文件 → peers
    for p in sorted(CASES.glob("*.md")):
        try:
            shutil.move(str(p), str(CASES / "peers" / p.name))
            moved["peers"] += 1
        except Exception as e:
            errors.append(f"{p.name}: {e}")

    # 2) sdh/ 按类别拆到 qa / share
    sdh = CASES / "sdh"
    if sdh.is_dir():
        for p in sorted(sdh.glob("*.md")):
            cat = category_of(p.stem)
            target = "qa" if any(h in cat for h in QA_HINTS) else "share"
            try:
                shutil.move(str(p), str(CASES / target / p.name))
                moved[target] += 1
            except Exception as e:
                errors.append(f"{p.name}: {e}")
        # 空目录清理
        try:
            sdh.rmdir()
        except OSError:
            print("NOTE: sdh 目录非空，保留")
    elif sdh.exists():
        print("NOTE: sdh 不是目录，跳过")

    print("移动统计:", moved)
    print("目录分布:")
    total = 0
    for g in GROUPS:
        n = len(list((CASES / g).glob("*.md")))
        total += n
        print(f"  {g:8s} {n:4d}")
    others = [p for p in CASES.glob("*.md")]
    print(f"  根目录残留 {len(others)} 个")
    print(f"  合计 {total + len(others)} 个 .md")
    if errors:
        print("错误:", errors, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
