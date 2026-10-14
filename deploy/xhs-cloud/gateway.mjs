import http from 'node:http';
import https from 'node:https';
import dns from 'node:dns/promises';
import net from 'node:net';
import { randomBytes } from 'node:crypto';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';

const base = process.env.XHS_ENGINE_URL || 'http://127.0.0.1:2038';
const key = process.env.XHS_API_KEY || '';
const port = Number(process.env.XHS_GATEWAY_PORT || 2039);
const tickets = new Map();
const MAX_BYTES = 512 * 1024 * 1024;
let active = 0;

export function extractUrl(text) {
  const raw = String(text || '').match(/https:\/\/[^\s<>"“”]+/u)?.[0]?.replace(/[，。！？；：、,.!?;:）)\]}]+$/u, '');
  if (!raw) throw new Error('请粘贴小红书作品分享链接或包含链接的分享文案');
  const u = new URL(raw);
  const allowed = ['xiaohongshu.com','www.xiaohongshu.com','xhslink.com','www.xhslink.com','xhslink.cn','www.xhslink.cn'];
  if (u.protocol !== 'https:' || !allowed.includes(u.hostname) || u.username || u.password || (u.port && u.port !== '443')) throw new Error('仅支持小红书 HTTPS 作品链接');
  return u.href;
}

export function publicIPv4(ip) {
  if (net.isIP(ip) !== 4) return false;
  const [a,b,c] = ip.split('.').map(Number);
  return !(a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127) || (a === 198 && [18,19].includes(b)) || (a === 192 && b === 0 && c === 0) || (a === 198 && b === 51 && c === 100) || (a === 203 && b === 0 && c === 113));
}

export function mediaHost(host) {
  return ['xhscdn.com','xiaohongshu.com'].some(root => host === root || host.endsWith(`.${root}`));
}

async function engine(path, options = {}) {
  if (!key) throw new Error('解析服务尚未配置');
  let response;
  try {
    response = await fetch(new URL(path, base), { ...options, headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', ...options.headers }, signal: AbortSignal.timeout(60000) });
  } catch {
    throw new Error('暂时无法连接小红书解析服务');
  }
  let body;
  try { body = await response.json(); } catch { throw new Error('小红书解析服务响应异常'); }
  if (!body?.success) throw new Error(body?.error?.message || '小红书解析失败');
  return body.data;
}

function issue(url, kind, filename) {
  if (!url) return null;
  const parsed = new URL(url);
  if (parsed.protocol !== 'https:' || !mediaHost(parsed.hostname)) return null;
  const now = Date.now();
  for (const [id, item] of tickets) if (item.expires < now) tickets.delete(id);
  while (tickets.size >= 2000) tickets.delete(tickets.keys().next().value);
  const id = randomBytes(24).toString('hex');
  tickets.set(id, { url, kind, filename, expires: now + 30 * 60 * 1000 });
  return `/api/xhs/media/${id}`;
}

function safeName(id, index, suffix) {
  return `xiaohongshu-${String(id).replace(/[^a-z0-9_-]/gi,'').slice(0,40)}${index ? `-${index}` : ''}.${suffix}`;
}

export function shape(post) {
  if (!post || post.platform !== 'xiaohongshu' || !post.id) throw new Error('解析服务未返回有效小红书作品');
  const id = String(post.id);
  return {
    id,
    type: post.video ? 'video' : 'image',
    title: post.title || '',
    description: post.description || '',
    author: post.author || '',
    created_at: post.created_at || null,
    stats: post.stats || {},
    cover: issue(post.cover, 'image', safeName(id, 'cover', 'jpg')),
    video: issue(post.video, 'video', safeName(id, '', 'mp4')),
    images: (post.images || []).map((url, index) => issue(url, 'image', safeName(id, index + 1, 'jpg'))).filter(Boolean),
    web_url: post.web_url,
  };
}

async function openMedia(raw, range, depth = 0) {
  if (depth > 5) throw new Error('资源跳转次数过多');
  const u = new URL(raw);
  if (u.protocol !== 'https:' || !mediaHost(u.hostname) || u.username || u.password || (u.port && u.port !== '443')) throw new Error('资源地址不受支持');
  const records = await dns.lookup(u.hostname, { all: true, family: 4 });
  if (!records.length || records.some(item => !publicIPv4(item.address))) throw new Error('资源地址无法访问');
  const response = await new Promise((resolve, reject) => {
    const req = https.get(u, { autoSelectFamily: false, family: 4, lookup: (_h,_o,cb) => cb(null, records[0].address, 4), headers: { 'User-Agent':'Mozilla/5.0', Referer:'https://www.xiaohongshu.com/', ...(range ? { Range: range } : {}) } }, resolve);
    req.setTimeout(25000, () => req.destroy(new Error('资源读取超时')));
    req.on('error', reject);
  });
  if ([301,302,303,307,308].includes(response.statusCode)) {
    response.resume();
    if (!response.headers.location) throw new Error('资源跳转异常');
    return openMedia(new URL(response.headers.location, u).href, range, depth + 1);
  }
  return response;
}

function send(res, status, data) {
  res.writeHead(status, { 'Content-Type':'application/json; charset=utf-8', 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff' });
  res.end(JSON.stringify(data));
}

async function readBody(req) {
  let value = '';
  for await (const chunk of req) {
    value += chunk;
    if (Buffer.byteLength(value) > 16384) throw new Error('输入内容过长');
  }
  return JSON.parse(value || '{}');
}

export const server = http.createServer(async (req, res) => {
  res.setHeader('Referrer-Policy', 'no-referrer');
  const url = new URL(req.url, 'http://localhost');
  try {
    if (url.pathname === '/api/xhs/health' && req.method === 'GET') {
      try {
        const status = await engine('/health');
        return send(res, 200, { configured:true, verified:Boolean(status.last_success), backend:status.engine, mac_required:false, last_success:status.last_success });
      } catch {
        return send(res, 503, { configured:false, verified:false, backend:'xhs-cloud', mac_required:false, error:'解析服务暂不可用' });
      }
    }
    if (url.pathname.startsWith('/api/xhs/media/') && req.method === 'GET') {
      const ticket = tickets.get(url.pathname.split('/').pop());
      if (!ticket || ticket.expires < Date.now()) return send(res, 410, { error:'下载链接已过期，请重新解析' });
      if (active >= 4) return send(res, 429, { error:'当前下载较多，请稍后重试' });
      active++;
      try {
        const range = req.headers.range;
        if (range && !/^bytes=\d*-\d*$/.test(range)) return send(res, 416, { error:'不支持的范围' });
        const upstream = await openMedia(ticket.url, range);
        const type = String(upstream.headers['content-type'] || 'application/octet-stream');
        if (![200,206].includes(upstream.statusCode) || !/^(image\/|video\/|application\/octet-stream)/i.test(type)) { upstream.destroy(); throw new Error('资源不可用，请重新解析'); }
        if (Number(upstream.headers['content-length'] || 0) > MAX_BYTES) { upstream.destroy(); throw new Error('文件超过 512MB 下载限制'); }
        let bytes = 0;
        upstream.on('data', chunk => { bytes += chunk.length; if (bytes > MAX_BYTES) upstream.destroy(new Error('文件过大')); });
        const headers = { 'Content-Type':type, 'Cache-Control':'private, no-store', 'Content-Disposition':`${url.searchParams.has('download') ? 'attachment' : 'inline'}; filename="${ticket.filename}"` };
        for (const name of ['content-length','content-range','accept-ranges']) if (upstream.headers[name]) headers[name] = upstream.headers[name];
        res.writeHead(upstream.statusCode, headers);
        res.on('close', () => upstream.destroy());
        await pipeline(upstream, res);
      } finally { active--; }
      return;
    }
    if (url.pathname === '/api/xhs/parse') {
      if (req.method !== 'POST') return send(res, 405, { error:'不支持的请求方法' });
      if (active >= 4) return send(res, 429, { error:'当前任务较多，请稍后重试' });
      active++;
      try {
        const body = await readBody(req);
        const result = await engine('/parse', { method:'POST', body:JSON.stringify({ url:extractUrl(body.url) }) });
        return send(res, 200, shape(result));
      } finally { active--; }
    }
    return send(res, 404, { error:'接口不存在' });
  } catch (error) {
    if (res.headersSent) res.destroy();
    else send(res, 502, { error:error?.message || '请求失败' });
  }
});

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) server.listen(port, '127.0.0.1', () => console.log(`XHS gateway: http://127.0.0.1:${port}`));
