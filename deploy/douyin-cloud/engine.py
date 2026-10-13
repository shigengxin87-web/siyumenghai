"""Loopback-only DouK compatibility backend. Never logs URLs or credentials."""
import asyncio
import hmac
import os
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from curl_cffi.requests import AsyncSession
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).parent / 'vendor'))
from src.custom import DATA_HEADERS, IMPERSONATE, USERAGENT
from src.encrypt import DouYinParams
from src.interface.template import API

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
secret = os.environ['DTK_API_KEY']
cookie_path = Path(os.environ.get('DOUYIN_COOKIE_FILE', '/etc/siyumenghai-douyin/cookies.yaml'))
lock = asyncio.Lock()
next_request = 0.0
cooldown_until = 0.0
cache = OrderedDict()
last_success = None
ALLOWED = {'douyin.com','www.douyin.com','v.douyin.com','iesdouyin.com','www.iesdouyin.com'}

class UpstreamError(Exception):
    def __init__(self, status=502): self.status = status

def valid_url(raw):
    u = urlsplit(raw)
    if u.scheme != 'https' or u.hostname not in ALLOWED or u.username or u.password or u.port not in (None,443):
        raise ValueError('仅支持抖音 HTTPS 链接')
    return raw

def pick(obj):
    return next((x for x in (obj or {}).get('url_list', []) if isinstance(x,str) and x.startswith('https://')), None)

def shape(d):
    if not isinstance(d,dict) or not re.fullmatch(r'\d{10,25}',str(d.get('aweme_id',''))): raise UpstreamError()
    vid=d.get('video') or {}
    images=[{'url':pick(x)} for x in d.get('images') or [] if pick(x)]
    video=pick(vid.get('play_addr'))
    return {'platform':'douyin','content_id':str(d['aweme_id']),'description':d.get('desc',''),
            'created_at':datetime.fromtimestamp(d.get('create_time',0),timezone.utc).isoformat(),
            'author':{'nickname':(d.get('author') or {}).get('nickname','')},'stats':d.get('statistics') or {},
            'media':{'covers':[{'url':pick(vid.get('cover'))}] if pick(vid.get('cover')) else [],
                     'video':{'url':video,'watermark':False} if video and not images else None,'images':images}}

async def detail_id(raw):
    valid_url(raw)
    for _ in range(6):
        m=re.search(r'/(?:video|note|slides)/(\d{10,25})',urlsplit(raw).path)
        if m: return m[1]
        from urllib.parse import parse_qs, urljoin
        q=parse_qs(urlsplit(raw).query)
        if q.get('modal_id') and re.fullmatch(r'\d{10,25}',q['modal_id'][0]): return q['modal_id'][0]
        async with AsyncSession(impersonate=IMPERSONATE,timeout=10,verify=True,allow_redirects=False,trust_env=False) as c:
            r=await c.get(raw,headers={'User-Agent':USERAGENT},allow_redirects=False)
        if r.status_code not in (301,302,303,307,308) or not r.headers.get('location'): break
        raw=valid_url(urljoin(raw,r.headers['location']))
    raise ValueError('无法从抖音链接提取作品 ID')

async def fetch_data(path, extra):
    global next_request, cooldown_until, last_success
    async with lock:
        now=time.monotonic()
        if now<cooldown_until: raise UpstreamError(429)
        await asyncio.sleep(max(0,next_request-now))
        next_request=time.monotonic()+3
        cookie=(yaml.safe_load(cookie_path.read_text()) or {}).get('douyin_cookie','')
        if not cookie: raise UpstreamError(503)
        values=dict(x.strip().split('=',1) for x in cookie.split(';') if '=' in x)
        params=API.params|{'msToken':values.get('msToken',''),'uifid':values.get('UIFID','')}|extra
        url='https://www.douyin.com'+path
        query=DouYinParams().sign_url(url,params,user_agent=USERAGENT)
        async with AsyncSession(impersonate=IMPERSONATE,timeout=20,verify=True,allow_redirects=False,trust_env=False) as c:
            r=await c.get(url+'?'+query,headers=DATA_HEADERS|{'Cookie':cookie,'uifid':values.get('UIFID','')})
        if r.status_code in (403,429):
            cooldown_until=time.monotonic()+300
            raise UpstreamError(429)
        if r.status_code!=200 or len(r.content)>8*1024*1024: raise UpstreamError()
        try: data=r.json()
        except Exception: raise UpstreamError() from None
        if not isinstance(data,dict) or data.get('status_code',0)!=0: raise UpstreamError()
        last_success=datetime.now(timezone.utc).isoformat()
        return data

@app.middleware('http')
async def boundary(request:Request,call_next):
    if not hmac.compare_digest(request.headers.get('authorization',''), 'Bearer '+secret):
        return JSONResponse({'success':False,'error':{'message':'Unauthorized'}},status_code=401)
    try: return await call_next(request)
    except ValueError as e: return JSONResponse({'success':False,'error':{'message':str(e)}},status_code=400)
    except Exception as e:
        status=e.status if isinstance(e,UpstreamError) else 502
        msg='抖音暂时限制访问，请等待至少 5 分钟后重试' if status==429 else '抖音暂未返回有效数据，请稍后重试'
        return JSONResponse({'success':False,'error':{'message':msg}},status_code=status)

def ok(data): return {'success':True,'data':data}

@app.get('/api/v1/health')
async def health(): return ok({'engine':'douk-cloud','mac_required':False,'last_success':last_success,'cooldown_seconds':max(0,int(cooldown_until-time.monotonic()))})

