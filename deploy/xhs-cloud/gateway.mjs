import http from 'node:http';
import https from 'node:https';
import dns from 'node:dns/promises';
import net from 'node:net';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';
import { Queue, root, ticketId, putTicket, getTicket, ensureMedia, existingMedia,
  thumbnail, serveFile, makeZip, cleanup, retain, sha, initStore } from './media-store.mjs';
const base=process.env.XHS_ENGINE_URL || 'http://127.0.0.1:2038';
const key=process.env.XHS_API_KEY || '';
const port=Number(process.env.XHS_GATEWAY_PORT || 2039);
const parses=new Queue(2,40), streams=new Queue(4,80), packs=new Queue(1,12);
const parsing=new Map(), jobs=new Map(), jobKeys=new Map();
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

function send(res,status,data) {
  res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(data));
}
async function readBody(req) {
  let value='';for await(const c of req){value+=c;if(Buffer.byteLength(value)>16384)throw new Error('输入内容过长');}return JSON.parse(value||'{}');
}
async function engine(url,refresh=false) {
  const identity=(url.match(/\/(?:explore|discovery\/item)\/([a-f0-9]+)/i)?.[1]||url)+(refresh?':refresh':'');
  if(parsing.has(identity))return parsing.get(identity);
  if(!key)throw new Error('解析服务尚未配置');
  const promise=parses.run(async()=>{
    const r=await fetch(new URL('/parse',base),{method:'POST',headers:{Authorization:`Bearer ${key}`,'Content-Type':'application/json'},body:JSON.stringify({url,refresh}),signal:AbortSignal.timeout(55000)});
    const b=await r.json();if(!r.ok||!b.success)throw new Error(b?.error?.message||'暂时无法读取作品');return b.data;
  });parsing.set(identity,promise);try{return await promise;}finally{parsing.delete(identity);}
}
function safeName(id,index,suffix) {return `xiaohongshu-${String(id).replace(/[^a-z0-9_-]/gi,'').slice(0,40)}${index?'-'+index:''}.${suffix}`;}
function issue(url,kind,id,role,webUrl) {
  if(!url)return null;const parsed=new URL(url);if(parsed.protocol!=='https:'||!mediaHost(parsed.hostname))return null;
  const token=ticketId(`${id}:${role}`,key);
  putTicket(token,{url,kind,id,role,web_url:webUrl,filename:safeName(id,role==='video'?'':role,kind==='video'?'mp4':'jpg')});
  return `/api/xhs/media/${token}`;
}
export function shape(post) {
  if(post?.platform!=='xiaohongshu')throw new Error('解析服务未返回有效小红书内容');
  if(post.kind==='author')return {kind:'author',cached:Boolean(post.cached),author:post.author,notes:(post.notes||[]).filter(n=>n.id).map(n=>({...n,cover:issue(n.cover,'image',n.id,'cover',n.web_url)}))};
  if(!post.id)throw new Error('作品信息不完整');
  const id=String(post.id),web=post.web_url;
  return {kind:'note',id,type:post.video?'video':'image',title:post.title||'',description:post.description||'',author:post.author||'',
    created_at:post.created_at||null,duration:post.duration||null,cached:Boolean(post.cached),stats:post.stats||{},
    cover:issue(post.cover,'image',id,'cover',web),video:issue(post.video,'video',id,'video',web),
    images:(post.images||[]).map((u,i)=>issue(u,'image',id,String(i+1),web)).filter(Boolean),web_url:web};
}
async function refreshTicket(id,ticket) {
  if(!ticket.web_url)throw new Error('请重新解析作品');
  shape(await engine(extractUrl(ticket.web_url),true));return getTicket(id);
}
async function asset(id,onProgress) {
  let t=await getTicket(id);
  try{return {ticket:t,media:await ensureMedia(t,openMedia,onProgress)};}
  catch(e){if(!e.upstream)throw e;t=await refreshTicket(id,t);return {ticket:t,media:await ensureMedia(t,openMedia,onProgress)};}
}
function viewJob(job) {return {id:job.id,state:job.state,done:job.done,total:job.total,bytes:job.bytes,file_bytes:job.file_bytes||0,
  file_total:job.file_total||0,error:job.error||'',download:job.state==='ready'?`/api/xhs/files/${job.id}`:null,filename:job.filename||'',expires:job.expires};}
