#!/usr/bin/env python3
"""Per-browser, encrypted Feishu API connections with verified upserts."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from cryptography.fernet import Fernet

DATA = Path(os.environ.get('FEISHU_SYNC_DATA', '/var/lib/siyumenghai-feishu-sync'))
PUBLIC_ORIGIN = 'https://siyumenghai.cn'
API_ROOT = 'https://open.feishu.cn/open-apis'
FIELDS = ('标题', '作者', '原视频链接', '逐字稿', '素材ID', '更新时间')
CIPHER: Fernet
POOL = ThreadPoolExecutor(max_workers=8)
LOCK = threading.Lock()
TABLE_LOCKS = [threading.Lock() for _ in range(64)]
ACTIVE = set()
TOKENS = {}

class Invalid(ValueError):
    pass

class Uncertain(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def initialize():
    global CIPHER
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_path = DATA / 'connection.key'
    if not key_path.exists():
        with key_path.open('xb') as handle:
            handle.write(Fernet.generate_key())
        key_path.chmod(0o600)
    CIPHER = Fernet(key_path.read_bytes())
    with database() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS connections (
          owner TEXT PRIMARY KEY, name TEXT NOT NULL, target TEXT NOT NULL,
          table_url TEXT NOT NULL, credentials BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS deliveries (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, target TEXT NOT NULL,
          source TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL,
          created REAL NOT NULL, sent REAL NOT NULL, record_id TEXT DEFAULT '',
          error TEXT DEFAULT '');
        CREATE INDEX IF NOT EXISTS by_source ON deliveries(owner,target,source,created);
        ''')
        db.execute("UPDATE deliveries SET state='awaiting',error='服务已重连，请点击重试核对保存结果。' WHERE state='sending'")
    (DATA / 'sync.sqlite3').chmod(0o600)


def database():
    db = sqlite3.connect(DATA / 'sync.sqlite3', timeout=10)
    db.row_factory = sqlite3.Row
    return db


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def feishu_url(value):
    try:
        parsed = urlparse(value)
        host = parsed.hostname or ''
        if (parsed.scheme != 'https' or not (host == 'feishu.cn' or host.endswith('.feishu.cn'))
            or not re.fullmatch(r'/base/[A-Za-z0-9]+/?', parsed.path)
            or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError()
    except ValueError:
        raise Invalid('请填写飞书多维表格的数据表链接（https://…feishu.cn/base/…?table=tbl…）。')
    table = parse_qs(parsed.query).get('table', [''])[0]
    if not re.fullmatch(r'tbl[A-Za-z0-9]+', table):
        raise Invalid('请打开目标数据表后，复制包含 table=tbl… 的完整链接。')
    query = {'table': table}
    view = parse_qs(parsed.query).get('view', [''])[0]
    if re.fullmatch(r'vew[A-Za-z0-9]+', view):
        query['view'] = view
    return parsed._replace(query=urlencode(query), fragment='').geturl()


def source_url(value):
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.netloc != 'weixin.qq.com' or not re.fullmatch(r'/sph/[A-Za-z0-9_-]+', parsed.path):
        raise Invalid('视频号原链接无效。')
    return 'https://weixin.qq.com' + parsed.path


def connection(owner):
    with database() as db:
        return db.execute('SELECT * FROM connections WHERE owner=?', (owner,)).fetchone()


def credentials(conn):
    value = json.loads(CIPHER.decrypt(conn['credentials'])) if conn else {}
    return value if value.get('app_id') else {}


def request_json(path, body=None, token='', method=None):
    # Only this fixed official API host receives credentials or transcript text.
    request = Request(API_ROOT + path, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json; charset=utf-8', **({'Authorization': 'Bearer ' + token} if token else {})}, method=method)
    try:
        with build_opener(NoRedirect).open(request, timeout=10) as response:
            value = json.loads(response.read(2 * 1024 * 1024))
    except HTTPError as exc:
        if exc.code == 429 or exc.code >= 500:
            raise Uncertain('飞书暂时繁忙，请稍后重试核对保存结果。')
        raise Invalid('飞书拒绝访问，请检查应用权限和目标表格的文档应用权限。')
    except (URLError, TimeoutError, OSError, ValueError):
        raise Uncertain('连接中断，尚未确认写入结果；请稍后重试核对。')
    if not isinstance(value, dict):
        raise Uncertain('飞书响应异常，请稍后重试核对保存结果。')
    return value


def checked(value):
    code = value.get('code')
    if code == 0:
        return value.get('data', {})
    if code in (1254290, 1254291, 1254607) or code is None:
        raise Uncertain('飞书暂时繁忙，请稍后重试核对保存结果。')
    if code in (1254040, 1254041):
        raise Invalid('找不到目标表格，请检查链接，并将此应用添加为该表格的文档应用。')
    if code in (1254044, 1254045, 1254015, 1254060):
        raise Invalid('表格字段不匹配，请按配置说明保留六个同名的文本字段。')
    raise Invalid('飞书访问失败（错误码 %s），请检查应用已发布、API 权限和目标表格的文档应用权限。' % code)


def access_token(cred, refresh=False):
    key = digest(cred['app_id'] + cred['app_secret'])
    with LOCK:
        cached = TOKENS.get(key)
    if cached and cached[1] > time.time() and not refresh:
        return cached[0]
    result = request_json('/auth/v3/tenant_access_token/internal', {'app_id': cred['app_id'], 'app_secret': cred['app_secret']})
    checked(result)
    token = result.get('tenant_access_token', '')
    if not token:
        raise Invalid('应用凭证验证失败，请检查 App ID 和 App Secret。')
    with LOCK:
        if len(TOKENS) > 500:
            TOKENS.clear()
        TOKENS[key] = (token, time.time() + max(0, int(result.get('expire', 0)) - 120))
    return token


def api(cred, suffix, body=None, method=None):
    path = '/bitable/v1/apps/' + cred['base_token'] + '/tables/' + cred['table_id'] + suffix
    result = request_json(path, body, access_token(cred), method)
    if result.get('code') in (99991663, 99991664, 99991668):
        result = request_json(path, body, access_token(cred, refresh=True), method)
    return checked(result)


def configure(owner, data):
    previous = credentials(connection(owner))
    app_id = str(data.get('app_id') or '').strip()
    secret = str(data.get('app_secret') or (previous.get('app_secret') if app_id == previous.get('app_id') else '') or '').strip()
    if not re.fullmatch(r'cli_[A-Za-z0-9]+', app_id) or not re.fullmatch(r'[\x21-\x7e]{8,500}', secret):
        raise Invalid('请填写有效的 App ID 和 App Secret。更换应用时需要重新填写密钥。')
    table_url = feishu_url(str(data.get('table_url') or '').strip())
    parsed = urlparse(table_url)
    cred = {'app_id': app_id, 'app_secret': secret, 'base_token': parsed.path.strip('/').split('/')[-1], 'table_id': parse_qs(parsed.query)['table'][0]}
    fields, page_token = {}, ''
    while True:
        result = api(cred, '/fields?' + urlencode({'page_size':100, **({'page_token':page_token} if page_token else {})}))
        fields.update({item['field_name']: item['type'] for item in result.get('items', [])})
        if not result.get('has_more'):
            break
        next_token = result.get('page_token', '')
        if not next_token or next_token == page_token:
            raise Invalid('字段读取未完成，请稍后重试。')
        page_token = next_token
    if any(fields.get(field) != 1 for field in FIELDS):
        raise Invalid('请将 标题、作者、原视频链接、逐字稿、素材ID、更新时间 六个字段设置为文本类型。')
    # Check search permission without creating a test record in the user's table.
    find_record(cred, digest('configuration-check'))
    name = str(data.get('name') or '我的视频素材库').strip()[:80]
    target = digest(cred['base_token'] + '/' + cred['table_id'])
    encrypted = CIPHER.encrypt(json.dumps(cred).encode())
    with database() as db:
        db.execute('INSERT OR REPLACE INTO connections VALUES (?,?,?,?,?)', (owner, name, target, table_url, encrypted))
    return {'configured':True, 'name':name, 'table_url':table_url, 'app_id':app_id}


def record_url(conn, record_id):
    parsed = urlparse(conn['table_url'])
    query = {key:values[0] for key,values in parse_qs(parsed.query).items() if key in {'table','view'}}
    if record_id:
        query['record'] = record_id
    return parsed._replace(query=urlencode(query)).geturl()


def public_delivery(row, conn):
    return {'request_id':row['id'], 'status':row['state'], 'record_url':record_url(conn,row['record_id']) if row['state']=='confirmed' else '',
            'error':row['error'], 'retry_after':max(0, int(60 - (time.time()-row['sent'])))}


def find_record(cred, source):
    result = api(cred, '/records/search?page_size=2', {'field_names':list(FIELDS), 'filter':{'conjunction':'and', 'conditions':[{'field_name':'素材ID','operator':'is','value':[source]}]}})
    items = result.get('items', [])
    if len(items) > 1 or result.get('has_more'):
        raise Invalid('素材库存在多条相同素材ID的记录，请先在飞书合并，再重试。')
    return items[0] if items else None


def text_value(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(item.get('text','') for item in value if isinstance(item, dict))
    return ''


def worker(conn, row, values):
    state, error, record_id = 'awaiting', '', ''
    try:
        cred = credentials(conn)
        fields = dict(zip(FIELDS, (values['title'],values['author'],values['source_url'],values['transcript'],row['source'],time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime(row['created']+8*3600))+' +08:00')))
        # Serialise writes to the same table, including different browser connections.
        table_lock = TABLE_LOCKS[int(conn['target'][:8], 16) % len(TABLE_LOCKS)]
        with table_lock:
            existing = find_record(cred, row['source'])
            if existing:
                record_id = existing['record_id']
                if any(text_value(existing.get('fields',{}).get(key)) != value for key,value in fields.items()):
                    api(cred, '/records/' + record_id, {'fields':fields}, 'PUT')
            else:
                result = api(cred, '/records?' + urlencode({'client_token':row['id']}), {'fields':fields})
                record_id = result.get('record',{}).get('record_id','')
            if not re.fullmatch(r'rec[A-Za-z0-9]+', record_id):
                raise Uncertain('飞书未返回有效记录，请稍后重试核对保存结果。')
            result = api(cred, '/records/batch_get', {'record_ids':[record_id]})
            records = result.get('records', [])
            if len(records) != 1 or records[0].get('record_id') != record_id or any(text_value(records[0].get('fields',{}).get(key)) != value for key,value in fields.items()):
                raise Uncertain('已请求写入，但文案尚未核对一致，请稍后重试。')
            state = 'confirmed'
    except Invalid as exc:
        state, error = 'error', str(exc)
    except Uncertain as exc:
        error = str(exc)
    except Exception:
        error = '保存结果尚未确认，请稍后重试核对。'
    finally:
        with database() as db:
            db.execute('UPDATE deliveries SET state=?,error=?,record_id=? WHERE id=?', (state,error,record_id,row['id']))
        with LOCK:
            ACTIVE.discard(row['id'])


def save(owner, data):
    conn = connection(owner)
    if not conn or not credentials(conn):
        raise Invalid('请先配置飞书应用和目标表格。')
    share = source_url(str(data.get('source_url') or ''))
    text = str(data.get('transcript') or '')
    if not text.strip() or len(text) > 100000:
        raise Invalid('请先生成并保存逐字稿（最多 10 万字）。')
    values = {'title':str(data.get('title') or '视频号视频')[:1000], 'author':str(data.get('author') or '')[:200], 'source_url':share, 'transcript':text}
    content_hash = digest(json.dumps(values,ensure_ascii=False,sort_keys=True))
    source, now = digest(share), time.time()
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM deliveries WHERE owner=? AND target=? AND source=? ORDER BY created DESC LIMIT 1',(owner,conn['target'],source)).fetchone()
        if row and row['state'] in {'sending','awaiting'}:
            with LOCK:
                active = row['id'] in ACTIVE
            if row['digest'] != content_hash:
                raise Invalid('上一版本尚待确认，请先打开飞书检查，重试确认后再保存新版本。')
            if active or not data.get('retry') or now-row['sent'] < 60:
                return public_delivery(row,conn)
        else:
            # A fresh click also rechecks externally edited/deleted records.
            request_id = str(uuid.uuid4())
            db.execute("INSERT INTO deliveries(id,owner,target,source,digest,state,created,sent) VALUES (?,?,?,?,?,'sending',?,?)",(request_id,owner,conn['target'],source,content_hash,now,now))
            row = db.execute('SELECT * FROM deliveries WHERE id=?',(request_id,)).fetchone()
        with LOCK:
            if len(ACTIVE) >= 32:
                raise Invalid('当前保存任务较多，请稍后再试。')
            ACTIVE.add(row['id'])
        db.execute("UPDATE deliveries SET state='sending',sent=?,error='' WHERE id=?",(now,row['id']))
    POOL.submit(worker, conn, dict(row), values)
    return {'request_id':row['id'], 'status':'sending', 'record_url':'', 'error':'', 'retry_after':60}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def send(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(body)

    def owner(self):
        value=self.headers.get('Authorization','')
        if not re.fullmatch(r'Bearer [a-f0-9]{64}',value):
            raise Invalid('连接凭证无效，请重新配置飞书。')
        return digest(value[7:])

    def do_GET(self):
        try:
            path=urlparse(self.path).path
            if path=='/healthz':
                return self.send(200,{'ok':True})
            owner=self.owner()
            conn=connection(owner)
            if path=='/connection':
                cred=credentials(conn)
                return self.send(200,{'configured':bool(cred),'name':conn['name'] if cred else '', 'table_url':conn['table_url'] if cred else '', 'app_id':cred.get('app_id','')})
            if path.startswith('/deliveries/') and conn:
                with database() as db:
                    row=db.execute('SELECT * FROM deliveries WHERE id=? AND owner=? AND target=?',(path.split('/')[-1],owner,conn['target'])).fetchone()
                if row:
                    return self.send(200,public_delivery(row,conn))
            self.send(404,{'error':'没有找到本次保存记录。'})
        except Invalid as exc:
            self.send(400,{'error':str(exc)})
        except Exception:
            self.send(503,{'error':'飞书保存服务暂时不可用，请稍后重试。'})

    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if origin and origin not in {PUBLIC_ORIGIN,'https://www.siyumenghai.cn'}:
                raise Invalid('请求来源无效。')
            size=int(self.headers.get('Content-Length','0'))
            if size<=0 or size>512*1024:
                raise Invalid('请求内容过大或为空。')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):
                raise Invalid('请求格式无效。')
            owner=self.owner()
            path=urlparse(self.path).path
            if path=='/connection':
                return self.send(200,configure(owner,data))
            if path=='/save':
                return self.send(200,save(owner,data))
            self.send(404,{'error':'接口不存在。'})
        except (Invalid,ValueError,TypeError) as exc:
            self.send(400,{'error':str(exc) if isinstance(exc,Invalid) else '请求格式无效。'})
        except Uncertain as exc:
            self.send(503,{'error':str(exc)})
        except Exception:
            self.send(503,{'error':'飞书保存服务暂时不可用，请稍后重试。'})

if __name__=='__main__':
    os.umask(0o077)
    initialize()
    ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('FEISHU_SYNC_PORT','2033'))),Handler).serve_forever()
