#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
石董会 AI 问答 —— 管理后台（自研，对标 Dify/Coze 控制台的常用功能）

功能：
- 密码登录（会话 Cookie）
- 概览：文档数 / 切片数 / 模型 / 服务状态
- 知识库：列出、上传（md/txt/pdf/docx，自动转 markdown）、编辑、删除、重建索引
- 提示词：在线编辑人设/约束，保存即热更新（无需重启）
- 测试：页内直接提问，验证改动效果
- 设置：模型名 / 温度 / 最大长度 / 召回条数，保存后重启生效
- 日志：最近问答日志

运行：uvicorn admin:app --host 127.0.0.1 --port 8090
"""

import os
import io
import re
import csv
import json
import hmac
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime

import httpx
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse

BASE_DIR = Path(os.environ.get("RAG_DIR", "/opt/siyumenghai-rag-lite"))
CASES_DIR = Path(os.environ.get("CASES_DIR", str(BASE_DIR / "cases")))
PROMPT_FILE = Path(os.environ.get("PROMPT_FILE", str(BASE_DIR / "SYSTEM_PROMPT.md")))
ENV_FILE = Path(os.environ.get("ENV_FILE", str(BASE_DIR / "env")))
META_CSV = Path(os.environ.get("META_CSV", str(BASE_DIR / "kb_metadata.csv")))

RAG_URL = os.environ.get("RAG_URL", "http://127.0.0.1:8080")
API_KEY = os.environ.get("API_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "sdh-admin-secret-change-me")
RAG_SERVICE = os.environ.get("RAG_SERVICE", "siyumenghai-rag-lite")
COOKIE = "sdh_admin"

app = FastAPI(title="石董会 AI 管理后台")


# ---------------- 认证 ----------------
def _token() -> str:
    raw = (ADMIN_PASSWORD or "empty").encode("utf-8")
    return hmac.new(SESSION_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def authed(req: Request) -> bool:
    if not ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(req.cookies.get(COOKIE, ""), _token())


def deny():
    return JSONResponse(status_code=401, content={"error": "unauthorized"})


# ---------------- 工具函数 ----------------
def _safe_path(name: str) -> Path | None:
    """只允许访问 CASES_DIR 下的 .md 文件，防目录穿越。"""
    if not name or "/" in name or "\\" in name or not name.endswith(".md"):
        return None
    p = (CASES_DIR / name).resolve()
    try:
        p.relative_to(CASES_DIR.resolve())
    except Exception:
        return None
    return p if p.is_file() else None


def _extract_text(filename: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith((".md", ".markdown", ".txt")):
        for enc in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", "ignore")
    if lower.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages)
    if lower.endswith(".docx"):
        import docx

        d = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs)
    raise ValueError("只支持 md / txt / pdf / docx 文件（旧版 .doc 请另存为 .docx）")


def _append_meta(cid: str, platform: str, topic: str) -> None:
    if not META_CSV.exists():
        return
    try:
        with META_CSV.open(encoding="utf-8-sig") as f:
            fields = csv.DictReader(f).fieldnames or []
        if not fields:
            return
        row = {k: "" for k in fields}
        for k in fields:
            kl = k.lower()
            if "case" in kl or kl == "id":
                row[k] = cid
            elif "platform" in kl or "来源" in k:
                row[k] = platform
            elif "topic" in kl or "title" in kl or "主题" in k or "标题" in k:
                row[k] = topic
        with META_CSV.open("a", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writerow(row)
    except Exception:
        pass


def _read_env() -> dict:
    out = {}
    if ENV_FILE.exists():
        for ln in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def _upsert_env(updates: dict) -> None:
    lines = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    seen = set()
    for i, ln in enumerate(lines):
        if "=" in ln and not ln.strip().startswith("#"):
            k = ln.split("=", 1)[0].strip()
            if k in updates:
                lines[i] = f"{k}={updates[k]}"
                seen.add(k)
    for k, v in updates.items():
        if k not in seen:
            lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _reload_rag() -> dict:
    with httpx.Client(timeout=30.0) as c:
        r = c.post(
            f"{RAG_URL}/internal/reload",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        r.raise_for_status()
        return r.json()


def _rag_health() -> dict:
    try:
        with httpx.Client(timeout=5.0) as c:
            return c.get(f"{RAG_URL}/health").json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _service_state() -> str:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", RAG_SERVICE],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _ask_rag(query: str) -> str:
    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "streaming",
        "conversation_id": "",
        "user": f"admin-test-{datetime.now().strftime('%H%M%S')}",
    }
    full = ""
    with httpx.Client(timeout=90.0) as c:
        with c.stream(
            "POST",
            f"{RAG_URL}/v1/chat-messages",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as r:
            if r.status_code != 200:
                body = r.read()
                raise RuntimeError(f"rag http {r.status_code}: {body[:200]}")
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                try:
                    obj = json.loads(line[5:].strip())
                except Exception:
                    continue
                if obj.get("event") == "message":
                    full += obj.get("answer", "")
    return full


# ---------------- 路由 ----------------
@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)


@app.post("/login")
async def login(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    pwd = (body.get("password") or "").strip()
    if not ADMIN_PASSWORD or not hmac.compare_digest(pwd, ADMIN_PASSWORD):
        return JSONResponse(status_code=401, content={"error": "密码不正确"})
    resp = JSONResponse({"ok": True})
    secure = req.headers.get("x-forwarded-proto", "") == "https"
    resp.set_cookie(
        COOKIE,
        _token(),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


@app.post("/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.get("/api/stats")
async def stats(req: Request):
    if not authed(req):
        return deny()
    docs = list(CASES_DIR.rglob("*.md")) if CASES_DIR.exists() else []
    h = _rag_health()
    env = _read_env()
    return {
        "docs": len(docs),
        "chunks": h.get("chunks", 0),
        "cases": h.get("cases", 0),
        "rag_ok": bool(h.get("ok")),
        "service": _service_state(),
        "model": env.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "temperature": env.get("TEMPERATURE", "0.3"),
        "max_tokens": env.get("MAX_TOKENS", "1500"),
        "top_k": env.get("TOP_K", "6"),
    }


@app.get("/api/kb")
async def kb_list(req: Request):
    if not authed(req):
        return deny()
    items = []
    if CASES_DIR.exists():
        for p in sorted(CASES_DIR.rglob("*.md")):
            st = p.stat()
            items.append(
                {
                    "name": str(p.relative_to(CASES_DIR)),
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                }
            )
    return {"items": items}


@app.get("/api/kb/file")
async def kb_get(req: Request, name: str):
    if not authed(req):
        return deny()
    p = _safe_path(name)
    if not p:
        return JSONResponse(status_code=404, content={"error": "文件不存在"})
    return {"name": name, "content": p.read_text(encoding="utf-8")}


@app.post("/api/kb/file")
async def kb_save(req: Request):
    if not authed(req):
        return deny()
    body = await req.json()
    p = _safe_path(body.get("name", ""))
    if not p:
        return JSONResponse(status_code=400, content={"error": "文件不存在"})
    p.write_text(body.get("content", ""), encoding="utf-8")
    _reload_rag()
    return {"ok": True}


@app.post("/api/kb/delete")
async def kb_delete(req: Request):
    if not authed(req):
        return deny()
    body = await req.json()
    p = _safe_path(body.get("name", ""))
    if not p:
        return JSONResponse(status_code=400, content={"error": "文件不存在"})
    p.unlink()
    _reload_rag()
    return {"ok": True}


@app.post("/api/kb/upload")
async def kb_upload(
    req: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    platform: str = Form("用户上传"),
):
    if not authed(req):
        return deny()
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"error": "文件超过 25MB"})
    try:
        text = _extract_text(file.filename or "", data)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    text = text.replace("\r\n", "\n").strip()
    if len(text) < 40:
        return JSONResponse(status_code=400, content={"error": "解析出的内容太短"})

    cid = "u" + datetime.now().strftime("%y%m%d%H%M%S")
    name = re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", title or Path(file.filename or "doc").stem)[:40]
    dest = CASES_DIR / f"{cid}__{name}.md"
    dest.write_text(text, encoding="utf-8")
    _append_meta(cid, platform or "用户上传", title)
    result = _reload_rag()
    return {"ok": True, "name": str(dest.relative_to(CASES_DIR)), "reload": result}


@app.get("/api/prompt")
async def prompt_get(req: Request):
    if not authed(req):
        return deny()
    txt = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else ""
    return {"content": txt}


@app.post("/api/prompt")
async def prompt_save(req: Request):
    if not authed(req):
        return deny()
    body = await req.json()
    content = body.get("content", "")
    if len(content.strip()) < 20:
        return JSONResponse(status_code=400, content={"error": "提示词太短"})
    PROMPT_FILE.write_text(content, encoding="utf-8")
    result = _reload_rag()
    return {"ok": True, "reload": result}


@app.post("/api/reload")
async def reload_now(req: Request):
    if not authed(req):
        return deny()
    return {"ok": True, "reload": _reload_rag()}


@app.post("/api/test")
async def test_chat(req: Request):
    if not authed(req):
        return deny()
    body = await req.json()
    q = (body.get("query") or "").strip()
    if not q:
        return JSONResponse(status_code=400, content={"error": "请输入问题"})
    try:
        ans = _ask_rag(q)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    return {"answer": ans}


@app.get("/api/settings")
async def settings_get(req: Request):
    if not authed(req):
        return deny()
    env = _read_env()
    key = env.get("DEEPSEEK_API_KEY", "")
    return {
        "model": env.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "temperature": env.get("TEMPERATURE", "0.3"),
        "max_tokens": env.get("MAX_TOKENS", "1500"),
        "top_k": env.get("TOP_K", "6"),
        "api_key_masked": (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("已配置" if key else "未配置"),
    }


@app.post("/api/settings")
async def settings_save(req: Request):
    if not authed(req):
        return deny()
    body = await req.json()
    updates = {}
    if body.get("model"):
        updates["DEEPSEEK_MODEL"] = str(body["model"]).strip()
    if body.get("temperature") not in (None, ""):
        updates["TEMPERATURE"] = str(body["temperature"]).strip()
    if body.get("max_tokens") not in (None, ""):
        updates["MAX_TOKENS"] = str(body["max_tokens"]).strip()
    if body.get("top_k") not in (None, ""):
        updates["TOP_K"] = str(body["top_k"]).strip()
    if body.get("deepseek_api_key"):
        updates["DEEPSEEK_API_KEY"] = str(body["deepseek_api_key"]).strip()
    if not updates:
        return JSONResponse(status_code=400, content={"error": "没有可保存的项"})
    _upsert_env(updates)
    try:
        subprocess.run(["systemctl", "restart", RAG_SERVICE], timeout=30, check=False)
    except Exception:
        pass
    return {"ok": True, "note": "已保存并重启服务，约 8 秒后生效"}


@app.get("/api/logs")
async def logs(req: Request):
    if not authed(req):
        return deny()
    try:
        r = subprocess.run(
            ["journalctl", "-u", RAG_SERVICE, "-n", "150", "--no-pager", "-o", "cat"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {"text": r.stdout or "(暂无日志)"}
    except Exception as e:
        return {"text": f"读取日志失败：{e}"}


# ---------------- 前端 ----------------
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>石董会 · AI 管理后台</title>
<style>
  :root{
    --bg:#f4f5f9; --panel:#ffffff; --ink:#15151d; --muted:#6b7280;
    --line:#e6e8ef; --accent:#7c3aed; --accent2:#a855f7; --ok:#16a34a;
    --warn:#d97706; --bad:#dc2626; --dark:#141420;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
       background:var(--bg);color:var(--ink);font-size:14px}
  a{color:var(--accent);text-decoration:none}
  .hide{display:none!important}

  /* 登录 */
  #login{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
  .login-card{width:100%;max-width:380px;background:var(--panel);border-radius:18px;
    padding:36px 30px;box-shadow:0 20px 60px rgba(20,20,40,.12)}
  .login-card h1{font-size:20px;margin:0 0 4px}
  .login-card p{color:var(--muted);margin:0 0 24px;font-size:13px}
  .brand-dot{display:inline-block;width:10px;height:10px;border-radius:50%;
    background:linear-gradient(135deg,var(--accent),var(--accent2));margin-right:8px}
  input[type=password],input[type=text],input[type=number],textarea,select{
    width:100%;padding:11px 13px;border:1px solid var(--line);border-radius:10px;
    font-size:14px;font-family:inherit;background:#fbfbfe;color:var(--ink);outline:none}
  input:focus,textarea:focus,select:focus{border-color:var(--accent);background:#fff}
  button{cursor:pointer;font-family:inherit;font-size:14px;border:none;border-radius:10px;
    padding:10px 18px;transition:.15s}
  .btn-primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;font-weight:600}
  .btn-primary:hover{filter:brightness(1.07)}
  .btn-ghost{background:#fff;border:1px solid var(--line);color:var(--ink)}
  .btn-ghost:hover{border-color:var(--accent);color:var(--accent)}
  .btn-danger{background:#fff;border:1px solid #f0c4c4;color:var(--bad)}
  .btn-danger:hover{background:#fdf2f2}
  .btn-sm{padding:6px 12px;font-size:13px;border-radius:8px}

  /* 布局 */
  #app{display:flex;min-height:100vh}
  .sidebar{width:216px;background:var(--dark);color:#cfd0dd;padding:22px 14px;
    display:flex;flex-direction:column;gap:6px;flex-shrink:0}
  .sidebar .logo{color:#fff;font-weight:700;font-size:15px;padding:0 10px 18px;
    display:flex;align-items:center;gap:8px}
  .sidebar .logo .dot{width:9px;height:9px;border-radius:50%;
    background:linear-gradient(135deg,var(--accent),var(--accent2))}
  .nav-item{padding:10px 12px;border-radius:9px;color:#a9aab8;font-size:14px;
    cursor:pointer;display:flex;align-items:center;gap:9px}
  .nav-item:hover{background:rgba(255,255,255,.06);color:#fff}
  .nav-item.active{background:rgba(124,58,237,.22);color:#fff;font-weight:600}
  .sidebar .spacer{flex:1}
  .sidebar .foot{font-size:11px;color:#6d6e7e;padding:8px 12px;line-height:1.5}

  .main{flex:1;min-width:0;display:flex;flex-direction:column}
  .topbar{display:flex;align-items:center;justify-content:space-between;
    padding:18px 28px;background:#fff;border-bottom:1px solid var(--line)}
  .topbar h2{margin:0;font-size:17px}
  .topbar .sub{color:var(--muted);font-size:12px;margin-top:2px}
  .content{padding:24px 28px;flex:1;overflow:auto}

  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;
    padding:20px;margin-bottom:18px}
  .card h3{margin:0 0 14px;font-size:15px}
  .grid{display:grid;gap:16px}
  .g4{grid-template-columns:repeat(4,1fr)}
  .g2{grid-template-columns:repeat(2,1fr)}
  @media(max-width:900px){.g4{grid-template-columns:repeat(2,1fr)}.g2{grid-template-columns:1fr}}
  @media(max-width:720px){
    #app{flex-direction:column}
    .sidebar{width:100%;flex-direction:row;overflow-x:auto;padding:10px;gap:4px}
    .sidebar .logo,.sidebar .spacer,.sidebar .foot{display:none}
    .nav-item{white-space:nowrap;padding:8px 12px}
    .content{padding:16px}
    .topbar{padding:14px 16px}
  }

  .stat{background:#fff;border:1px solid var(--line);border-radius:13px;padding:18px}
  .stat .k{color:var(--muted);font-size:12px;margin-bottom:8px}
  .stat .v{font-size:26px;font-weight:700;letter-spacing:-.5px}
  .stat .v small{font-size:12px;font-weight:500;color:var(--muted);margin-left:4px}
  .badge{display:inline-block;padding:3px 9px;border-radius:20px;font-size:12px;font-weight:600}
  .badge.ok{background:#e8f7ee;color:var(--ok)}
  .badge.bad{background:#fdecec;color:var(--bad)}
  .badge.mid{background:#fdf3e6;color:var(--warn)}

  table{width:100%;border-collapse:collapse}
  th,td{text-align:left;padding:11px 10px;border-bottom:1px solid var(--line);font-size:13px}
  th{color:var(--muted);font-weight:500;font-size:12px}
  td.name{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
  tr:hover td{background:#fafafe}

  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .field{margin-bottom:16px}
  .field label{display:block;font-size:12.5px;color:var(--muted);margin-bottom:6px}
  textarea{resize:vertical;min-height:120px;line-height:1.65}
  .mono{font-family:ui-monospace,Menlo,monospace;font-size:12px;white-space:pre-wrap;
    background:#0f0f18;color:#d6d7e3;border-radius:10px;padding:14px;line-height:1.6;
    max-height:420px;overflow:auto}
  .hint{color:var(--muted);font-size:12px;line-height:1.6}
  .toast{position:fixed;right:20px;bottom:20px;background:#15151d;color:#fff;
    padding:12px 18px;border-radius:10px;font-size:13px;opacity:0;transform:translateY(10px);
    transition:.25s;pointer-events:none;z-index:99;max-width:360px}
  .toast.show{opacity:1;transform:translateY(0)}
  .drop{border:2px dashed var(--line);border-radius:12px;padding:26px;text-align:center;
    color:var(--muted);cursor:pointer;transition:.15s}
  .drop:hover,.drop.over{border-color:var(--accent);background:#faf7ff;color:var(--accent)}
  .modal-bg{position:fixed;inset:0;background:rgba(15,15,25,.5);display:flex;
    align-items:center;justify-content:center;padding:20px;z-index:50}
  .modal{background:#fff;border-radius:16px;width:100%;max-width:900px;max-height:88vh;
    display:flex;flex-direction:column;overflow:hidden}
  .modal .mhead{padding:16px 20px;border-bottom:1px solid var(--line);
    display:flex;justify-content:space-between;align-items:center}
  .modal .mbody{padding:18px 20px;overflow:auto;flex:1}
  .modal .mfoot{padding:14px 20px;border-top:1px solid var(--line);display:flex;
    justify-content:flex-end;gap:10px}
  .answer{white-space:pre-wrap;line-height:1.75;background:#fafafe;border:1px solid var(--line);
    border-radius:12px;padding:16px;min-height:80px}
  .qchip{display:inline-block;padding:7px 12px;border:1px solid var(--line);border-radius:20px;
    font-size:12.5px;margin:0 8px 8px 0;cursor:pointer;background:#fff}
  .qchip:hover{border-color:var(--accent);color:var(--accent)}
  .spin{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.4);
    border-top-color:#fff;border-radius:50%;animation:sp .7s linear infinite;vertical-align:-2px}
  @keyframes sp{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<!-- 登录 -->
<div id="login">
  <div class="login-card">
    <h1><span class="brand-dot"></span>石董会 AI 管理后台</h1>
    <p>管理知识库、人设与模型配置</p>
    <div class="field">
      <label>管理密码</label>
      <input id="pwd" type="password" placeholder="请输入密码" autocomplete="current-password">
    </div>
    <button class="btn-primary" style="width:100%" id="loginBtn">进入后台</button>
    <div class="hint" id="loginErr" style="color:var(--bad);margin-top:12px"></div>
  </div>
</div>

<!-- 应用 -->
<div id="app" class="hide">
  <aside class="sidebar">
    <div class="logo"><span class="dot"></span>石董会 · AI 助教</div>
    <div class="nav-item active" data-tab="overview">概览</div>
    <div class="nav-item" data-tab="kb">知识库</div>
    <div class="nav-item" data-tab="prompt">提示词 / 人设</div>
    <div class="nav-item" data-tab="test">测试问答</div>
    <div class="nav-item" data-tab="settings">模型设置</div>
    <div class="nav-item" data-tab="logs">运行日志</div>
    <div class="spacer"></div>
    <div class="foot">独立部署 · 无平台费<br>数据全在你自己服务器</div>
  </aside>

  <div class="main">
    <div class="topbar">
      <div>
        <h2 id="pageTitle">概览</h2>
        <div class="sub" id="pageSub">问答服务运行状态</div>
      </div>
      <button class="btn-ghost btn-sm" id="logoutBtn">退出登录</button>
    </div>

    <div class="content">
      <!-- 概览 -->
      <section id="tab-overview">
        <div class="grid g4" style="margin-bottom:18px">
          <div class="stat"><div class="k">知识库文档</div><div class="v" id="s-docs">—</div></div>
          <div class="stat"><div class="k">检索切片</div><div class="v" id="s-chunks">—</div></div>
          <div class="stat"><div class="k">案例数</div><div class="v" id="s-cases">—</div></div>
          <div class="stat"><div class="k">服务状态</div><div class="v" id="s-state">—</div></div>
        </div>
        <div class="card">
          <h3>当前配置</h3>
          <div class="grid g2">
            <div class="hint">生成模型：<b id="s-model">—</b></div>
            <div class="hint">温度：<b id="s-temp">—</b> ｜ 最大长度：<b id="s-max">—</b> ｜ 召回条数：<b id="s-topk">—</b></div>
          </div>
          <div class="row" style="margin-top:16px">
            <button class="btn-primary btn-sm" id="reloadBtn">重建索引</button>
            <span class="hint">上传或编辑知识库后会自动重建；也可手动点这里。</span>
          </div>
        </div>
        <div class="card">
          <h3>快速试问</h3>
          <div class="row">
            <input id="quickQ" type="text" placeholder="输入一个问题，直接调用线上服务" style="flex:1;min-width:220px">
            <button class="btn-primary btn-sm" id="quickBtn">发送</button>
          </div>
          <div class="answer" id="quickA" style="margin-top:14px">回答会显示在这里。</div>
        </div>
      </section>

      <!-- 知识库 -->
      <section id="tab-kb" class="hide">
        <div class="card">
          <h3>上传资料</h3>
          <div class="row" style="margin-bottom:12px">
            <input id="upTitle" type="text" placeholder="标题（可选）" style="flex:1;min-width:180px">
            <input id="upPlatform" type="text" placeholder="来源/分类（默认：用户上传）" style="flex:1;min-width:180px">
          </div>
          <div class="drop" id="drop">点击选择文件，或把文件拖到这里<br>
            <span class="hint">支持 md / txt / pdf / docx，自动转成知识库文本</span></div>
          <input type="file" id="fileInput" class="hide" accept=".md,.txt,.pdf,.docx">
        </div>
        <div class="card">
          <div class="row" style="justify-content:space-between;margin-bottom:10px">
            <h3 style="margin:0">知识库文件 <span class="hint" id="kbCount"></span></h3>
            <button class="btn-ghost btn-sm" id="kbRefresh">刷新</button>
          </div>
          <div style="overflow:auto">
            <table>
              <thead><tr><th>文件</th><th>大小</th><th>修改时间</th><th style="width:150px">操作</th></tr></thead>
              <tbody id="kbBody"></tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- 提示词 -->
      <section id="tab-prompt" class="hide">
        <div class="card">
          <h3>提示词 / 人设</h3>
          <div class="hint" style="margin-bottom:12px">
            这里就是 AI 的"人设 + 约束"。改完点保存即刻生效，不用重启。
            注意保留 <code>{{#context#}}</code> 占位符（知识库内容会替换到这里）。
          </div>
          <textarea id="promptBox" style="min-height:440px"></textarea>
          <div class="row" style="margin-top:14px">
            <button class="btn-primary btn-sm" id="promptSave">保存并生效</button>
            <span class="hint" id="promptInfo"></span>
          </div>
        </div>
      </section>

      <!-- 测试 -->
      <section id="tab-test" class="hide">
        <div class="card">
          <h3>测试问答</h3>
          <div class="hint" style="margin-bottom:12px">直接调用线上服务，验证人设与知识库改动后的真实效果。</div>
          <div class="row">
            <input id="testQ" type="text" placeholder="输入测试问题" style="flex:1;min-width:220px">
            <button class="btn-primary btn-sm" id="testBtn">提问</button>
          </div>
          <div style="margin-top:12px" id="testChips"></div>
          <div class="answer" id="testA" style="margin-top:14px">回答会显示在这里。</div>
        </div>
      </section>

      <!-- 设置 -->
      <section id="tab-settings" class="hide">
        <div class="card">
          <h3>模型设置</h3>
          <div class="grid g2">
            <div class="field"><label>生成模型</label>
              <input id="setModel" type="text" placeholder="deepseek-chat"></div>
            <div class="field"><label>召回条数 TOP_K</label>
              <input id="setTopk" type="number" min="1" max="20"></div>
            <div class="field"><label>温度（0-1，越低越稳）</label>
              <input id="setTemp" type="number" step="0.1" min="0" max="1"></div>
            <div class="field"><label>最大输出长度</label>
              <input id="setMax" type="number" min="200" max="4000"></div>
          </div>
          <div class="field"><label>DeepSeek API Key（留空则不修改）</label>
            <input id="setKey" type="password" placeholder="当前：—" autocomplete="new-password"></div>
          <div class="row">
            <button class="btn-primary btn-sm" id="setSave">保存并重启服务</button>
            <span class="hint">保存后服务会重启，约 8 秒生效。</span>
          </div>
        </div>
      </section>

      <!-- 日志 -->
      <section id="tab-logs" class="hide">
        <div class="card">
          <div class="row" style="justify-content:space-between;margin-bottom:10px">
            <h3 style="margin:0">运行日志（最近 150 行）</h3>
            <button class="btn-ghost btn-sm" id="logRefresh">刷新</button>
          </div>
          <div class="mono" id="logBox">加载中…</div>
        </div>
      </section>
    </div>
  </div>
</div>

<!-- 文件编辑弹窗 -->
<div id="modal" class="modal-bg hide">
  <div class="modal">
    <div class="mhead"><b id="mTitle">编辑文件</b>
      <button class="btn-ghost btn-sm" id="mClose">关闭</button></div>
    <div class="mbody"><textarea id="mText" style="min-height:420px"></textarea></div>
    <div class="mfoot">
      <button class="btn-ghost btn-sm" id="mCancel">取消</button>
      <button class="btn-primary btn-sm" id="mSave">保存并生效</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const API = './api';
let currentFile = null;

function $(id){ return document.getElementById(id); }
function toast(msg, bad){
  const t = $('toast'); t.textContent = msg;
  t.style.background = bad ? '#dc2626' : '#15151d';
  t.classList.add('show');
  clearTimeout(t._h); t._h = setTimeout(()=>t.classList.remove('show'), 2600);
}
async function api(path, opts){
  opts = opts || {};
  const r = await fetch(API + path, opts);
  if(r.status === 401){ showLogin(); throw new Error('未登录'); }
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if(!r.ok){ throw new Error((data && data.error) || ('请求失败 ' + r.status)); }
  return data;
}
function showLogin(){ $('app').classList.add('hide'); $('login').classList.remove('hide'); }
function showApp(){ $('login').classList.add('hide'); $('app').classList.remove('hide'); }

/* 登录 */
$('loginBtn').onclick = async ()=>{
  const pwd = $('pwd').value.trim();
  if(!pwd){ $('loginErr').textContent = '请输入密码'; return; }
  $('loginErr').textContent = '';
  try{
    const r = await fetch('./login', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({password: pwd})});
    if(!r.ok){ $('loginErr').textContent = '密码不正确'; return; }
    showApp(); boot();
  }catch(e){ $('loginErr').textContent = '登录失败：' + e.message; }
};
$('pwd').addEventListener('keydown', e=>{ if(e.key==='Enter') $('loginBtn').click(); });

$('logoutBtn').onclick = async ()=>{
  await fetch('./logout', {method:'POST'});
  showLogin();
};

/* 导航 */
const TITLES = {overview:['概览','问答服务运行状态'], kb:['知识库','上传与管理知识库资料'],
  prompt:['提示词 / 人设','编辑 AI 人设与约束'], test:['测试问答','页内验证回答效果'],
  settings:['模型设置','模型与生成参数'], logs:['运行日志','服务最近日志']};
document.querySelectorAll('.nav-item').forEach(el=>{
  el.onclick = ()=>{
    document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
    el.classList.add('active');
    const tab = el.dataset.tab;
    ['overview','kb','prompt','test','settings','logs'].forEach(t=>{
      $('tab-'+t).classList.toggle('hide', t!==tab);
    });
    $('pageTitle').textContent = TITLES[tab][0];
    $('pageSub').textContent = TITLES[tab][1];
    if(tab==='overview') loadStats();
    if(tab==='kb') loadKB();
    if(tab==='prompt') loadPrompt();
    if(tab==='settings') loadSettings();
    if(tab==='logs') loadLogs();
  };
});

/* 概览 */
async function loadStats(){
  try{
    const s = await api('/stats');
    $('s-docs').textContent = s.docs;
    $('s-chunks').textContent = s.chunks;
    $('s-cases').textContent = s.cases;
    $('s-state').innerHTML = s.service === 'active'
      ? '<span class="badge ok">运行中</span>' : '<span class="badge bad">'+s.service+'</span>';
    $('s-model').textContent = s.model;
    $('s-temp').textContent = s.temperature;
    $('s-max').textContent = s.max_tokens;
    $('s-topk').textContent = s.top_k;
  }catch(e){ toast(e.message, true); }
}
$('reloadBtn').onclick = async ()=>{
  try{ const r = await api('/reload', {method:'POST'}); toast('已重建：'+r.reload.chunks+' 个切片'); loadStats(); }
  catch(e){ toast(e.message, true); }
};
$('quickBtn').onclick = ()=> quickAsk();
$('quickQ').addEventListener('keydown', e=>{ if(e.key==='Enter') quickAsk(); });
async function quickAsk(){
  const q = $('quickQ').value.trim(); if(!q) return;
  $('quickA').textContent = '生成中…';
  try{ const r = await api('/test', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({query:q})}); $('quickA').textContent = r.answer || '(空回答)'; }
  catch(e){ $('quickA').textContent = '出错：' + e.message; }
}

/* 知识库 */
async function loadKB(){
  try{
    const d = await api('/kb');
    $('kbCount').textContent = '共 ' + d.items.length + ' 个';
    $('kbBody').innerHTML = d.items.map(it=>`
      <tr>
        <td class="name">${esc(it.name)}</td>
        <td>${(it.size/1024).toFixed(1)} KB</td>
        <td>${it.mtime}</td>
        <td>
          <button class="btn-ghost btn-sm" onclick="openFile('${esc(it.name)}')">编辑</button>
          <button class="btn-danger btn-sm" onclick="delFile('${esc(it.name)}')">删除</button>
        </td>
      </tr>`).join('') || '<tr><td colspan="4" class="hint">暂无文件</td></tr>';
  }catch(e){ toast(e.message, true); }
}
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
$('kbRefresh').onclick = loadKB;

async function openFile(name){
  try{
    const d = await api('/kb/file?name=' + encodeURIComponent(name));
    currentFile = name;
    $('mTitle').textContent = name;
    $('mText').value = d.content;
    $('modal').classList.remove('hide');
  }catch(e){ toast(e.message, true); }
}
$('mClose').onclick = $('mCancel').onclick = ()=> $('modal').classList.add('hide');
$('mSave').onclick = async ()=>{
  try{
    await api('/kb/file', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: currentFile, content: $('mText').value})});
    $('modal').classList.add('hide'); toast('已保存并重建索引'); loadKB(); loadStats();
  }catch(e){ toast(e.message, true); }
};
async function delFile(name){
  if(!confirm('确定删除 ' + name + ' ？')) return;
  try{ await api('/kb/delete', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name})}); toast('已删除'); loadKB(); loadStats(); }
  catch(e){ toast(e.message, true); }
}

/* 上传 */
$('drop').onclick = ()=> $('fileInput').click();
$('drop').addEventListener('dragover', e=>{ e.preventDefault(); $('drop').classList.add('over'); });
$('drop').addEventListener('dragleave', ()=> $('drop').classList.remove('over'));
$('drop').addEventListener('drop', e=>{ e.preventDefault(); $('drop').classList.remove('over');
  if(e.dataTransfer.files[0]) doUpload(e.dataTransfer.files[0]); });
$('fileInput').onchange = e=>{ if(e.target.files[0]) doUpload(e.target.files[0]); };
async function doUpload(file){
  const fd = new FormData();
  fd.append('file', file);
  fd.append('title', $('upTitle').value.trim());
  fd.append('platform', $('upPlatform').value.trim() || '用户上传');
  $('drop').textContent = '上传中…';
  try{
    const r = await fetch(API + '/kb/upload', {method:'POST', body: fd});
    const d = await r.json();
    if(!r.ok) throw new Error(d.error || '上传失败');
    toast('上传成功：' + d.name);
    loadKB(); loadStats();
  }catch(e){ toast(e.message, true); }
  finally{
    $('drop').innerHTML = '点击选择文件，或把文件拖到这里<br><span class="hint">支持 md / txt / pdf / docx，自动转成知识库文本</span>';
    $('fileInput').value = '';
  }
}

/* 提示词 */
async function loadPrompt(){
  try{ const d = await api('/prompt'); $('promptBox').value = d.content; }catch(e){ toast(e.message, true); }
}
$('promptSave').onclick = async ()=>{
  try{
    const r = await api('/prompt', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({content: $('promptBox').value})});
    toast('已保存并生效（'+r.reload.chunks+' 切片）');
  }catch(e){ toast(e.message, true); }
};

/* 测试 */
const CHIPS = ['石董会是什么','999元会员具体能拿到什么','怎么把一个技能做成能卖的产品'];
$('testChips').innerHTML = CHIPS.map(q=>`<span class="qchip" onclick="fillTest('${esc(q)}')">${esc(q)}</span>`).join('');
function fillTest(q){ $('testQ').value = q; testAsk(); }
$('testBtn').onclick = testAsk;
$('testQ').addEventListener('keydown', e=>{ if(e.key==='Enter') testAsk(); });
async function testAsk(){
  const q = $('testQ').value.trim(); if(!q) return;
  $('testA').textContent = '生成中…';
  try{ const r = await api('/test', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({query:q})}); $('testA').textContent = r.answer || '(空回答)'; }
  catch(e){ $('testA').textContent = '出错：' + e.message; }
}

/* 设置 */
async function loadSettings(){
  try{
    const s = await api('/settings');
    $('setModel').value = s.model; $('setTopk').value = s.top_k;
    $('setTemp').value = s.temperature; $('setMax').value = s.max_tokens;
    $('setKey').placeholder = '当前：' + s.api_key_masked;
  }catch(e){ toast(e.message, true); }
}
$('setSave').onclick = async ()=>{
  const body = {model:$('setModel').value.trim(), top_k:$('setTopk').value,
    temperature:$('setTemp').value, max_tokens:$('setMax').value};
  if($('setKey').value.trim()) body.deepseek_api_key = $('setKey').value.trim();
  try{ await api('/settings', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)}); $('setKey').value=''; toast('已保存，服务重启中（约8秒）'); }
  catch(e){ toast(e.message, true); }
};

/* 日志 */
async function loadLogs(){
  $('logBox').textContent = '加载中…';
  try{ const d = await api('/logs'); $('logBox').textContent = d.text; }catch(e){ $('logBox').textContent = e.message; }
}
$('logRefresh').onclick = loadLogs;

/* 启动 */
async function boot(){
  try{ await api('/stats'); showApp(); loadStats(); }
  catch(e){ showLogin(); }
}
boot();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("ADMIN_PORT", "8090")))
