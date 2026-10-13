import http from 'node:http';
import https from 'node:https';
import dns from 'node:dns/promises';
import net from 'node:net';
import { randomBytes } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';

const base = process.env.DTK_URL || 'http://127.0.0.1:8000';
const key = process.env.DTK_API_KEY || '';
const tickets = new Map();
const creatorNextRequest = new Map();
const CREATOR_GAP_MS = 15000;
const CREATOR_COOLDOWN_MS = 5 * 60 * 1000;
let active = 0;
const MAX_BYTES = 512 * 1024 * 1024;
export function extractUrl(text) {
  const raw = String(text).match(/https?:\/\/[^\s<>"“”]+/u)?.[0]?.replace(/[，。！）)]+$/u, '');
  if (!raw) throw new Error('请粘贴抖音分享链接或包含链接的文案');
  const u = new URL(raw);
  if (u.protocol !== 'https:' || !['douyin.com','www.douyin.com','v.douyin.com','www.iesdouyin.com','iesdouyin.com'].includes(u.hostname) || u.username || u.password || (u.port && u.port !== '443')) throw new Error('仅支持抖音 HTTPS 链接');
  return u.href;
}
export function unwrap(body) {
  if (!body || body.success !== true) throw new Error(body?.error?.message || '解析服务返回错误');
  return body.data;
}
export async function resolveTask(initial, poll, sleep = ms => new Promise(r => setTimeout(r, ms)), deadline = 90000) {
  let data = initial;
  if (!data?.task_id) return data;
  const id = data.task_id;
  const end = Date.now() + deadline;
  // A cached task can be returned as done without an embedded result.
  // In that case the canonical task GET includes the actual payload.
  if (data.state === 'done' && data.data == null) data = await poll(id);
  while (true) {
    if (data.state === 'failed') throw new Error(data.error?.message || '解析任务失败');
    if (data.state === 'done') {
      if (data.data == null) throw new Error('解析任务已结束但结果缺失');
      return data.data;
    }
    if (Date.now() >= end) throw new Error('解析超时，请稍后重试');
    await sleep(1000);
    data = await poll(id);
  }
}
async function engine(path, options = {}) {
  if (!key) throw new Error('解析服务尚未配置');
  let res;
  try { res = await fetch(new URL(path, base), { ...options, headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', ...options.headers }, signal: AbortSignal.timeout(20000) }); }
  catch { throw new Error('暂时无法连接解析服务'); }
  let body;
  try { body = await res.json(); } catch { throw new Error('解析服务响应异常'); }
  const data = unwrap(body);
  if (!res.ok) throw new Error('解析服务请求失败');
  return data;
}
async function operation(path, options) {
  return resolveTask(await engine(path, options), id => engine(`/api/v1/tasks/${encodeURIComponent(id)}`));
}
function issue(url, kind, filename) {
  if (!url) return null;
  const now = Date.now();
  for (const [id, t] of tickets) if (t.expires < now) tickets.delete(id);
  while (tickets.size >= 2000) tickets.delete(tickets.keys().next().value);
  const id = randomBytes(24).toString('hex');
  tickets.set(id, { url, kind, filename, expires: now + 30 * 60000 });
  return `/api/douyin/media/${id}`;
}
function shape(post) {
  if (!post?.content_id || !post.media || post.platform !== 'douyin') throw new Error('解析服务未返回有效抖音作品');
  const id = String(post.content_id);
  const video = post.media.video;
  return { id, description: post.description, created_at: post.created_at, author: post.author?.nickname, stats: post.stats,
    cover: issue(post.media.covers?.[0]?.url, 'image', `${id}-cover.jpg`),
    video: video && video.watermark === false ? issue(video.url, 'video', `${id}.mp4`) : null,
    images: (post.media.images || []).map((im, i) => issue(im.url, 'image', `${id}-${i+1}.jpg`)), web_url: `https://www.douyin.com/video/${id}` };
}
export function publicIPv4(ip) {
  if (net.isIP(ip) !== 4) return false;
  const [a,b] = ip.split('.').map(Number);
  return !(a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && [0,168].includes(b)) || (a === 100 && b >= 64 && b <= 127) || (a === 198 && [18,19,51].includes(b)) || (a === 203 && b === 0));
}
export function mediaHost(host) {
  return ['douyinvod.com','byteimg.com','douyinpic.com','pstatp.com','snssdk.com','douyin.com','iesdouyin.com','ibytedtos.com','bytecdn.cn'].some(h => host === h || host.endsWith(`.${h}`));
}
async function openMedia(raw, range, depth = 0) {
  if (depth > 5) throw new Error('资源跳转次数过多');
  const u = new URL(raw);
  if (u.protocol !== 'https:' || !mediaHost(u.hostname) || u.username || u.password || (u.port && u.port !== '443')) throw new Error('资源地址不受支持');
  const records = await dns.lookup(u.hostname, { all: true, family: 4 });
  if (!records.length || records.some(r => !publicIPv4(r.address))) throw new Error('资源地址无法访问');
  const response = await new Promise((resolve, reject) => {
    const req = https.get(u, { autoSelectFamily: false, family: 4, lookup: (_h, _o, cb) => cb(null, records[0].address, 4), headers: { 'User-Agent': 'Mozilla/5.0', Referer: 'https://www.douyin.com/', ...(range ? { Range: range } : {}) } }, resolve);
    req.setTimeout(20000, () => req.destroy(new Error('资源读取超时')));
    req.on('error', reject);
  });
  if ([301,302,303,307,308].includes(response.statusCode)) {
    response.resume();
    if (!response.headers.location) throw new Error('资源跳转异常');
    return openMedia(new URL(response.headers.location, u).href, range, depth+1);
  }
  return response;
}
function send(res, status, data) { res.writeHead(status, { 'Content-Type':'application/json; charset=utf-8', 'Cache-Control':'no-store' }); res.end(JSON.stringify(data)); }
async function body(req) {
  let buf = '';
  for await (const chunk of req) { buf += chunk; if (Buffer.byteLength(buf) > 16384) throw new Error('输入内容过长'); }
  return JSON.parse(buf || '{}');
}
export const server = http.createServer(async (req,res) => {
  res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Referrer-Policy','no-referrer');
  const u = new URL(req.url, 'http://localhost');
  try {
    if (u.pathname === '/api/douyin/health' && req.method === 'GET') {
      try {
        const h = await engine('/api/v1/health');
        return send(res,200,{ configured: Boolean(key), verified: Boolean(h.last_success), backend: h.engine, mac_required: false, last_success: h.last_success, cooldown_seconds: h.cooldown_seconds });
      } catch { return send(res,503,{configured:false,verified:false,backend:'douk-cloud',mac_required:false,error:'解析服务暂不可用'}); }
    }
    if (u.pathname.startsWith('/api/douyin/media/') && req.method === 'GET') {
      const t = tickets.get(u.pathname.split('/').pop());
      if (!t || t.expires < Date.now()) return send(res,410,{error:'下载链接已过期，请重新解析'});
      if (active >= 4) return send(res,429,{error:'当前下载较多，请稍后重试'});
      active++;
      try {
        const range = req.headers.range;
        if (range && !/^bytes=\d*-\d*$/.test(range)) return send(res,416,{error:'不支持的范围'});
        const upstream = await openMedia(t.url,range);
        const type = String(upstream.headers['content-type'] || '');
        if (![200,206].includes(upstream.statusCode) || !/^(image\/|video\/|application\/octet-stream)/i.test(type)) { upstream.destroy(); throw new Error('资源不可用，请重新解析'); }
        if (Number(upstream.headers['content-length'] || 0) > MAX_BYTES) { upstream.destroy(); throw new Error('文件超过 512MB 下载限制'); }
        let bytes = 0;
        upstream.on('data', c => { bytes += c.length; if (bytes > MAX_BYTES) upstream.destroy(new Error('文件过大')); });
        const headers = { 'Content-Type': type, 'Cache-Control':'private, no-store', 'Content-Disposition': `${u.searchParams.has('download') ? 'attachment' : 'inline'}; filename="${t.filename}"` };
        for (const h of ['content-length','content-range','accept-ranges']) if (upstream.headers[h]) headers[h] = upstream.headers[h];
        res.writeHead(upstream.statusCode,headers);
        res.on('close', () => upstream.destroy());
        await pipeline(upstream,res);
      } finally { active--; }
      return;
    }
    if (u.pathname.startsWith('/api/douyin/')) {
      if (req.method !== 'POST') return send(res,405,{error:'不支持的请求方法'});
      if (!['/api/douyin/parse','/api/douyin/posts','/api/douyin/profile','/api/douyin/comments','/api/douyin/mix'].includes(u.pathname)) return send(res,404,{error:'接口不存在'});
      if (active >= 4) return send(res,429,{error:'当前任务较多，请稍后重试'});
      active++;
      try {
        const b = await body(req);
        if (u.pathname.endsWith('/parse')) {
          const post = await operation('/api/v1/parse',{ method:'POST', body:JSON.stringify({url:extractUrl(b.url)}) });
          return send(res,200,shape(post));
        }
        if (u.pathname.endsWith('/profile')) {
          const target = String(b.target || '').trim();
          const p = new URLSearchParams();
          if (/https?:\/\//.test(target)) p.set('url',extractUrl(target));
          else if (/^MS4wLjAB[A-Za-z0-9_-]{10,250}$/.test(target)) p.set('sec_user_id',target);
          else throw new Error('请提供有效的抖音博主主页链接或 sec_uid');
          const result = await operation(`/api/v1/douyin/user?${p}`);
          return send(res,200,{nickname:result.nickname,signature:result.signature,verified:result.verified,stats:result.stats,web_url:result.web_url,sec_uid:result.sec_uid});
        }
        if (u.pathname.endsWith('/comments')) {
          const id = String(b.id || '');
          if (!/^\d{10,25}$/.test(id)) throw new Error('作品 ID 无效');
          const count = Number(b.count ?? 20);
          if (!Number.isInteger(count)||count<1||count>50) throw new Error('评论数量须为 1 至 50');
          const p = new URLSearchParams({aweme_id:id,count:String(count)});
          if (b.cursor) {if (typeof b.cursor !== 'string'||b.cursor.length>512) throw new Error('评论分页参数无效');p.set('cursor',b.cursor);}
          const result = await operation(`/api/v1/douyin/video/comments?${p}`);
          return send(res,200,{items:result.items||result.comments||[],cursor:result.cursor,has_more:result.has_more});
        }
        if (u.pathname.endsWith('/mix')) {
          const target = String(b.target || b.id || '').trim();
          const p = new URLSearchParams({count:'20'});
          if (/^\d{5,30}$/.test(target)) p.set('mix_id',target);
          else p.set('url',extractUrl(target));
          if(b.cursor){if(typeof b.cursor!=='string'||b.cursor.length>512)throw new Error('分页参数无效');p.set('cursor',b.cursor);}
          const result = await operation(`/api/v1/douyin/mix/posts?${p}`);
          return send(res,200,{items:(result.items||[]).map(shape),cursor:result.cursor,has_more:result.has_more});
        }
        const count = Number(b.count ?? 20);
        if (!Number.isInteger(count) || count < 1 || count > 50) throw new Error('每页作品数须为 1 至 50');
        const p = new URLSearchParams({count:String(count)});
        const target = String(b.target || '').trim();
        if (/https?:\/\//.test(target)) p.set('url',extractUrl(target));
        else if (/^MS4wLjAB[A-Za-z0-9_-]{10,250}$/.test(target)) p.set('sec_user_id',target);
        else throw new Error('请提供抖音主页链接或 sec_uid，暂不支持昵称搜索');
        if (b.cursor) { if (typeof b.cursor !== 'string' || b.cursor.length > 512) throw new Error('分页参数无效'); p.set('cursor',b.cursor); }
        const next = creatorNextRequest.get(target) || 0;
        if (next > Date.now()) { const wait = Math.ceil((next-Date.now())/1000); return send(res,429,{error:`请求过于频繁，请在 ${wait} 秒后继续；已提取的作品不会丢失。`,retry_after_seconds:wait}); }
        creatorNextRequest.set(target,Date.now()+CREATOR_GAP_MS);
        let page;
        try { page = await operation(`/api/v1/douyin/user/posts?${p}`); }
        catch (e) {
          if (/automated traffic|cooled down|风控|频繁|冷却/i.test(String(e.message))) {
            creatorNextRequest.set(target,Date.now()+CREATOR_COOLDOWN_MS);
            return send(res,429,{error:'抖音暂时限制了连续访问，已暂停该账号提取至少 5 分钟；请稍后继续，不会自动重试。',retry_after_seconds:300});
          }
          throw e;
        }
        if (!Array.isArray(page?.items)) throw new Error('作品列表响应异常');
        return send(res,200,{ items:page.items.map(shape), cursor:page.cursor, has_more:page.has_more });
      } finally { active--; }
    }
    if (req.method !== 'GET') return send(res,405,{error:'不支持的请求方法'});
    const files = {'/':'index.html','/douyin-downloader.html':'index.html','/app.js':'app.js','/style.css':'style.css'};
    const file = files[u.pathname];
    if (!file) return send(res,404,{error:'页面不存在'});
    res.writeHead(200,{ 'Content-Type': file.endsWith('.js') ? 'text/javascript; charset=utf-8' : file.endsWith('.css') ? 'text/css; charset=utf-8':'text/html; charset=utf-8', 'Content-Security-Policy': "default-src 'self'; img-src 'self'; media-src 'self'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'", 'Cache-Control':'no-cache' });
    res.end(await readFile(new URL(`./public/${file}`,import.meta.url)));
  } catch (e) {
    if (res.headersSent) res.destroy();
    else send(res,/限制访问/.test(e.message) ? 429 : 502,{error:e.message || '请求失败'});
  }
});
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) server.listen(Number(process.env.PORT || 2033),'127.0.0.1',()=>console.log('Douyin gateway: http://127.0.0.1:'+(process.env.PORT || 2033)));
