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
import time
import secrets
import hashlib
import subprocess
import urllib.request
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

AUTH_FILE = Path(os.environ.get("AUTH_FILE", str(BASE_DIR / "admin_auth.json")))
SMS_LOG = Path(os.environ.get("SMS_LOG", str(BASE_DIR / "sms.log")))

RAG_URL = os.environ.get("RAG_URL", "http://127.0.0.1:8080")
API_KEY = os.environ.get("API_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "sdh-admin-secret-change-me")
RAG_SERVICE = os.environ.get("RAG_SERVICE", "siyumenghai-rag-lite")
COOKIE = "sdh_admin"

CODE_TTL = 300          # 验证码有效期（秒）
CODE_RESEND = 60        # 同一号码重发间隔（秒）
CODE_HOURLY_MAX = 10    # 同一号码每小时最多发送次数
LOGIN_FAIL_MAX = 5      # 密码连续错误次数上限
LOGIN_LOCK = 300        # 触发上限后的锁定时长（秒）

# ---------------- 知识库分类（按内容性质划分） ----------------
GROUP_LABELS = {
    "share": "石更新本人分享",
    "qa": "石更新本人答疑",
    "course": "石更新课程内容",
    "peers": "同行案例",
}
DIR_GROUP = {
    "share": "share",
    "own": "share",
    "self": "share",
    "sdh": "share",
    "qa": "qa",
    "ask": "qa",
    "answer": "qa",
    "course": "course",
    "courses": "course",
    "kc": "course",
    "peers": "peers",
    "peer": "peers",
    "cases": "peers",
}
QA_HINTS = ("问答", "答疑", "问与答", "Q&A", "Q＆A")


def _group_of(p: Path) -> str:
    """按所在目录推断内容归属；根目录现存资料视为同行案例。"""
    try:
        rel = p.relative_to(CASES_DIR)
    except Exception:
        return "peers"
    parts = rel.parts
    if len(parts) >= 2:
        d = parts[0].lower()
        g = DIR_GROUP.get(d, "peers")
        if d in ("sdh", "own", "self", "share"):
            stem = p.stem
            if "__" in stem:
                cat = re.split(r"[_\s]", stem.split("__", 1)[1], 1)[0]
                if any(h in cat for h in QA_HINTS):
                    return "qa"
        return g
    return "peers"


app = FastAPI(title="石董会 AI 管理后台")


# ---------------- 认证 ----------------
# 凭证存放在 admin_auth.json（0600），密码只存 PBKDF2 哈希，不存明文。
# 未生成文件时回退到 env 里的 ADMIN_PASSWORD，保证旧部署平滑升级。

def _load_auth() -> dict:
    try:
        if AUTH_FILE.exists():
            return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_auth(data: dict) -> None:
    AUTH_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        os.chmod(AUTH_FILE, 0o600)
    except Exception:
        pass


def _hash_pwd(pwd: str) -> str:
    iters = 120000
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, iters)
    return f"pbkdf2_sha256${iters}${salt.hex()}${dk.hex()}"


