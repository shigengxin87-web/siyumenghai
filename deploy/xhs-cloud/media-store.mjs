import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { createHash, createHmac, randomBytes } from 'node:crypto';
import { Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { spawn } from 'node:child_process';

export class Queue {
  constructor(limit, max=120) { this.limit=limit; this.max=max; this.active=0; this.waiting=[]; }
  async run(fn) {
    if (this.active >= this.limit) {
      if (this.waiting.length >= this.max) throw new Error('任务较多，请稍后重试');
      await new Promise(resolve=>this.waiting.push(resolve));
    } else this.active++;
    try { return await fn(); }
    finally { const next=this.waiting.shift(); if(next) next(); else this.active--; }
  }
}
export const sha = value=>createHash('sha256').update(value).digest('hex');
export const root=process.env.XHS_MEDIA_CACHE_DIR || '/var/lib/siyumenghai-xhs-media';
const maxFile=512*1024*1024;
const cacheBudget=Number(process.env.XHS_MEDIA_CACHE_BYTES || 1536*1024*1024);
const ttl=7*86400*1000;
const imageQueue=new Queue(3), videoQueue=new Queue(1), thumbQueue=new Queue(1);
const transfers=new Map(), thumbs=new Map();
export function initStore() { fs.mkdirSync(root,{recursive:true,mode:0o700}); }
export function ticketId(identity,key) { return createHmac('sha256',key).update(identity).digest('hex').slice(0,48); }
export function putTicket(id,ticket) {
  initStore();
  const file=path.join(root,id+'.ticket');
  const temp=file+'.'+randomBytes(4).toString('hex')+'.tmp';
  fs.writeFileSync(temp,JSON.stringify({...ticket,expires:Date.now()+ttl}),{mode:0o600});
  fs.renameSync(temp,file);
}
export async function getTicket(id) {
  if(!/^[a-f0-9]{48}$/.test(id)) throw new Error('资源地址无效');
  try { const t=JSON.parse(await fsp.readFile(path.join(root,id+'.ticket'),'utf8')); if(t.expires<Date.now()) throw new Error(); return t; }
  catch { const e=new Error('作品链接需要更新，请重新解析'); e.status=410; throw e; }
}
export function mediaPath(ticket) { return path.join(root,sha(ticket.url)+'.media'); }
export async function existingMedia(ticket) {
  const file=mediaPath(ticket);
  try {
    const stat=await fsp.stat(file);
    if(Date.now()-stat.mtimeMs>ttl) return null;
    return {file,size:stat.size,type:await sniffType(file,ticket.kind)};
  } catch {return null;}
}
export async function sniffType(file,kind) {
  const fd=await fsp.open(file,'r'); const b=Buffer.alloc(16);
  try { await fd.read(b,0,16,0); } finally {await fd.close();}
  if(b[0]===0xff&&b[1]===0xd8) return 'image/jpeg';
  if(b.subarray(1,4).toString()==='PNG') return 'image/png';
  if(b.subarray(8,12).toString()==='WEBP') return 'image/webp';
  if(b.subarray(4,8).toString()==='ftyp') return kind==='video'?'video/mp4':'image/avif';
  return kind==='video'?'video/mp4':'application/octet-stream';
}
let cleaning;
export async function cleanup() {
  if(cleaning) return cleaning;
  cleaning=(async()=>{
    let size=0; const entries=[]; const now=Date.now();
    for(const name of await fsp.readdir(root)) {
      const file=path.join(root,name); const stat=await fsp.stat(file).catch(()=>null); if(!stat?.isFile())continue;
      if(now-stat.mtimeMs>ttl || (/\.tmp$/.test(name)&&now-stat.mtimeMs>3600000)) {await fsp.unlink(file).catch(()=>{});continue;}
      if(/\.(media|zip|jpg)$/.test(name)) {size+=stat.size; entries.push({file,size:stat.size,time:stat.mtimeMs});}
    }
    for(const entry of entries.sort((a,b)=>a.time-b.time)) {
      if(size<=cacheBudget) break;
      // Never evict a file another request is downloading or packaging.
      if(protectedFiles.has(entry.file)) continue;
      await fsp.unlink(entry.file).catch(()=>{}); size-=entry.size;
    }
  })().finally(()=>{cleaning=null;});return cleaning;
}
export const protectedFiles=new Map();
export function retain(file) {protectedFiles.set(file,(protectedFiles.get(file)||0)+1);return ()=>{const n=protectedFiles.get(file)-1;if(n)protectedFiles.set(file,n);else protectedFiles.delete(file);};}
export async function ensureMedia(ticket,openMedia,onProgress=()=>{}) {
  const cached=await existingMedia(ticket);if(cached)return cached;
  const id=sha(ticket.url);
  if(transfers.has(id)) return transfers.get(id);
  const promise=(ticket.kind==='video'?videoQueue:imageQueue).run(async()=>{
    const again=await existingMedia(ticket);if(again)return again;
    initStore();const file=mediaPath(ticket),temp=file+'.'+randomBytes(4).toString('hex')+'.tmp';
    let last;
    for(let attempt=0;attempt<2;attempt++) {
      try {
        const upstream=await openMedia(ticket.url);
        const type=String(upstream.headers['content-type']||'');
        if(upstream.statusCode!==200 || !/^(image\/|video\/|application\/octet-stream)/i.test(type)) {upstream.destroy();const e=new Error('原文件暂不可用');e.upstream=true;throw e;}
        const total=Number(upstream.headers['content-length']||0);
        if(total>maxFile){upstream.destroy();throw new Error('文件超过512MB限制');}
        let bytes=0;
        const meter=new Transform({transform(chunk,_enc,cb){bytes+=chunk.length;onProgress(bytes,total);if(bytes>maxFile)cb(new Error('文件超过512MB限制'));else cb(null,chunk);}});
        const deadline=setTimeout(()=>upstream.destroy(new Error('文件读取超时，请重试')),180000);
        try{await pipeline(upstream,meter,fs.createWriteStream(temp,{mode:0o600}));}finally{clearTimeout(deadline);}
        if(!bytes)throw new Error('原文件为空');
        await fsp.rename(temp,file);
        return {file,size:bytes,type:await sniffType(file,ticket.kind)};
      } catch(e) {last=e;await fsp.unlink(temp).catch(()=>{});if(e.upstream)break;}
    }
    throw last;
  });transfers.set(id,promise);try{return await promise;}finally{transfers.delete(id);}
}
export async function thumbnail(media) {
  const file=media.file+'.jpg';
  if(fs.existsSync(file))return {file,size:(await fsp.stat(file)).size,type:'image/jpeg'};
  if(!thumbs.has(file))thumbs.set(file,thumbQueue.run(async()=>{
    await new Promise((resolve,reject)=>{
      const child=spawn(process.env.XHS_PYTHON_BIN || '/opt/siyumenghai-xhs-cloud/.venv/bin/python',['-B',new URL('./thumbnail.py',import.meta.url).pathname,media.file,file],{stdio:'ignore'});
      const timer=setTimeout(()=>{child.kill('SIGKILL');reject(new Error('缩略图生成超时'));},15000);
      child.once('error',e=>{clearTimeout(timer);reject(e);});child.once('exit',code=>{clearTimeout(timer);code===0?resolve():reject(new Error('缩略图生成失败'));});
    });return {file,size:(await fsp.stat(file)).size,type:'image/jpeg'};
  }).finally(()=>thumbs.delete(file)));
  return thumbs.get(file);
}
export function byteRange(header,size) {
  if(!header)return null;
  const match=/^bytes=(\d*)-(\d*)$/.exec(header);
  if(!match || (!match[1]&&!match[2]))throw Object.assign(new Error('范围无效'),{status:416});
  let start=match[1]?Number(match[1]):Math.max(0,size-Number(match[2]));
  let end=match[1]?(match[2]?Number(match[2]):size-1):size-1;
  end=Math.min(end,size-1);
  if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>end||start>=size)throw Object.assign(new Error('范围无效'),{status:416});
  return {start,end};
}
export async function serveFile(req,res,media,filename,attachment=false) {
  const range=byteRange(req.headers.range,media.size);
  const release=retain(media.file);
  const headers={'Content-Type':media.type,'Accept-Ranges':'bytes','Cache-Control':'private, max-age=3600',
    'Content-Disposition':`${attachment?'attachment':'inline'}; filename="${filename}"`,'X-Content-Type-Options':'nosniff'};
  if(range)headers['Content-Range']=`bytes ${range.start}-${range.end}/${media.size}`;
  headers['Content-Length']=range?range.end-range.start+1:media.size;
  res.writeHead(range?206:200,headers);
  if(req.method==='HEAD'){res.end();release();return;}
  const stream=fs.createReadStream(media.file,range||{});res.on('close',()=>stream.destroy());
  try{await pipeline(stream,res);}finally{release();}
}
const table=Uint32Array.from({length:256},(_,n)=>{for(let k=0;k<8;k++)n=n&1?0xedb88320^(n>>>1):n>>>1;return n>>>0;});
export function crcUpdate(crc,buf){for(const b of buf)crc=table[(crc^b)&255]^(crc>>>8);return crc>>>0;}
// ZIP Store with data descriptors: stream files instead of buffering a gallery.
export async function makeZip(entries,destination) {
  const temp=destination+'.tmp';const fd=await fsp.open(temp,'w',0o600);let offset=0;const central=[];
  const write=async b=>{let n=0;while(n<b.length){const {bytesWritten}=await fd.write(b,n,b.length-n);n+=bytesWritten;}offset+=b.length;};
  try {
    for(const entry of entries) {
      const name=Buffer.from(entry.name);const local=Buffer.alloc(30);const start=offset;
      local.writeUInt32LE(0x04034b50);local.writeUInt16LE(20,4);local.writeUInt16LE(0x808,6);local.writeUInt16LE(name.length,26);
      await write(local);await write(name);let crc=0xffffffff,size=0;
      for await(const chunk of fs.createReadStream(entry.file)){crc=crcUpdate(crc,chunk);size+=chunk.length;if(offset+chunk.length>maxFile)throw new Error('图集超过512MB打包限制');await write(chunk);}
      crc=(crc^0xffffffff)>>>0;
      const descriptor=Buffer.alloc(16);descriptor.writeUInt32LE(0x08074b50);descriptor.writeUInt32LE(crc,4);descriptor.writeUInt32LE(size,8);descriptor.writeUInt32LE(size,12);await write(descriptor);
      const c=Buffer.alloc(46);c.writeUInt32LE(0x02014b50);c.writeUInt16LE(20,4);c.writeUInt16LE(20,6);c.writeUInt16LE(0x808,8);c.writeUInt32LE(crc,16);c.writeUInt32LE(size,20);c.writeUInt32LE(size,24);c.writeUInt16LE(name.length,28);c.writeUInt32LE(start,42);central.push(Buffer.concat([c,name]));
    }
    const centralStart=offset;for(const c of central)await write(c);
    const end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(entries.length,8);end.writeUInt16LE(entries.length,10);end.writeUInt32LE(offset-centralStart,12);end.writeUInt32LE(centralStart,16);await write(end);
    await fd.close();await fsp.rename(temp,destination);
  }catch(e){await fd.close().catch(()=>{});await fsp.unlink(temp).catch(()=>{});throw e;}
}
