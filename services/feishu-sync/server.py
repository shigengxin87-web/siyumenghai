#!/usr/bin/env python3
"""Per-browser Feishu webhook connections and verified write receipts."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from cryptography.fernet import Fernet

DATA = Path(os.environ.get("FEISHU_SYNC_DATA", "/var/lib/siyumenghai-feishu-sync"))
PUBLIC_ORIGIN = "https://siyumenghai.cn"
CALLBACK_URL = PUBLIC_ORIGIN + "/api/feishu-sync/receipts"
KEY = b""
CIPHER: Fernet


class Invalid(ValueError):
    pass


def initialize():
    global KEY, CIPHER
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_path = DATA / "connection.key"
    if not key_path.exists():
        with key_path.open("xb") as handle:
            handle.write(Fernet.generate_key())
        key_path.chmod(0o600)
    KEY = key_path.read_bytes()
    CIPHER = Fernet(KEY)
    with database() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS connections (
          owner TEXT PRIMARY KEY, name TEXT NOT NULL, target TEXT NOT NULL,
          table_url TEXT NOT NULL, credentials BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS deliveries (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, target TEXT NOT NULL,
          source TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL,
          created REAL NOT NULL, sent REAL NOT NULL, record_id TEXT DEFAULT '',
          error TEXT DEFAULT '');
        CREATE INDEX IF NOT EXISTS by_source ON deliveries(owner,target,source,created);
        """)
    (DATA / "sync.sqlite3").chmod(0o600)


def database():
    db = sqlite3.connect(DATA / "sync.sqlite3", timeout=10)
    db.row_factory = sqlite3.Row
    return db


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def feishu_url(value: str, webhook=False) -> str:
    try:
        parsed = urlparse(value)
        host = parsed.hostname or ""
        valid_host = host == "feishu.cn" or host.endswith(".feishu.cn")
        path_ok = re.fullmatch(r"/base/automation/webhook/event/[A-Za-z0-9_-]+/?", parsed.path) if webhook else re.fullmatch(r"/base/[A-Za-z0-9]+/?", parsed.path)
        if parsed.scheme != "https" or not valid_host or not path_ok or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.fragment:
            raise Invalid()
        if webhook and parsed.query:
            raise Invalid()
    except ValueError:
        raise Invalid("请填写有效的飞书多维表格" + (" Webhook 接收地址。" if webhook else "链接（/base/ 开头）。"))
    return value


def source_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "weixin.qq.com" or not re.fullmatch(r"/sph/[A-Za-z0-9_-]+", parsed.path):
        raise Invalid("视频号原链接无效。")
    return "https://weixin.qq.com" + parsed.path


def receipt_token(request_id: str) -> str:
    return hmac.new(KEY, request_id.encode(), hashlib.sha256).hexdigest()


def connection(owner: str):
    with database() as db:
        return db.execute("SELECT * FROM connections WHERE owner=?", (owner,)).fetchone()


def configure(owner: str, data: dict):
    old = connection(owner)
    previous = json.loads(CIPHER.decrypt(old["credentials"])) if old else {}
    url = str(data.get("webhook_url") or previous.get("url") or "").strip()
    feishu_url(url, webhook=True)
    table_url = feishu_url(str(data.get("table_url") or "").strip())
    token = str(data.get("webhook_token") or (previous.get("token") if url == previous.get("url") else "") or "").strip()
    if not re.fullmatch(r"[\x21-\x7e]{8,1000}",token):
        raise Invalid("请在飞书接收流程开启凭证校验，并填写校验凭证。")
    name = str(data.get("name") or "我的视频素材库").strip()[:80]
    target = digest(url)
    encrypted = CIPHER.encrypt(json.dumps({"url":url,"token":token}).encode())
    with database() as db:
        db.execute("INSERT OR REPLACE INTO connections VALUES (?,?,?,?,?)", (owner,name,target,table_url,encrypted))
    return {"configured": True,"name": name,"table_url":table_url}


def record_url(conn, record_id: str) -> str:
    parsed = urlparse(conn["table_url"])
    query = {key:values[0] for key,values in parse_qs(parsed.query).items() if key in {"table","view"}}
    if record_id:
        query["record"] = record_id
    return parsed._replace(query=urlencode(query), fragment="").geturl()


def public_delivery(row, conn):
    return {"request_id":row["id"], "status":row["state"], "record_url":record_url(conn,row["record_id"]) if row["state"] == "confirmed" else "", "error":row["error"], "retry_after":max(0, int(60-(time.time()-row["sent"])))}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def forward(url, token, payload):
    request = Request(url, data=json.dumps(payload,ensure_ascii=False).encode(), headers={"Content-Type":"application/json","Authorization":"Bearer "+token}, method="POST")
    with build_opener(NoRedirect).open(request,timeout=12) as response:
        result = json.loads(response.read(65536))
        if not isinstance(result,dict) or result.get("code") != 0:
            raise Invalid("飞书未接收本次请求，请检查接收流程和校验凭证。")


