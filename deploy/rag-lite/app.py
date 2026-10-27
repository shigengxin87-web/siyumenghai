#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
石董会 AI 问答 —— 自研轻量 RAG 服务（Dify 兼容接口）

设计目标（方案 D）：
- 零外部向量库依赖：jieba 中文分词 + 本地 BM25 召回 128 个实战案例。
- 对话走 DeepSeek（api.deepseek.com），模型费极低，无平台费。
- 对外暴露 POST /v1/chat-messages，SSE 协议与 Dify 完全一致，
  agent-proxy（已改造为 Dify 版）与小程序前端均无需任何改动。

对外契约（与 Dify chat-messages 对齐）：
- 请求体：{"inputs":{}, "query":"...", "response_mode":"streaming",
           "conversation_id":"...", "user":"..."}
- 响应：text/event-stream，每行 `data: {"event":"message","answer":"片段"}`，
       结尾 `data: {"event":"message_end","answer":"全文","metadata":{...}}`。
"""

import os
import re
import json
import math
import time
import logging
import asyncio
from pathlib import Path
from collections import defaultdict

import jieba
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("rag-lite")

# ---------------- 配置（环境变量驱动，部署时注入） ----------------
CASES_DIR = os.environ.get("CASES_DIR", "/opt/siyumenghai-rag-lite/cases")
META_CSV = os.environ.get("META_CSV", "/opt/siyumenghai-rag-lite/kb_metadata.csv")
PROMPT_FILE = os.environ.get("PROMPT_FILE", "/opt/siyumenghai-rag-lite/SYSTEM_PROMPT.md")
API_KEY = os.environ.get("API_KEY", "sdh-rag-lite-default")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
TOP_K = int(os.environ.get("TOP_K", 6))
CHUNK_MAX = int(os.environ.get("CHUNK_MAX", 600))
HIST_TTL = int(os.environ.get("HIST_TTL", 3600))  # 多轮历史 TTL（秒）


# ---------------- 系统提示词（复用迁移包，剥离 frontmatter） ----------------
def load_prompt() -> str:
    p = Path(PROMPT_FILE)
    if not p.exists():
        return "你是一位资深运营顾问，背靠「运营研究社 128 实战案例知识库」。\n\n下面是知识库检索到的相关案例内容：\n\n{{#context#}}\n\n你的所有回答必须且只能基于上面这段检索内容，不凭空编造。"
    txt = p.read_text(encoding="utf-8")
    # 去掉 --- frontmatter ---
    m = re.match(r"^---\n.*?\n---\n", txt, re.S)
    if m:
        txt = txt[m.end():]
    # 去掉开头的用法说明（> 引用行），直到第一个 # 标题
    lines = txt.split("\n")
    out, started = [], False
    for ln in lines:
        if not started:
            if ln.startswith("#"):
                started = True
            else:
                continue
        out.append(ln)
    return "\n".join(out).strip()


SYSTEM_PROMPT = load_prompt()


# ---------------- BM25（Okapi，纯算法，零依赖） ----------------
class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.docs = docs
        n = len(docs) or 1
        self.avgdl = sum(len(d) for d in docs) / n
        self.f = []
        self.df = {}
        for d in docs:
            freq = defaultdict(int)
            for w in d:
                freq[w] += 1
            self.f.append(freq)
            for w in freq:
                self.df[w] = self.df.get(w, 0) + 1
        self.idf = {
            w: math.log(1 + (n - df + 0.5) / (df + 0.5))
            for w, df in self.df.items()
        }

    def scores(self, q):
        out = []
        for fi, dl in zip(self.f, (len(d) for d in self.docs)):
            s = 0.0
            for w in q:
                c = fi.get(w, 0)
                if c:
                    idf = self.idf.get(w, 0)
                    s += idf * (c * (self.k1 + 1)) / (
                        c + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                    )
            out.append(s)
        return out


# ---------------- 案例加载与切分 ----------------
def load_cases():
    meta = {}
    mp = Path(META_CSV)
    if mp.exists():
        import csv

        with mp.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                meta[(row.get("case_id") or "").strip()] = row

    chunks = []
    files = sorted(Path(CASES_DIR).rglob("*.md"))
    for md in files:
        cid = md.stem.split("__")[0]
        m = meta.get(cid, {})
        platform = (m.get("platform") or "").strip()
        text = md.read_text(encoding="utf-8")
        text = re.sub(r"\r\n", "\n", text)
        # 按分隔线 --- 切块
        for part in re.split(r"\n\s*-{3,}\s*\n", text):
            part = part.strip()
            if len(part) < 40:
                continue
            for sub in split_long(part):
                chunks.append(
                    {"case_id": cid, "platform": platform, "text": sub}
                )
    log.info(
        "loaded %d chunks from %d case files", len(chunks), len(files)
    )
    return chunks


def split_long(text, maxlen=CHUNK_MAX):
    if len(text) <= maxlen:
        return [text]
    segs = re.split(r"(?<=[。！？\n])", text)
    out, cur = [], ""
    for s in segs:
        if cur and len(cur) + len(s) > maxlen:
            out.append(cur.strip())
            cur = s
        else:
            cur += s
    if cur.strip():
        out.append(cur.strip())
    return out


chunks = load_cases()
doc_tokens = [list(jieba.cut(c["text"])) for c in chunks]
bm25 = BM25(doc_tokens)


def retrieve(query, n=TOP_K):
    q = list(jieba.cut(query))
    sc = bm25.scores(q)
    order = sorted(range(len(sc)), key=lambda i: -sc[i])
    seen = defaultdict(int)
    picked = []
    for i in order:
        if sc[i] <= 0:
            continue
        c = chunks[i]
        if seen[c["case_id"]] >= 2:  # 同一案例最多取 2 段
            continue
        seen[c["case_id"]] += 1
        picked.append((sc[i], c))
        if len(picked) >= n:
            break
    return picked


def build_context(picked):
    blocks = []
    for _, c in picked:
        head = f"【案例#{c['case_id']}"
        if c["platform"]:
            head += f"｜{c['platform']}"
        head += "】"
        blocks.append(head + "\n" + c["text"])
    return "\n\n".join(blocks)


# ---------------- 多轮历史（内存，带 TTL） ----------------
history = {}  # conv_id -> (timestamp, [msgs])


def get_history(cid):
    item = history.get(cid)
    if not item:
        return []
    ts, msgs = item
    if time.time() - ts > HIST_TTL:
        history.pop(cid, None)
        return []
    return msgs


def set_history(cid, msgs):
    history[cid] = (time.time(), msgs[-10:])


# ---------------- DeepSeek 流式 ----------------
async def stream_deepseek(messages):
    if not DEEPSEEK_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        async with client.stream(
            "POST",
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": messages,
                "stream": True,
                "max_tokens": 1500,
                "temperature": 0.3,
            },
        ) as r:
            if r.status_code != 200:
                body = await r.aread()
                raise RuntimeError(f"deepseek http {r.status_code}: {body[:200]}")
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                delta = (
                    obj.get("choices", [{}])[0]
                    .get("delta", {})
                    .get("content", "")
                )
                if delta:
                    yield delta


# ---------------- FastAPI ----------------
app = FastAPI()


def sse(obj):
    return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")


def json_error(code, msg):
    return JSONResponse(status_code=code, content={"error": {"message": msg}})


@app.post("/v1/chat-messages")
async def chat_messages(req: Request):
    auth = req.headers.get("Authorization", "")
    if API_KEY and not auth.endswith(API_KEY):
        return json_error(401, "invalid api key")
    try:
        body = await req.json()
    except Exception:
        return json_error(400, "invalid json")

    query = (body.get("query") or "").strip()
    if not query:
        return json_error(400, "empty query")
    conv_id = body.get("conversation_id") or "anon"
    user = body.get("user") or "anon"

    picked = retrieve(query)
    ctx = build_context(picked)
    sys_prompt = SYSTEM_PROMPT.replace(
        "{{#context#}}",
        ctx
        or "（知识库中暂未找到完全对应的案例，请根据最接近的相关内容给参考方向，并说明这是类比推演）",
    )
    hist = get_history(conv_id)
    messages = [{"role": "system", "content": sys_prompt}] + hist + [
        {"role": "user", "content": query}
    ]
    log.info(
        "conv=%s user=%s query=%r recalled=%d",
        conv_id,
        user,
        query[:40],
        len(picked),
    )

    async def gen():
        full = ""
        try:
            async for delta in stream_deepseek(messages):
                full += delta
                yield sse({"event": "message", "answer": delta})
            set_history(
                conv_id,
                hist
                + [
                    {"role": "user", "content": query},
                    {"role": "assistant", "content": full},
                ],
            )
            yield sse(
                {
                    "event": "message_end",
                    "answer": full,
                    "metadata": {"usage": {}},
                }
            )
        except Exception:
            log.exception("stream error")
            if not full:
                yield sse({"event": "error", "message": "服务暂时不可用"})
            else:
                yield sse(
                    {"event": "message_end", "answer": full, "metadata": {}}
                )

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "chunks": len(chunks),
        "cases": len(set(c["case_id"] for c in chunks)),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8080)))
