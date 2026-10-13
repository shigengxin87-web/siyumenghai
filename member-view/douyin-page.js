const $ = id => document.getElementById(id);
let posts = [], cursor = null, target = '', stopped = false, busy = false;
const CREATOR_PAGE_GAP_MS = 15000;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function status(text) { $('status').textContent = text; }
function setBusy(value) { busy = value; document.querySelectorAll('form button, #more, #all, [role=tab]').forEach(b=>b.disabled=value); $('stop').hidden=!value; }
async function api(path,body) {
  const response = await fetch(`/api/douyin/${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(120000)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败');
  return result;
}
function node(tag,text,cls) { const el=document.createElement(tag); if(text != null) el.textContent=text; if(cls) el.className=cls; return el; }
function link(text,url,download=false) { const a=node('a',text); a.href=url+(download?'?download=1':''); if(download) a.download=''; else {a.target='_blank';a.rel='noopener noreferrer';} return a; }
function add(post) {
  if(posts.some(p=>p.id===post.id))return;
  posts.push(post);
  const card=node('article',null,'card');
  card.append(node('h2',post.description || '未提供文案'));
  card.append(node('p',`${post.author || '未提供作者'} · ${post.created_at ? new Date(post.created_at).toLocaleString('zh-CN') : '未提供发布时间'}`,'meta'));
  const stats=post.stats || {}; card.append(node('p',`点赞 ${stats.digg_count ?? '—'}　评论 ${stats.comment_count ?? '—'}　转发 ${stats.share_count ?? '—'}　收藏 ${stats.collect_count ?? '—'}`,'stats'));
  if(post.cover){ const img=node('img');img.src=post.cover;img.alt='作品封面';img.loading='lazy';card.append(img,link('保存封面',post.cover,true)); }
  if(post.video){const v=node('video');v.src=post.video;v.controls=true;v.preload='none';v.setAttribute('playsinline','');card.append(v,link('下载无水印视频',post.video,true));}
  if(post.images?.length){const gallery=node('div',null,'gallery');post.images.forEach((url,i)=>{const fig=node('figure');const img=node('img');img.src=url;img.alt=`图集第 ${i+1} 张`;img.loading='lazy';fig.append(img,link(`保存图片 ${i+1}`,url,true));gallery.append(fig);});card.append(gallery);}
  if(!post.video&&!post.images?.length)card.append(node('p','当前作品未返回可下载资源','error'));
  const commentsButton=node('button','查看前 20 条评论');
  const commentsArea=node('div',null,'comments');
  commentsButton.onclick=async()=>{commentsButton.disabled=true;commentsArea.textContent='正在读取评论…';try{const data=await api('comments',{id:post.id,count:20});commentsArea.replaceChildren();if(!data.items?.length)commentsArea.textContent='暂无可展示评论';for(const c of data.items||[]){const name=c.user?.nickname||c.author?.nickname||'用户';commentsArea.append(node('p',`${name}：${c.text||c.content||''}`));}if(data.has_more)commentsArea.append(node('small','仅展示前 20 条评论'));}catch(e){commentsArea.textContent=`评论暂不可用：${e.message}`;}finally{commentsButton.disabled=false;}};
  card.append(commentsButton,commentsArea,link('查看原作品',post.web_url));$('results').append(card);
  $('actions').hidden=false;
}
function reset(){posts=[];cursor=null;$('results').replaceChildren();$('actions').hidden=true;}
function paging(hasMore){$('more').hidden=!hasMore;$('all').hidden=!hasMore;}
const modes=[['singleTab','single'],['creatorTab','creator'],['mixTab','mix']];
for(const [tab,panel] of modes) $(tab).onclick=()=>{if(busy)return;for(const [t,p]of modes){$(t).setAttribute('aria-selected',String(t===tab));$(p).hidden=p!==panel;}cursor=null;paging(false);};
$('single').onsubmit=async e=>{e.preventDefault();if(busy)return;const lines=$('links').value.split('\n').map(s=>s.trim()).filter(Boolean);if(lines.length>20){status('每次最多解析 20 条，请分批提交');return;}reset();paging(false);setBusy(true);stopped=false;let success=0;const errors=[];try{for(let i=0;i<lines.length&&!stopped;i++){status(`正在解析 ${i+1}/${lines.length}…`);try{add(await api('parse',{url:lines[i]}));success++;}catch(e){errors.push(`第 ${i+1} 条：${e.message}`);}}status(`${stopped?'已停止。':''}成功 ${success}/${lines.length} 条${errors.length?'\n'+errors.join('\n'):''}`);}finally{setBusy(false);}};
async function page(){const result=await api('posts',{target,count:Number($('count').value),cursor});if(result.has_more&&(!result.cursor||result.cursor===cursor))throw new Error('分页游标未推进，已停止提取');result.items.forEach(add);cursor=result.has_more?result.cursor:null;paging(Boolean(cursor));status(`已提取 ${posts.length} 条${cursor?'，还有更多作品':'，已到末页'}`);}
$('creator').onsubmit=async e=>{e.preventDefault();if(busy)return;reset();target=$('target').value.trim();setBusy(true);status('正在提取作品…');try{await page();}catch(e){status(e.message);}finally{setBusy(false);}};
$('profileButton').onclick=async()=>{if(busy)return;setBusy(true);status('正在查询公开博主资料…');try{const data=await api('profile',{target:$('target').value.trim()});const card=node('article',null,'card');card.append(node('h2',data.nickname||'未提供昵称'));card.append(node('p',data.signature||'暂无简介'));const s=data.stats||{};card.append(node('p',`粉丝 ${s.follower_count??'—'} · 作品 ${s.content_count??'—'} · 累计获赞 ${s.total_digg??'—'}`));if(data.web_url)card.append(link('查看博主主页',data.web_url));$('results').prepend(card);status('已展示公开博主资料');}catch(e){status(`博主资料暂不可用：${e.message}`);}finally{setBusy(false);}};
$('mix').onsubmit=async e=>{e.preventDefault();if(busy)return;setBusy(true);status('正在识别合集并提取作品…');try{const data=await api('mix',{target:$('mixTarget').value.trim()});reset();(data.items||[]).forEach(add);status(`合集本次提取 ${data.items?.length||0} 条${data.has_more?'；仍有更多作品，当前先展示这一页':'，已到末页'}`);}catch(e){status(`合集提取暂不可用：${e.message}`);}finally{setBusy(false);}};
$('more').onclick=async()=>{if(busy||!cursor)return;setBusy(true);try{await page();}catch(e){status(e.message);}finally{setBusy(false);}};
$('all').onclick=async()=>{if(busy||!cursor)return;setBusy(true);stopped=false;try{let pages=0;while(cursor&&!stopped&&pages++<100){status(`已保存 ${posts.length} 条，等待下一页…`);await sleep(CREATOR_PAGE_GAP_MS);if(stopped)break;await page();}if(stopped)status(`已停止，保留 ${posts.length} 条；可继续加载`);else if(cursor)status(`已提取 ${posts.length} 条；单次最多连续 100 页，可再次继续`);}catch(e){status(`提取暂停：${e.message} 已保留 ${posts.length} 条和分页位置，请等待平台恢复后再继续。`);}finally{setBusy(false);}};
$('stop').onclick=()=>{stopped=true;status('将在当前请求结束后停止');};
$('export').onclick=()=>{const blob=new Blob([JSON.stringify(posts,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=link('导出',url);a.download='抖音作品信息.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('exportCsv').onclick=()=>{const rows=[['作品ID','作者','标题文案','发布时间','点赞','评论','转发','收藏','原作品链接']];for(const p of posts){const s=p.stats||{};rows.push([p.id,p.author,p.description,p.created_at,s.digg_count,s.comment_count,s.share_count,s.collect_count,p.web_url]);}const escape=v=>'"'+String(v??'').replace(/"/g,'""')+'"';const csv='\uFEFF'+rows.map(row=>row.map(escape).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=link('导出',url);a.download='抖音作品信息.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
fetch('/api/douyin/health').then(r=>r.json()).then(h=>{if(!h.configured)status('服务尚未配置，暂时无法解析。');}).catch(()=>status('服务暂时无法连接'));