def _verify_hash(pwd: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", pwd.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def verify_password(pwd: str) -> bool:
    a = _load_auth()
    if a.get("password_hash"):
        return _verify_hash(pwd, a["password_hash"])
    if ADMIN_PASSWORD:
        return hmac.compare_digest(pwd or "", ADMIN_PASSWORD)
    return False


def _cred() -> str:
    """凭证指纹：改密码/绑定手机后自动变化，旧会话立即失效。"""
    a = _load_auth()
    if a.get("password_hash"):
        return "h:" + a["password_hash"]
    if ADMIN_PASSWORD:
        return "e:" + hashlib.sha256(ADMIN_PASSWORD.encode("utf-8")).hexdigest()
    return ""


def _token() -> str:
    raw = (_cred() or "empty").encode("utf-8")
    return hmac.new(SESSION_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def authed(req: Request) -> bool:
    if not _cred():
        return False
    return hmac.compare_digest(req.cookies.get(COOKIE, ""), _token())


def _set_session(resp: JSONResponse, req: Request) -> None:
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


def deny():
    return JSONResponse(status_code=401, content={"error": "unauthorized"})


# ---- 登录失败节流（同一 IP 5 次错锁 5 分钟）----
_LOGIN_FAIL: dict = {}


def _client_ip(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else ""))


def _login_locked(ip: str) -> int:
    rec = _LOGIN_FAIL.get(ip)
    if not rec:
        return 0
    left = int(rec.get("until", 0) - time.time())
    return left if left > 0 else 0


def _login_fail(ip: str) -> None:
    rec = _LOGIN_FAIL.setdefault(ip, {"n": 0, "until": 0})
    rec["n"] += 1
    if rec["n"] >= LOGIN_FAIL_MAX:
        rec["until"] = time.time() + LOGIN_LOCK
        rec["n"] = 0


def _login_ok(ip: str) -> None:
    _LOGIN_FAIL.pop(ip, None)


# ---- 手机号 ----
def _norm_phone(raw: str) -> str:
    s = re.sub(r"[^\d]", "", raw or "")
    if s.startswith("0086"):
        s = s[4:]
    if s.startswith("86") and len(s) == 13:
        s = s[2:]
    return s


def _valid_phone(p: str) -> bool:
    return bool(re.fullmatch(r"1[3-9]\d{9}", p or ""))


def _mask_phone(p: str) -> str:
    return p[:3] + "****" + p[-4:] if len(p) == 11 else ""


# ---- 验证码 ----
_CODES: dict = {}


def _send_code_rate(phone: str) -> tuple:
    now = time.time()
    rec = _CODES.get(phone)
    if rec:
        gap = now - rec.get("sent_at", 0)
        if gap < CODE_RESEND:
            return False, f"请 {int(CODE_RESEND - gap)} 秒后再获取"
        if now - rec.get("hour_start", 0) > 3600:
            rec["hour_start"], rec["hour_count"] = now, 0
        if rec.get("hour_count", 0) >= CODE_HOURLY_MAX:
            return False, "该号码获取次数过多，请 1 小时后再试"
    return True, ""


def _issue_code(phone: str) -> str:
    code = f"{secrets.randbelow(1000000):06d}"
    now = time.time()
    rec = _CODES.setdefault(phone, {"hour_start": now, "hour_count": 0})
    if now - rec.get("hour_start", 0) > 3600:
        rec["hour_start"], rec["hour_count"] = now, 0
    rec.update(
        {
            "hash": hashlib.sha256(code.encode()).hexdigest(),
            "exp": now + CODE_TTL,
            "tries": 0,
            "sent_at": now,
            "hour_count": rec.get("hour_count", 0) + 1,
        }
    )
    return code


def _check_code(phone: str, code: str) -> tuple:
    rec = _CODES.get(phone)
    if not rec:
        return False, "请先获取验证码"
    if time.time() > rec.get("exp", 0):
        _CODES.pop(phone, None)
        return False, "验证码已过期，请重新获取"
    if rec.get("tries", 0) >= 5:
        _CODES.pop(phone, None)
        return False, "验证码错误次数过多，请重新获取"
    rec["tries"] = rec.get("tries", 0) + 1
    if not hmac.compare_digest(
        hashlib.sha256((code or "").strip().encode()).hexdigest(), rec.get("hash", "")
    ):
        return False, "验证码不正确"
    _CODES.pop(phone, None)
    return True, ""


# ---------------- 验证码发送通道 ----------------
# SMS_PROVIDER: log（写服务器日志，零成本自用）/ webhook（企业微信·飞书·Server酱机器人）
#               / tencent（腾讯云短信，需填 SecretId/Key/SdkAppId/签名/模板ID）
SMS_KEYS = [
    "SMS_PROVIDER",
    "SMS_WEBHOOK_URL",
    "SMS_SECRET_ID",
    "SMS_SECRET_KEY",
    "SMS_SDK_APP_ID",
    "SMS_SIGN_NAME",
    "SMS_TEMPLATE_ID",
]


def _sms_conf() -> dict:
    env = _read_env()
    conf = {}
    for k in SMS_KEYS:
        conf[k] = (env.get(k) or os.environ.get(k) or "").strip()
    conf["SMS_PROVIDER"] = (conf["SMS_PROVIDER"] or "log").lower()
    conf["SMS_SIGN_NAME"] = conf["SMS_SIGN_NAME"] or "石董会"
    return conf


def _send_via_log(phone: str, code: str) -> tuple:
    line = (
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\t{_mask_phone(phone)}\t{code}\n"
    )
    try:
        with SMS_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
        try:
            os.chmod(SMS_LOG, 0o600)
        except Exception:
            pass
        return True, "log"
    except Exception as e:
        return False, f"写日志失败：{e}"


def _send_via_webhook(url: str, phone: str, code: str, sign: str) -> tuple:
    text = f"【{sign}】后台登录验证码 {code}，{CODE_TTL // 60} 分钟内有效。如非本人操作请忽略。"
    if "sctapi.ftqq.com" in url:  # Server酱
        payload = {"title": f"{sign} 管理后台验证码", "desp": text}
    else:  # 企业微信 / 飞书 / 钉钉 群机器人通用文本格式
        payload = {"msgtype": "text", "text": {"content": text}}
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", "ignore")
        if '"errcode"' in body and '"errcode":0' not in body.replace(" ", ""):
            return False, f"机器人返回：{body[:160]}"
        return True, "webhook"
    except Exception as e:
        return False, f"推送失败：{e}"


def _send_via_tencent(conf: dict, phone: str, code: str) -> tuple:
    sid = conf.get("SMS_SECRET_ID", "")
    skey = conf.get("SMS_SECRET_KEY", "")
    appid = conf.get("SMS_SDK_APP_ID", "")
    sign = conf.get("SMS_SIGN_NAME", "")
    tid = conf.get("SMS_TEMPLATE_ID", "")
    missing = [
        n
        for n, v in (
            ("SecretId", sid),
            ("SecretKey", skey),
            ("SdkAppId", appid),
            ("短信签名", sign),
            ("模板ID", tid),
        )
        if not v
    ]
    if missing:
        return False, "腾讯云短信参数不全：" + "、".join(missing)

    host, service = "sms.tencentcloudapi.com", "sms"
    action, version = "SendSms", "2021-01-11"
    payload = json.dumps(
        {
            "PhoneNumberSet": ["+86" + phone],
            "SmsSdkAppId": appid,
            "SignName": sign,
            "TemplateId": tid,
            "TemplateParamSet": [code, str(CODE_TTL // 60)],
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    ts = int(time.time())
    date = time.strftime("%Y-%m-%d", time.gmtime(ts))
    ctype = "application/json; charset=utf-8"
    signed_headers = "content-type;host;x-tc-action"
    canonical_headers = (
        f"content-type:{ctype}\nhost:{host}\nx-tc-action:{action.lower()}\n"
    )
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = (
        f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_payload}"
    )
    scope = f"{date}/{service}/tc3_request"
    string_to_sign = (
        f"TC3-HMAC-SHA256\n{ts}\n{scope}\n"
        + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    )

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _hmac(("TC3" + skey).encode("utf-8"), date)
    k_service = _hmac(k_date, service)
    k_signing = _hmac(k_service, "tc3_request")
    signature = hmac.new(
        k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    authorization = (
        f"TC3-HMAC-SHA256 Credential={sid}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    try:
        req = urllib.request.Request(
            f"https://{host}",
            data=payload.encode("utf-8"),
            method="POST",
            headers={
                "Authorization": authorization,
                "Content-Type": ctype,
                "Host": host,
                "X-TC-Action": action,
                "X-TC-Timestamp": str(ts),
                "X-TC-Version": version,
                "X-TC-Region": "",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return False, f"请求腾讯云失败：{e}"
    resp = data.get("Response", {})
    if resp.get("Error"):
        err = resp["Error"]
        return False, f"{err.get('Code')}: {err.get('Message')}"
    st = (resp.get("SendStatusSet") or [{}])[0]
    if st.get("Code") == "Ok":
        return True, "tencent"
    return False, f"{st.get('Code')}: {st.get('Message')}"


def _dispatch_code(phone: str, code: str) -> tuple:
    conf = _sms_conf()
    provider = conf["SMS_PROVIDER"]
    if provider == "webhook":
        url = conf.get("SMS_WEBHOOK_URL", "")
        if not url:
            return False, "未配置机器人 Webhook 地址"
        return _send_via_webhook(url, phone, code, conf["SMS_SIGN_NAME"])
    if provider == "tencent":
        return _send_via_tencent(conf, phone, code)
    return _send_via_log(phone, code)


# ---------------- 工具函数 ----------------
def _safe_path(name: str) -> Path | None:
    """只允许访问 CASES_DIR 下的 .md 文件（现支持 share/qa/course/peers 子目录），防目录穿越。"""
    if not name or "\x00" in name or not name.lower().endswith(".md"):
        return None
    rel = name.replace("\\", "/").lstrip("/")
    p = (CASES_DIR / rel).resolve()
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
    ip = _client_ip(req)
    left = _login_locked(ip)
    if left:
        return JSONResponse(
            status_code=429, content={"error": f"密码错误次数过多，请 {left // 60 + 1} 分钟后再试"}
        )
    try:
        body = await req.json()
    except Exception:
        body = {}
    pwd = (body.get("password") or "").strip()
    if not verify_password(pwd):
        _login_fail(ip)
        return JSONResponse(status_code=401, content={"error": "密码不正确"})
    _login_ok(ip)
    resp = JSONResponse({"ok": True})
    _set_session(resp, req)
    return resp


# ---------------- 手机验证码登录 ----------------
@app.get("/api/auth/state")
async def auth_state(req: Request):
    """登录页用：是否已绑定手机号、当前验证码通道（不含任何敏感信息）。"""
    a = _load_auth()
    return {
        "phone_bound": bool(a.get("phone")),
        "phone_masked": _mask_phone(a.get("phone", "")),
        "provider": _sms_conf()["SMS_PROVIDER"],
        "logged_in": authed(req),
    }


@app.post("/api/auth/send-code")
async def auth_send_code(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    phone = _norm_phone(body.get("phone", ""))
    if not _valid_phone(phone):
        return JSONResponse(status_code=400, content={"error": "手机号格式不正确"})

    a = _load_auth()
    bound = a.get("phone", "")
    is_login = authed(req)
    # 未登录：只能给已绑定号码发码；已登录：可用于更换绑定号码
    if not is_login:
        if not bound:
            return JSONResponse(
                status_code=403,
                content={"error": "尚未绑定手机号，请先用密码登录后在「安全设置」里绑定"},
            )
        if phone != bound:
            return JSONResponse(status_code=403, content={"error": "手机号不匹配"})
    else:
        if body.get("purpose") != "bind" and bound and phone != bound:
            return JSONResponse(status_code=403, content={"error": "手机号与绑定号码不一致"})
        if bound and bound == phone and body.get("purpose") == "bind":
            return JSONResponse(status_code=400, content={"error": "该号码已绑定"})

    ok, msg = _send_code_rate(phone)
    if not ok:
        return JSONResponse(status_code=429, content={"error": msg})
    code = _issue_code(phone)
    sent, info = _dispatch_code(phone, code)
    if not sent:
        _CODES.pop(phone, None)
        return JSONResponse(status_code=502, content={"error": info})
    out = {"ok": True, "provider": info, "ttl": CODE_TTL, "resend": CODE_RESEND}
    if info == "log":
        out["hint"] = "当前为「日志通道」，验证码已写入服务器日志（后台「安全设置」可查看最近一条）"
    return out


@app.post("/api/auth/verify-code")
async def auth_verify_code(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    phone = _norm_phone(body.get("phone", ""))
    code = (body.get("code") or "").strip()
    if not _valid_phone(phone) or not code:
        return JSONResponse(status_code=400, content={"error": "请填写手机号和验证码"})
    ok, msg = _check_code(phone, code)
    if not ok:
        return JSONResponse(status_code=401, content={"error": msg})

    a = _load_auth()
    resp = JSONResponse({"ok": True})
    if authed(req) and body.get("purpose") == "bind":
        a["phone"] = phone
        a["phone_bound_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_auth(a)
        resp = JSONResponse({"ok": True, "bound": True, "phone": _mask_phone(phone)})
        _set_session(resp, req)
        return resp
    if not a.get("phone"):
        return JSONResponse(
            status_code=403, content={"error": "该号码尚未绑定，请先用密码登录后绑定"}
        )
    if a.get("phone") != phone:
        return JSONResponse(status_code=403, content={"error": "手机号不匹配"})
    _set_session(resp, req)
    return resp


# ---------------- 修改密码 / 安全设置 ----------------
@app.post("/api/change-password")
async def change_password(req: Request):
    if not authed(req):
        return deny()
    try:
        body = await req.json()
    except Exception:
        body = {}
    old = (body.get("old") or "").strip()
    new = (body.get("new") or "").strip()
    if not verify_password(old):
        return JSONResponse(status_code=400, content={"error": "当前密码不正确"})
    if len(new) < 8:
        return JSONResponse(status_code=400, content={"error": "新密码至少 8 位"})
    if len(new) > 64:
        return JSONResponse(status_code=400, content={"error": "新密码过长（最多 64 位）"})
    if new == old:
        return JSONResponse(status_code=400, content={"error": "新密码不能与当前密码相同"})
    if new.isdigit():
        return JSONResponse(status_code=400, content={"error": "密码不要用纯数字，加字母更安全"})

    a = _load_auth()
    a["password_hash"] = _hash_pwd(new)
    a["password_changed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_auth(a)
    # 同步 env 里的明文（便于对外备份/别的脚本读取），并让会话自动续到新凭证
    try:
        _upsert_env({"ADMIN_PASSWORD": new})
    except Exception:
        pass
    resp = JSONResponse({"ok": True})
    _set_session(resp, req)
    return resp


@app.get("/api/sms-settings")
async def sms_settings(req: Request):
    if not authed(req):
        return deny()
    conf = _sms_conf()
    a = _load_auth()
    last = ""
    try:
        if SMS_LOG.exists():
            lines = [x for x in SMS_LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
            if lines:
                last = lines[-1]
    except Exception:
        pass
    return {
        "provider": conf["SMS_PROVIDER"],
        "webhook_url": conf.get("SMS_WEBHOOK_URL", ""),
        "has_secret": bool(conf.get("SMS_SECRET_ID")),
        "secret_id_masked": (conf.get("SMS_SECRET_ID", "")[:6] + "****")
        if conf.get("SMS_SECRET_ID")
        else "",
        "sdk_app_id": conf.get("SMS_SDK_APP_ID", ""),
        "sign_name": conf.get("SMS_SIGN_NAME", ""),
        "template_id": conf.get("SMS_TEMPLATE_ID", ""),
        "phone_masked": _mask_phone(a.get("phone", "")),
        "phone_bound": bool(a.get("phone")),
        "last_code_line": last,
        "password_changed_at": a.get("password_changed_at", ""),
    }


@app.post("/api/sms-settings")
async def sms_settings_save(req: Request):
    if not authed(req):
        return deny()
    try:
        body = await req.json()
    except Exception:
        body = {}
    provider = (body.get("provider") or "log").lower()
    if provider not in ("log", "webhook", "tencent"):
        return JSONResponse(status_code=400, content={"error": "未知的通道类型"})
    updates = {"SMS_PROVIDER": provider}
    for k in ("SMS_WEBHOOK_URL", "SMS_SDK_APP_ID", "SMS_SIGN_NAME", "SMS_TEMPLATE_ID"):
        v = (body.get(k.lower()) or "").strip()
        if v:
            updates[k] = v
    # 密钥单独处理：留空表示不修改
    for k in ("SMS_SECRET_ID", "SMS_SECRET_KEY"):
        v = (body.get(k.lower()) or "").strip()
        if v:
            updates[k] = v
    _upsert_env(updates)
    return {"ok": True, "provider": provider}


@app.post("/api/sms/test")
async def sms_test(req: Request):
    if not authed(req):
        return deny()
    try:
        body = await req.json()
    except Exception:
        body = {}
    a = _load_auth()
    phone = _norm_phone(body.get("phone") or a.get("phone", ""))
    if not _valid_phone(phone):
        return JSONResponse(status_code=400, content={"error": "请先绑定或填写手机号"})
    ok, msg = _send_code_rate(phone)
    if not ok:
        return JSONResponse(status_code=429, content={"error": msg})
    code = _issue_code(phone)
    sent, info = _dispatch_code(phone, code)
    if not sent:
        _CODES.pop(phone, None)
        return JSONResponse(status_code=502, content={"error": info})
    out = {"ok": True, "provider": info, "phone": _mask_phone(phone)}
    if info == "log":
        out["debug_code"] = code
    return out


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
    by_group = {}
    for p in docs:
        g = _group_of(p)
        by_group[g] = by_group.get(g, 0) + 1
    h = _rag_health()
    env = _read_env()
    return {
        "docs": len(docs),
        "chunks": h.get("chunks", 0),
        "cases": h.get("cases", 0),
        "groups": by_group,
        "group_labels": GROUP_LABELS,
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
            g = _group_of(p)
            items.append(
                {
                    "name": str(p.relative_to(CASES_DIR)),
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                    "group": g,
                    "group_label": GROUP_LABELS.get(g, g),
                }
            )
    return {"items": items, "group_labels": GROUP_LABELS}


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
    platform: str = Form(""),
    group: str = Form("share"),
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

    g = group if group in GROUP_LABELS else "share"
    cid = "u" + datetime.now().strftime("%y%m%d%H%M%S")
    name = re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", title or Path(file.filename or "doc").stem)[:40]
    target_dir = CASES_DIR / g
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / f"{cid}__{name}.md"
    dest.write_text(text, encoding="utf-8")
    _append_meta(cid, platform, title)
    result = _reload_rag()
    return {
        "ok": True,
        "name": str(dest.relative_to(CASES_DIR)),
        "group": g,
        "group_label": GROUP_LABELS[g],
        "reload": result,
    }


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
  .ltabs{display:flex;gap:4px;background:#f2f3f8;border-radius:10px;padding:4px;margin-bottom:20px}
  .ltab{flex:1;text-align:center;padding:8px;border-radius:8px;font-size:13px;
    color:var(--muted);cursor:pointer;transition:.15s}
  .ltab.active{background:#fff;color:var(--ink);font-weight:600;
    box-shadow:0 2px 8px rgba(20,20,40,.07)}
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

    <div class="ltabs">
      <div class="ltab active" data-lt="pwd">密码登录</div>
      <div class="ltab" data-lt="sms">手机验证码</div>
    </div>

    <div id="lt-pwd">
      <div class="field">
        <label>管理密码</label>
        <input id="pwd" type="password" placeholder="请输入密码" autocomplete="current-password">
      </div>
      <button class="btn-primary" style="width:100%" id="loginBtn">进入后台</button>
    </div>

    <div id="lt-sms" class="hide">
      <div class="field">
        <label>绑定手机号</label>
        <input id="lPhone" type="text" inputmode="numeric" maxlength="11"
               placeholder="11 位手机号" autocomplete="tel">
      </div>
      <div class="field">
        <label>验证码</label>
        <div class="row" style="flex-wrap:nowrap">
          <input id="lCode" type="text" inputmode="numeric" maxlength="6" placeholder="6 位验证码">
          <button class="btn-ghost" id="lSend" style="white-space:nowrap;flex-shrink:0">获取验证码</button>
        </div>
      </div>
      <button class="btn-primary" style="width:100%" id="smsLoginBtn">登录</button>
      <div class="hint" id="smsHint" style="margin-top:12px"></div>
    </div>

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
    <div class="nav-item" data-tab="security">安全设置</div>
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
            <select id="upGroup" style="flex:1;min-width:180px">
              <option value="share">石更新本人分享</option>
              <option value="qa">石更新本人答疑</option>
              <option value="course">石更新课程内容</option>
              <option value="peers">同行案例（别人的，仅作佐证）</option>
            </select>
          </div>
          <div class="row" style="margin-bottom:12px">
            <input id="upPlatform" type="text" placeholder="来源/主题（可选，如：小红书引流）" style="flex:1">
          </div>
          <div class="drop" id="drop">点击选择文件，或把文件拖到这里<br>
            <span class="hint">支持 md / txt / pdf / docx，自动转成知识库文本</span></div>
          <input type="file" id="fileInput" class="hide" accept=".md,.txt,.pdf,.docx">
        </div>
        <div class="card">
          <div class="row" style="justify-content:space-between;margin-bottom:10px">
            <h3 style="margin:0">知识库文件 <span class="hint" id="kbCount"></span></h3>
            <div class="row" style="gap:8px">
              <select id="kbFilter" style="min-width:160px">
                <option value="">全部分类</option>
                <option value="share">石更新本人分享</option>
                <option value="qa">石更新本人答疑</option>
                <option value="course">石更新课程内容</option>
                <option value="peers">同行案例</option>
              </select>
              <button class="btn-ghost btn-sm" id="kbRefresh">刷新</button>
            </div>
          </div>
          <div style="overflow:auto">
            <table>
              <thead><tr><th>文件</th><th>分类</th><th>大小</th><th>修改时间</th><th style="width:150px">操作</th></tr></thead>
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

      <!-- 安全设置 -->
      <section id="tab-security" class="hide">
        <div class="card">
          <h3>修改密码</h3>
          <div class="hint" style="margin-bottom:14px">
            密码只保存加密哈希，不存明文。改完旧会话自动失效，其他设备需重新登录。
          </div>
          <div class="grid g2">
            <div class="field"><label>当前密码</label>
              <input id="cpOld" type="password" autocomplete="current-password" placeholder="输入现在的密码"></div>
            <div class="field"><label>新密码（至少 8 位，建议字母+数字）</label>
              <input id="cpNew" type="password" autocomplete="new-password" placeholder="新密码"></div>
          </div>
          <div class="field"><label>再输一次新密码</label>
            <input id="cpNew2" type="password" autocomplete="new-password" placeholder="确认新密码"></div>
          <div class="row">
            <button class="btn-primary btn-sm" id="cpSave">保存新密码</button>
            <span class="hint" id="cpInfo"></span>
          </div>
        </div>

        <div class="card">
          <h3>手机验证码登录</h3>
          <div class="hint" style="margin-bottom:14px">
            绑定后可用「手机号 + 验证码」登录，忘密码也能进。手机号仅存于服务器本机（admin_auth.json）。
          </div>
          <div class="row" style="margin-bottom:14px">
            <span class="hint">当前绑定：<b id="bindPhone">未绑定</b></span>
          </div>
          <div class="grid g2">
            <div class="field"><label>手机号</label>
              <input id="bindInput" type="text" inputmode="numeric" maxlength="11" placeholder="11 位手机号"></div>
            <div class="field"><label>验证码</label>
              <div class="row" style="flex-wrap:nowrap">
                <input id="bindCode" type="text" inputmode="numeric" maxlength="6" placeholder="6 位验证码">
                <button class="btn-ghost btn-sm" id="bindSend" style="white-space:nowrap;flex-shrink:0">获取验证码</button>
              </div>
            </div>
          </div>
          <div class="row">
            <button class="btn-primary btn-sm" id="bindSave">绑定 / 更换号码</button>
            <span class="hint" id="bindInfo"></span>
          </div>
        </div>

        <div class="card">
          <h3>验证码发送通道</h3>
          <div class="hint" style="margin-bottom:14px">
            三选一：<b>日志通道</b>免费自用（验证码写进服务器日志）；<b>机器人</b>推到企业微信/飞书群（免费）；
            <b>腾讯云短信</b>发真短信（需开通短信服务，约 0.04 元/条）。
          </div>
          <div class="field"><label>通道</label>
            <select id="smsProvider">
              <option value="log">日志通道（免费，验证码写服务器日志）</option>
              <option value="webhook">群机器人（企业微信 / 飞书 / Server酱）</option>
              <option value="tencent">腾讯云短信（真短信）</option>
            </select>
          </div>

          <div id="pane-webhook" class="hide">
            <div class="field"><label>机器人 Webhook 地址</label>
              <input id="smsWebhook" type="text" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."></div>
          </div>

          <div id="pane-tencent" class="hide">
            <div class="grid g2">
              <div class="field"><label>SecretId</label>
                <input id="smsSid" type="text" placeholder="AKID..."></div>
              <div class="field"><label>SecretKey（留空不修改）</label>
                <input id="smsSkey" type="password" placeholder="当前：—" autocomplete="new-password"></div>
              <div class="field"><label>SdkAppId</label>
                <input id="smsApp" type="text" placeholder="1400xxxxxx"></div>
              <div class="field"><label>短信签名</label>
                <input id="smsSign" type="text" placeholder="石董会"></div>
            </div>
            <div class="field"><label>模板 ID</label>
              <input id="smsTpl" type="text" placeholder="1234567"></div>
            <div class="hint" style="margin-bottom:12px">
              模板内容建议：<code>您的验证码是 {1}，{2} 分钟内有效，请勿泄露。</code>（两个变量分别对应验证码与有效分钟数）
            </div>
          </div>

          <div class="row">
            <button class="btn-primary btn-sm" id="smsSave">保存通道设置</button>
            <button class="btn-ghost btn-sm" id="smsTest">发一条测试</button>
            <span class="hint" id="smsInfo"></span>
          </div>
          <div class="hint" id="smsLast" style="margin-top:14px"></div>
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
function loginTab(which){
  document.querySelectorAll('.ltab').forEach(t=>t.classList.toggle('active', t.dataset.lt===which));
  $('lt-pwd').classList.toggle('hide', which!=='pwd');
  $('lt-sms').classList.toggle('hide', which!=='sms');
  $('loginErr').textContent = '';
  if(which==='sms') loadAuthState();
}
document.querySelectorAll('.ltab').forEach(t=>{ t.onclick = ()=> loginTab(t.dataset.lt); });

async function loadAuthState(){
  try{
    const st = await (await fetch('./api/auth/state')).json();
    if(st.phone_bound){
      $('lPhone').placeholder = '已绑定 ' + st.phone_masked;
      $('smsHint').textContent = '已绑定 ' + st.phone_masked + '，输入该号码后点「获取验证码」';
    }else{
      $('smsHint').textContent = '尚未绑定手机号：请先用密码登录，在「安全设置」里绑定。';
    }
  }catch(e){}
}

$('loginBtn').onclick = async ()=>{
  const pwd = $('pwd').value.trim();
  if(!pwd){ $('loginErr').textContent = '请输入密码'; return; }
  $('loginErr').textContent = '';
  try{
    const r = await fetch('./login', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({password: pwd})});
    if(!r.ok){
      const d = await r.json().catch(()=>({}));
      $('loginErr').textContent = d.error || '密码不正确'; return;
    }
    $('pwd').value = '';
    showApp(); loadStats();
  }catch(e){ $('loginErr').textContent = '登录失败：' + e.message; }
};
$('pwd').addEventListener('keydown', e=>{ if(e.key==='Enter') $('loginBtn').click(); });

/* 手机验证码登录 */
let smsTimer = null;
function startCountdown(btn, sec){
  let n = sec; btn.disabled = true;
  const raw = btn.dataset.raw || btn.textContent;
  btn.dataset.raw = raw;
  clearInterval(smsTimer);
  btn.textContent = n + 's';
  smsTimer = setInterval(()=>{
    n--;
    if(n<=0){ clearInterval(smsTimer); btn.disabled=false; btn.textContent = btn.dataset.raw; }
    else btn.textContent = n + 's';
  }, 1000);
}
async function requestCode(phone, btn, infoEl, purpose){
  if(!/^1[3-9]\d{9}$/.test(phone)){ infoEl.textContent = '请输入正确的 11 位手机号'; return false; }
  infoEl.textContent = '发送中…';
  try{
    const r = await fetch('./api/auth/send-code', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({phone, purpose: purpose||'login'})});
    const d = await r.json().catch(()=>({}));
    if(!r.ok){ infoEl.textContent = d.error || '发送失败'; return false; }
    infoEl.textContent = '已发送' + (d.provider==='log' ? '（通道：服务器日志，可在「安全设置」查看）' : '（通道：' + d.provider + '）');
    startCountdown(btn, d.resend || 60);
    return true;
  }catch(e){ infoEl.textContent = '发送失败：' + e.message; return false; }
}
$('lSend').onclick = ()=>{
  const ph = $('lPhone').value.trim();
  if(!ph){ $('smsHint').textContent = '请先输入绑定的手机号'; return; }
  requestCode(ph, $('lSend'), $('smsHint'), 'login');
};
$('smsLoginBtn').onclick = async ()=>{
  const phone = $('lPhone').value.trim(), code = $('lCode').value.trim();
  if(!phone || !code){ $('smsHint').textContent = '请填写手机号和验证码'; return; }
  $('smsHint').textContent = '验证中…';
  try{
    const r = await fetch('./api/auth/verify-code', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({phone, code})});
    const d = await r.json().catch(()=>({}));
    if(!r.ok){ $('smsHint').textContent = d.error || '登录失败'; return; }
    $('lCode').value = '';
    $('smsHint').textContent = '';
    showApp(); loadStats();
  }catch(e){ $('smsHint').textContent = '登录失败：' + e.message; }
};
$('lCode').addEventListener('keydown', e=>{ if(e.key==='Enter') $('smsLoginBtn').click(); });

$('logoutBtn').onclick = async ()=>{
  await fetch('./logout', {method:'POST'});
  showLogin();
};

/* 导航 */
const TITLES = {overview:['概览','问答服务运行状态'], kb:['知识库','上传与管理知识库资料'],
  prompt:['提示词 / 人设','编辑 AI 人设与约束'], test:['测试问答','页内验证回答效果'],
  settings:['模型设置','模型与生成参数'], security:['安全设置','密码 / 手机验证码 / 发送通道'],
  logs:['运行日志','服务最近日志']};
document.querySelectorAll('.nav-item').forEach(el=>{
  el.onclick = ()=>{
    document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
    el.classList.add('active');
    const tab = el.dataset.tab;
    ['overview','kb','prompt','test','settings','security','logs'].forEach(t=>{
      $('tab-'+t).classList.toggle('hide', t!==tab);
    });
    $('pageTitle').textContent = TITLES[tab][0];
    $('pageSub').textContent = TITLES[tab][1];
    if(tab==='overview') loadStats();
    if(tab==='kb') loadKB();
    if(tab==='prompt') loadPrompt();
    if(tab==='settings') loadSettings();
    if(tab==='security') loadSecurity();
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
const GROUP_BADGE = {share:'ok', qa:'ok', course:'ok', peers:''};
async function loadKB(){
  try{
    const d = await api('/kb');
    const f = $('kbFilter').value;
    const list = f ? d.items.filter(it=>it.group===f) : d.items;
    const cnt = {};
    d.items.forEach(it=>{ cnt[it.group]=(cnt[it.group]||0)+1; });
    $('kbCount').innerHTML = '共 ' + d.items.length + ' 个'
      + ' <span class="hint">（'+ ['share','qa','course','peers'].map(g=>{
          const lb = (d.group_labels&&d.group_labels[g])||g;
          return lb+' '+(cnt[g]||0);
        }).join(' · ') +'）</span>';
    $('kbBody').innerHTML = list.map(it=>`
      <tr>
        <td class="name">${esc(it.name)}</td>
        <td><span class="badge ${GROUP_BADGE[it.group]||''}">${esc(it.group_label||it.group)}</span></td>
        <td>${(it.size/1024).toFixed(1)} KB</td>
        <td>${it.mtime}</td>
        <td>
          <button class="btn-ghost btn-sm" onclick="openFile('${esc(it.name)}')">编辑</button>
          <button class="btn-danger btn-sm" onclick="delFile('${esc(it.name)}')">删除</button>
        </td>
      </tr>`).join('') || '<tr><td colspan="5" class="hint">暂无文件</td></tr>';
  }catch(e){ toast(e.message, true); }
}
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
$('kbRefresh').onclick = loadKB;
$('kbFilter').onchange = loadKB;

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
  fd.append('group', $('upGroup').value);
  fd.append('platform', $('upPlatform').value.trim());
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

/* 安全设置 */
let secState = {};
async function loadSecurity(){
  try{
    const s = await api('/sms-settings');
    secState = s;
    $('cpInfo').textContent = s.password_changed_at ? ('上次修改：' + s.password_changed_at) : '尚未修改过（仍是初始密码，建议立刻改）';
    $('bindPhone').textContent = s.phone_bound ? s.phone_masked : '未绑定';
    $('bindInput').placeholder = s.phone_bound ? ('当前 ' + s.phone_masked + '，输入新号可更换') : '11 位手机号';
    $('smsProvider').value = s.provider || 'log';
    $('smsWebhook').value = s.webhook_url || '';
    $('smsSid').value = s.secret_id_masked || '';
    $('smsApp').value = s.sdk_app_id || '';
    $('smsSign').value = s.sign_name || '';
    $('smsTpl').value = s.template_id || '';
    $('smsSkey').placeholder = s.has_secret ? '已配置（留空不修改）' : '当前：—';
    $('smsLast').textContent = s.last_code_line
      ? ('最近一条日志通道验证码：' + s.last_code_line)
      : '最近一条日志通道验证码：暂无';
    smsTogglePanes();
  }catch(e){ toast(e.message, true); }
}
function smsTogglePanes(){
  const v = $('smsProvider').value;
  $('pane-webhook').classList.toggle('hide', v!=='webhook');
  $('pane-tencent').classList.toggle('hide', v!=='tencent');
}
$('smsProvider').onchange = smsTogglePanes;

$('cpSave').onclick = async ()=>{
  const oldV = $('cpOld').value, n1 = $('cpNew').value.trim(), n2 = $('cpNew2').value.trim();
  if(!oldV || !n1){ toast('请填写当前密码和新密码', true); return; }
  if(n1 !== n2){ toast('两次输入的新密码不一致', true); return; }
  if(n1.length < 8){ toast('新密码至少 8 位', true); return; }
  try{
    await api('/change-password', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({old: oldV, new: n1})});
    $('cpOld').value = $('cpNew').value = $('cpNew2').value = '';
    toast('密码已修改，其他设备需重新登录');
    loadSecurity();
  }catch(e){ toast(e.message, true); }
};

$('bindSend').onclick = ()=>{
  const ph = $('bindInput').value.trim();
  if(!ph){ $('bindInfo').textContent = '请先输入手机号'; return; }
  requestCode(ph, $('bindSend'), $('bindInfo'), 'bind');
};
$('bindSave').onclick = async ()=>{
  const phone = $('bindInput').value.trim(), code = $('bindCode').value.trim();
  if(!phone || !code){ $('bindInfo').textContent = '请填写手机号和验证码'; return; }
  $('bindInfo').textContent = '验证中…';
  try{
    await api('/auth/verify-code', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({phone, code, purpose:'bind'})});
    $('bindCode').value = ''; $('bindInfo').textContent = '绑定成功';
    toast('手机号已绑定，可用验证码登录');
    loadSecurity();
  }catch(e){ $('bindInfo').textContent = e.message; }
};

$('smsSave').onclick = async ()=>{
  const v = $('smsProvider').value;
  const body = {provider: v,
    sms_webhook_url: $('smsWebhook').value.trim(),
    sms_secret_id: $('smsSid').value.trim(),
    sms_secret_key: $('smsSkey').value.trim(),
    sms_sdk_app_id: $('smsApp').value.trim(),
    sms_sign_name: $('smsSign').value.trim(),
    sms_template_id: $('smsTpl').value.trim()};
  try{
    await api('/sms-settings', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)});
    $('smsSkey').value = '';
    $('smsInfo').textContent = '已保存';
    toast('通道设置已保存');
    loadSecurity();
  }catch(e){ toast(e.message, true); }
};

$('smsTest').onclick = async ()=>{
  $('smsInfo').textContent = '发送中…';
  try{
    const d = await api('/sms/test', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({phone: $('bindInput').value.trim()})});
    $('smsInfo').textContent = '已通过 ' + d.provider + ' 发送到 ' + d.phone
      + (d.debug_code ? ('（测试码 ' + d.debug_code + '）') : '');
    loadSecurity();
  }catch(e){ $('smsInfo').textContent = e.message; }
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