@app.post('/api/v1/parse')
async def parse(request:Request):
    b=await request.json(); id=await detail_id(str(b.get('url','')))
    cached=cache.get(id)
    if cached and time.monotonic()-cached[0]<300: return ok(cached[1])
    data=await fetch_data('/aweme/v1/web/aweme/detail/',{'aweme_id':id,'version_code':'190500','version_name':'19.5.0'})
    post=shape(data.get('aweme_detail'))
    if post['content_id']!=id: raise UpstreamError()
    cache[id]=(time.monotonic(),post);cache.move_to_end(id)
    while len(cache)>100:cache.popitem(last=False)
    return ok(post)

def creator(request):
    uid=request.query_params.get('sec_user_id','')
    if not uid:
        raw=valid_url(request.query_params.get('url',''))
        m=re.fullmatch(r'/user/(MS4wLjAB[\w-]{10,250})/?',urlsplit(raw).path)
        uid=m[1] if m else ''
    if not re.fullmatch(r'MS4wLjAB[\w-]{10,250}',uid): raise ValueError('博主主页或 sec_uid 无效')
    return uid

def number(request,name,default,maximum):
    raw=request.query_params.get(name,str(default))
    if not re.fullmatch(r'\d{1,20}',raw):raise ValueError('分页参数无效')
    value=int(raw)
    if value>maximum:raise ValueError('分页参数无效')
    return value

@app.get('/api/v1/douyin/user')
async def profile(request:Request):
    uid=creator(request)
    d=(await fetch_data('/aweme/v1/web/user/profile/other/',{'sec_user_id':uid,'publish_video_strategy_type':'2','personal_center_strategy_type':'1'})).get('user')
    if not d:raise UpstreamError()
    return ok({'nickname':d.get('nickname'),'signature':d.get('signature'),'sec_uid':uid,'verified':bool(d.get('custom_verify')),
               'stats':{'follower_count':d.get('follower_count'),'content_count':d.get('aweme_count'),'total_digg':d.get('total_favorited')},'web_url':'https://www.douyin.com/user/'+uid})

@app.get('/api/v1/douyin/video/comments')
async def comments(request:Request):
    id=request.query_params.get('aweme_id','')
    if not re.fullmatch(r'\d{10,25}',id):raise ValueError('作品 ID 无效')
    d=await fetch_data('/aweme/v1/web/comment/list/',{'aweme_id':id,'cursor':number(request,'cursor',0,10**20),'count':number(request,'count',20,50),'item_type':'0','version_code':'170400','version_name':'17.4.0'})
    if 'comments' not in d:raise UpstreamError()
    # Only expose public comment fields, not upstream login/session metadata.
    items=[{'id':c.get('cid'),'text':c.get('text'),'digg_count':c.get('digg_count'),'user':{'nickname':(c.get('user') or {}).get('nickname')}} for c in d.get('comments') or []]
    return ok({'items':items,'cursor':str(d.get('cursor',0)),'has_more':bool(d.get('has_more'))})

@app.get('/api/v1/douyin/user/posts')
async def posts(request:Request):
    d=await fetch_data('/aweme/v1/web/aweme/post/',{'sec_user_id':creator(request),'max_cursor':number(request,'cursor',0,10**20),'count':number(request,'count',20,50),'locate_query':'false','need_time_list':'1','publish_video_strategy_type':'2'})
    if 'aweme_list' not in d:raise UpstreamError()
    return ok({'items':[shape(x) for x in d.get('aweme_list') or []],'cursor':str(d.get('max_cursor',0)),'has_more':bool(d.get('has_more'))})

@app.get('/api/v1/douyin/mix/posts')
async def mix(request:Request):
    id=request.query_params.get('mix_id','')
    if not id:
        raw=valid_url(request.query_params.get('url',''))
        for _ in range(6):
            parts=urlsplit(raw)
            found=re.search(r'/(?:collection|share/mix/detail)/(\d{5,30})(?:/|$)',parts.path)
            if found:
                id=found[1]
                break
            detail=re.search(r'/(?:video|note|slides)/(\d{10,25})',parts.path)
            if not detail:
                from urllib.parse import parse_qs
                modal=parse_qs(parts.query).get('modal_id',[''])[0]
                detail=re.fullmatch(r'\d{10,25}',modal)
            if detail:
                detail_id_value=detail[1] if hasattr(detail,'lastindex') and detail.lastindex else detail[0]
                data=await fetch_data('/aweme/v1/web/aweme/detail/',{'aweme_id':detail_id_value,'version_code':'190500','version_name':'19.5.0'})
                id=str(((data.get('aweme_detail') or {}).get('mix_info') or {}).get('mix_id') or '')
                break
            from urllib.parse import urljoin
            async with AsyncSession(impersonate=IMPERSONATE,timeout=10,verify=True,allow_redirects=False,trust_env=False) as c:
                response=await c.get(raw,headers={'User-Agent':USERAGENT},allow_redirects=False)
            if response.status_code not in (301,302,303,307,308) or not response.headers.get('location'):break
            raw=valid_url(urljoin(raw,response.headers['location']))
    if not re.fullmatch(r'\d{5,30}',id):raise ValueError('请粘贴合集分享链接、合集网址，或合集中的任意作品链接')
    d=await fetch_data('/aweme/v1/web/mix/aweme/',{'mix_id':id,'cursor':number(request,'cursor',0,10**20),'count':number(request,'count',20,50)})
    if 'aweme_list' not in d:raise UpstreamError()
    return ok({'items':[shape(x) for x in d.get('aweme_list') or []],'cursor':str(d.get('cursor',0)),'has_more':bool(d.get('has_more'))})