def save(owner: str, data: dict):
    conn = connection(owner)
    if not conn:
        raise Invalid("请先配置飞书接收流程。")
    share = source_url(str(data.get("source_url") or ""))
    text = str(data.get("transcript") or "")
    if not text.strip() or len(text) > 100000:
        raise Invalid("请先生成并保存逐字稿（最多 10 万字）。")
    values = {"title":str(data.get("title") or "视频号视频")[:1000],"author":str(data.get("author") or "")[:200],"source_url":share,"transcript":text}
    content_hash = digest(json.dumps(values,ensure_ascii=False,sort_keys=True))
    source = digest(share)
    now = time.time()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM deliveries WHERE owner=? AND target=? AND source=? ORDER BY created DESC LIMIT 1",(owner,conn["target"],source)).fetchone()
        if row and row["state"] in {"sending","awaiting"}:
            if row["digest"] != content_hash:
                raise Invalid("上一版本尚待飞书确认，请先检查保存结果后再发送新版本。")
            if not data.get("retry") or now-row["sent"] < 60:
                return public_delivery(row,conn)
        elif row and row["digest"] == content_hash and row["state"] == "confirmed":
            return public_delivery(row,conn)
        else:
            request_id = secrets.token_hex(20)
            db.execute("INSERT INTO deliveries(id,owner,target,source,digest,state,created,sent) VALUES (?,?,?,?,?,'sending',?,?)",(request_id,owner,conn["target"],source,content_hash,now,now))
            row = db.execute("SELECT * FROM deliveries WHERE id=?",(request_id,)).fetchone()
        db.execute("UPDATE deliveries SET state='sending',sent=?,error='' WHERE id=?",(now,row["id"]))
    credentials = json.loads(CIPHER.decrypt(conn["credentials"]))
    payload = {**values,"schema_version":1,"source_id":source,"request_id":row["id"],"updated_at":time.strftime("%Y-%m-%d %H:%M:%S",time.gmtime(now+8*3600))+" +08:00","callback_url":CALLBACK_URL,"callback_token":receipt_token(row["id"])}
    state, error = "awaiting", ""
    try:
        forward(credentials["url"],credentials["token"],payload)
    except HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code != 429:
            state,error="error","飞书拒绝接收，请检查接收地址、凭证和流程状态。"
        else:
            error="尚未确认是否送达，请先等待回执或到飞书检查。"
    except Invalid as exc:
        state,error="error",str(exc)
    except (URLError, TimeoutError, OSError, ValueError):
        error="连接中断，尚未确认是否送达，请先等待回执或到飞书检查。"
    with database() as db:
        db.execute("UPDATE deliveries SET state=?,error=? WHERE id=? AND state='sending'",(state,error,row["id"]))
        updated = db.execute("SELECT * FROM deliveries WHERE id=?",(row["id"],)).fetchone()
    return public_delivery(updated,conn)


def receive(data: dict):
    request_id = str(data.get("request_id") or "")
    if not hmac.compare_digest(str(data.get("callback_token") or ""),receipt_token(request_id)):
        raise Invalid("回执凭证无效。")
    record_id = data.get("record_id") or ""
    if isinstance(record_id,list) and len(record_id)==1:
        record_id=record_id[0]
    record_id=str(record_id)
    if not re.fullmatch(r"rec[A-Za-z0-9]+",record_id) or data.get("status") != "saved":
        raise Invalid("回执必须包含已写入的飞书记录 ID。")
    with database() as db:
        row = db.execute("SELECT * FROM deliveries WHERE id=?",(request_id,)).fetchone()
        if not row or row["source"] != data.get("source_id"):
            raise Invalid("回执与保存请求不匹配。")
        db.execute("UPDATE deliveries SET state='confirmed',record_id=?,error='' WHERE id=?",(record_id,request_id))
    return {"received": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def send(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        self.wfile.write(body)

    def owner(self):
        value=self.headers.get("Authorization","")
        if not re.fullmatch(r"Bearer [a-f0-9]{64}",value):
            raise Invalid("连接凭证无效，请重新配置飞书。")
        return digest(value[7:])

    def do_GET(self):
        try:
            path=urlparse(self.path).path
            if path=="/healthz":
                return self.send(200,{"ok":True})
            owner=self.owner()
            conn=connection(owner)
            if path=="/connection":
                return self.send(200,{"configured":bool(conn),"name":conn["name"] if conn else "","table_url":conn["table_url"] if conn else ""})
            if path.startswith("/deliveries/") and conn:
                with database() as db:
                    row=db.execute("SELECT * FROM deliveries WHERE id=? AND owner=? AND target=?",(path.split("/")[-1],owner,conn["target"])).fetchone()
                if row:
                    return self.send(200,public_delivery(row,conn))
            self.send(404,{"error":"没有找到本次保存记录。"})
        except Invalid as exc:
            self.send(400,{"error":str(exc)})

    def do_POST(self):
        try:
            origin=self.headers.get("Origin")
            if origin and origin not in {PUBLIC_ORIGIN,"https://www.siyumenghai.cn"}:
                raise Invalid("请求来源无效。")
            size=int(self.headers.get("Content-Length","0"))
            if size<=0 or size>512*1024:
                raise Invalid("请求内容过大或为空。")
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):
                raise Invalid("请求格式无效。")
            path=urlparse(self.path).path
            if path=="/receipts":
                return self.send(200,receive(data))
            owner=self.owner()
            if path=="/connection":
                return self.send(200,configure(owner,data))
            if path=="/save":
                return self.send(200,save(owner,data))
            self.send(404,{"error":"接口不存在。"})
        except (Invalid,ValueError,TypeError) as exc:
            self.send(400,{"error":str(exc) if isinstance(exc,Invalid) else "请求格式无效。"})
        except Exception:
            self.send(503,{"error":"飞书保存服务暂时不可用，请稍后重试。"})


if __name__=="__main__":
    os.umask(0o077)
    initialize()
    ThreadingHTTPServer(("127.0.0.1",int(os.environ.get("FEISHU_SYNC_PORT","2033"))),Handler).serve_forever()