async function startJob(ids) {
  const tickets=await Promise.all(ids.map(getTicket));
  const identity=sha(ids.map((id,i)=>id+':'+tickets[i].url).join(',')),existingId=jobKeys.get(identity);const previous=jobs.get(existingId);
  if(previous&&previous.expires>Date.now()&&previous.state!=='failed'&&(previous.state!=='ready'||fs.existsSync(previous.file)))return previous;
  if([...jobs.values()].filter(j=>j.state==='preparing').length>=12)throw new Error('下载任务较多，请稍后重试');
  if(ids.length>1&&tickets.some(t=>t.kind!=='image'||t.id!==tickets[0].id))throw new Error('请按作品打包图片');
  const job={id:randomBytes(24).toString('hex'),state:'preparing',done:0,total:ids.length,bytes:0,expires:Date.now()+86400000};
  jobs.set(job.id,job);jobKeys.set(identity,job.id);
  void packs.run(async()=>{
    const files=[],releases=[];
    try {
      for(const id of ids) {
        job.file_bytes=0;job.file_total=0;
        const item=await asset(id,(b,t)=>{job.file_bytes=b;job.file_total=t;});
        releases.push(retain(item.media.file));files.push(item);job.done++;job.bytes+=item.media.size;
        if(job.bytes>512*1024*1024)throw new Error('图集超过512MB打包限制');
      }
      if(files.length===1){job.file=files[0].media.file;job.type=files[0].media.type;job.filename=files[0].ticket.filename.replace(/\.jpg$/, ({"image/png":".png","image/webp":".webp","image/avif":".avif"}[files[0].media.type]||".jpg"));}
      else {
        job.file=path.join(root,job.id+'.zip');job.filename=safeName(tickets[0].id,'images','zip');job.type='application/zip';
        const extension=type=>({'image/jpeg':'jpg','image/png':'png','image/webp':'webp','image/avif':'avif'}[type]||'jpg');
        await makeZip(files.map((f,i)=>({file:f.media.file,name:`${String(i+1).padStart(2,'0')}.${extension(f.media.type)}`})),job.file);
      }
      job.size=(await fsp.stat(job.file)).size;job.state='ready';
      await fsp.writeFile(path.join(root,job.id+'.job'),JSON.stringify(job),{mode:0o600});
    }catch(e){job.state='failed';job.error=e?.message||'文件准备失败，请重试';}
    finally{releases.forEach(release=>release());await cleanup().catch(()=>{});}
  }).catch(e=>{job.state='failed';job.error=e.message;});
  return job;
}
async function readJob(id) {
  if(!/^[a-f0-9]{48}$/.test(id))return null;
  let job=jobs.get(id);
  if(!job)try{job=JSON.parse(await fsp.readFile(path.join(root,id+'.job'),'utf8'));}catch{}
  if(!job||job.expires<Date.now())return null;
  if(job.state==='ready'&&!fs.existsSync(job.file))return null;
  return job;
}
export const server=http.createServer(async(req,res)=>{
  res.setHeader('Referrer-Policy','no-referrer');
  const u=new URL(req.url,'http://localhost');
  try {
    if(u.pathname==='/api/xhs/health') {
      const r=await fetch(new URL('/health',base),{headers:{Authorization:`Bearer ${key}`},signal:AbortSignal.timeout(5000)});const b=await r.json();
      return send(res,r.ok?200:503,{configured:r.ok,verified:Boolean(b.data?.last_success),backend:'xhs-cloud',mac_required:false,version:2});
    }
    if(u.pathname==='/api/xhs/parse'&&req.method==='POST') {
      const b=await readBody(req),started=Date.now();const result=shape(await engine(extractUrl(b.url),b.refresh===true));
      return send(res,200,{...result,elapsed_ms:Date.now()-started});
    }
    if(u.pathname==='/api/xhs/jobs'&&req.method==='POST') {
      const b=await readBody(req);if(!Array.isArray(b.media)||b.media.length<1||b.media.length>100)throw new Error('请选择要保存的文件');
      const ids=[...new Set(b.media.map(url=>{const match=/^\/api\/xhs\/media\/([a-f0-9]{48})$/.exec(url);if(!match)throw new Error('资源地址无效');return match[1];}))];
      return send(res,202,viewJob(await startJob(ids)));
    }
    if(u.pathname.startsWith('/api/xhs/jobs/')&&req.method==='GET') {
      const j=await readJob(u.pathname.split('/').pop());return send(res,j?200:410,j?viewJob(j):{error:'下载任务已过期，请重新点击保存'});
    }
    if(u.pathname.startsWith('/api/xhs/files/')&&['GET','HEAD'].includes(req.method)) {
      const j=await readJob(u.pathname.split('/').pop());if(!j||j.state!=='ready')return send(res,410,{error:'文件尚未就绪或已过期，请重新保存'});
      return await serveFile(req,res,{file:j.file,size:j.size,type:j.type},j.filename,true);
    }
    if(u.pathname.startsWith('/api/xhs/media/')&&['GET','HEAD'].includes(req.method)) {
      const id=u.pathname.split('/').pop();let ticket=await getTicket(id);const cached=await existingMedia(ticket);
      if(ticket.kind==='video'&&!cached&&!u.searchParams.has('download')) {
        // A cold preview streams immediately. Full downloads use a separate,
        // resumable preparation task and become reusable local files.
        return await streams.run(async()=>{
          if(res.destroyed)return;
          const range=req.headers.range;if(range&&!/^bytes=\d*-\d*$/.test(range))return send(res,416,{error:'范围无效'});
          let upstream=await openMedia(ticket.url,range);
          if(![200,206].includes(upstream.statusCode)){upstream.destroy();ticket=await refreshTicket(id,ticket);upstream=await openMedia(ticket.url,range);}
          if(![200,206].includes(upstream.statusCode)||!/^(video\/|application\/octet-stream)/i.test(String(upstream.headers['content-type']||''))){upstream.destroy();throw new Error('视频暂不可用，请重试');}
          const length=Number(upstream.headers['content-length']||0);if(length>512*1024*1024){upstream.destroy();throw new Error('文件超过512MB限制');}
          const headers={'Content-Type':'video/mp4','Cache-Control':'private, max-age=300','Accept-Ranges':'bytes','Content-Disposition':`inline; filename="${ticket.filename}"`};
          for(const n of ['content-length','content-range'])if(upstream.headers[n])headers[n]=upstream.headers[n];
          res.writeHead(upstream.statusCode,headers);res.on('close',()=>upstream.destroy());
          if(req.method==='HEAD'){upstream.destroy();res.end();return;}await pipeline(upstream,res);
        });
      }
      const found=cached?{ticket,media:cached}:await asset(id);
      const media=u.searchParams.has('thumb')&&ticket.kind==='image'?await thumbnail(found.media):found.media;
      return await serveFile(req,res,media,found.ticket.filename,u.searchParams.has('download'));
    }
    return send(res,404,{error:'接口不存在'});
  } catch(e) {
    if(res.headersSent)res.destroy();else send(res,e.status||502,{error:e.message||'服务暂不可用，请重试'});
  }
});
if(process.argv[1]&&fileURLToPath(import.meta.url)===process.argv[1]) {
  initStore();server.requestTimeout=120000;server.listen(port,'127.0.0.1');
  const timer=setInterval(()=>{for(const [id,j]of jobs)if(j.expires<Date.now()){jobs.delete(id);for(const[k,v]of jobKeys)if(v===id)jobKeys.delete(k);}void cleanup().catch(()=>{});},600000);timer.unref();
  void cleanup().catch(()=>{});
}
