(() => {
  const $=id=>document.getElementById(id);
  const text=v=>v==null?'':String(v),escape=v=>text(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const results=[],downloads=[];const historyKey='siyumenghai-xhs-history-v2',jobsKey='siyumenghai-xhs-jobs-v2';
  let gallery=[],galleryIndex=0,previewKind='',returnFocus,previewSource='';
  const mobileImageSave=()=>/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)||matchMedia('(pointer: coarse)').matches;
  const thumb=url=>url?`${url}?thumb=1`:'';
  const read=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))||fallback;}catch{return fallback;}};
  const write=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value));}catch{}};
  async function api(url,body,timeout=30000) {
    const response=await fetch(url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(timeout)});
    let data;try{data=await response.json();}catch{throw new Error('服务暂时没有响应，请重试');}
    if(!response.ok){const e=new Error(data.error||'暂时无法完成，请重试');e.status=response.status;throw e;}return data;
  }
  function extract(value){return [...new Set((value.match(/https:\/\/[^\s<>"“”]+/gu)||[]).map(u=>u.replace(/[，。！？；：、,.!?;:）)\]}]+$/u,'')).filter(u=>{try{return ['xiaohongshu.com','www.xiaohongshu.com','xhslink.com','www.xhslink.com','xhslink.cn','www.xhslink.cn'].includes(new URL(u).hostname);}catch{return false;}}))].slice(0,20);}
  const metric=(label,value)=>value==null||value===''?'':`<span>${label}<b>${escape(value)}</b></span>`;
  function card(item,i) {
    if(item.kind==='author')return `<article class="author-card"><h2>${escape(item.author?.nickname||'博主')}的最新作品</h2><div class="author-grid">${(item.notes||[]).map(n=>`<button class="author-note" data-note="${escape(n.web_url)}"><img src="${escape(thumb(n.cover))}" loading="lazy" alt=""><span>${escape(n.title||'查看作品')}</span></button>`).join('')}</div></article>`;
    const video=Boolean(item.video),images=item.images||[],cover=video?item.cover:images[0];
    return `<article class="card" data-index="${i}"><div class="visual ${video?'video':'image'}"><button class="cover" data-preview="${i}" data-start="0" aria-label="${video?'播放视频':'预览图片 1'}"><img src="${escape(thumb(cover))}" alt="${escape(item.title)}" decoding="async">${video?'<span class="play" aria-hidden="true">▶</span>':''}<span class="count">${video?'视频':`${images.length} 张图片`}</span></button>${!video&&images.length>1?`<div class="thumbnails">${images.slice(1,5).map((url,n)=>`<button data-preview="${i}" data-start="${n+1}" aria-label="预览图片 ${n+2}"><img src="${escape(thumb(url))}" loading="lazy" alt="第 ${n+2} 张">${n===3&&images.length>5?`<span>+${images.length-4}</span>`:''}</button>`).join('')}</div>`:''}</div><div class="copy"><span class="card-type">${video?'视频作品':'图文作品'}${item.cached?' · 已收录':''}</span><h2>${escape(item.title||'小红书作品')}</h2><p class="author">${escape(item.author||'作者信息未公开')}</p><p class="description">${escape(item.description)}</p><div class="stats">${metric('点赞',item.stats?.liked)}${metric('收藏',item.stats?.collected)}${metric('评论',item.stats?.commented)}${metric('分享',item.stats?.shared)}</div><div class="card-actions"><button class="primary" data-save="${i}">${video?'下载视频':mobileImageSave()?'查看图片并保存':`下载图集 · ${images.length} 张`}</button><button data-preview="${i}" data-start="0">${video?'播放预览':'浏览图集'}</button><a href="${escape(item.web_url)}" target="_blank" rel="noopener noreferrer">原作品 ↗</a></div><p class="media-note">${video?'保存作品视频，支持断点续传':mobileImageSave()?'点击图片查看大图，长按图片保存到相册':'图集打包为一个 ZIP，也可在预览中逐张保存'}</p></div></article>`;
  }
  function addResult(item) {
    const index=results.length;results.push(item);$('results').insertAdjacentHTML('beforeend',card(item,index));
    $('actions').hidden=!results.some(i=>i.kind!=='author');
    if(item.kind!=='author')saveHistory(item);
  }
  function saveHistory(item) {
    const entry={id:item.id,type:item.video?'video':'image',title:item.title||'小红书作品',author:item.author||'',web_url:item.web_url,saved_at:Date.now()};
    write(historyKey,[entry,...read(historyKey,[]).filter(i=>i.id!==entry.id)].slice(0,30));renderHistory();
  }
  function renderHistory(){const history=read(historyKey,[]);$('historyList').innerHTML=history.length?history.map(i=>`<div class="history-row"><div><strong>${escape(i.title)}</strong><small>${i.type==='video'?'视频':'图集'} · ${escape(i.author)} · ${new Date(i.saved_at).toLocaleDateString('zh-CN')}</small></div><button data-history="${escape(i.web_url)}">打开</button></div>`).join(''):'<p class="empty">收集过的作品会出现在这里，随时回来继续保存。</p>';}
  async function parseOne(url,refresh=false){return api('/api/xhs/parse',{url,refresh},70000);}
  $('parseForm').addEventListener('submit',async e=>{
    e.preventDefault();const list=extract($('links').value);if(!list.length){$('status').textContent='没有识别到小红书链接，请粘贴完整的分享链接。';return;}
    const button=e.currentTarget.querySelector('button');button.disabled=true;button.textContent='正在读取…';
    results.length=0;$('results').replaceChildren();$('actions').hidden=true;
    const loading=document.createElement('div');loading.className='skeleton';loading.setAttribute('aria-label','正在读取作品');$('results').append(loading);
    let done=0,failed=0,cursor=0;
    async function worker(){while(cursor<list.length){const i=cursor++;$('status').textContent=`正在收集作品 ${done+failed+1}/${list.length}…`;
      try{const item=await parseOne(list[i]);loading.remove();addResult(item);done++;}
      catch(error){failed++;$('results').insertAdjacentHTML('beforeend',`<div class="parse-error">第 ${i+1} 条：${escape(error.name==='TimeoutError'?'读取超时，请稍后重试':error.message)} <button data-note="${escape(list[i])}">重试</button></div>`);}
      $('status').textContent=`已收集 ${done}/${list.length} 条${failed?`，${failed} 条需要重试`:''}。${done?'点击作品可预览，点击下载可保存原文件。':''}`;
    }}
    try{await Promise.all(Array.from({length:Math.min(2,list.length)},worker));}finally{loading.remove();button.disabled=false;button.innerHTML='解析作品 <span aria-hidden="true">↗</span>';}
  });
  async function openNote(url,button){if(button)button.disabled=true;$('status').textContent='正在读取作品…';try{const item=await parseOne(url);addResult(item);$('status').textContent='已收集，可以预览和保存。';$('results').lastElementChild?.scrollIntoView({behavior:'smooth',block:'start'});}catch(e){$('status').textContent=e.message;}finally{if(button)button.disabled=false;}}
  $('results').addEventListener('error',e=>{if(e.target.tagName==='IMG'){e.target.hidden=true;const parent=e.target.closest('button');if(parent&&!parent.querySelector('.image-error'))parent.insertAdjacentHTML('beforeend','<span class="image-error">点击重新查看</span>');}},true);
  $('results').addEventListener('click',e=>{
    const note=e.target.closest('[data-note]');if(note)return openNote(note.dataset.note,note);
    const preview=e.target.closest('[data-preview]');if(preview)return openPreview(results[Number(preview.dataset.preview)],Number(preview.dataset.start||0));
    const save=e.target.closest('[data-save]');if(save){const i=results[Number(save.dataset.save)];if(!i.video&&mobileImageSave())return openPreview(i);return prepare(i.video?[i.video]:i.images,i.title,i.web_url);}
  });
  function updatePreview(){const url=gallery[galleryIndex],longPress=previewKind==='image'&&mobileImageSave();$('previewSave').hidden=longPress;$('previewOpen').hidden=longPress;$('previewHint').textContent=longPress?'长按图片保存到相册':'原文件保留清晰度';$('galleryCounter').textContent=previewKind==='image'?`${galleryIndex+1} / ${gallery.length}`:'视频';$('galleryPrev').hidden=previewKind!=='image'||galleryIndex===0;$('galleryNext').hidden=previewKind!=='image'||galleryIndex===gallery.length-1;$('previewState').textContent='正在加载…';$('previewOpen').href=url;$('previewSave').textContent=previewKind==='video'?'下载视频':'保存这一张';if(previewKind==='image')$('previewImage').src=url;else $('previewVideo').src=url;}
  function openPreview(item,index=0){returnFocus=document.activeElement;previewKind=item.video?'video':'image';gallery=item.video?[item.video]:(item.images||[]);if(!gallery.length)return;previewSource=item.web_url;galleryIndex=index;$('previewTitle').textContent=item.title||'作品预览';$('previewImage').hidden=previewKind!=='image';$('previewVideo').hidden=previewKind!=='video';$('preview').hidden=false;document.body.style.overflow='hidden';updatePreview();$('previewClose').focus();}
  function closePreview(){$('preview').hidden=true;document.body.style.overflow='';$('previewVideo').pause();$('previewVideo').removeAttribute('src');$('previewVideo').load();$('previewImage').removeAttribute('src');returnFocus?.focus();}
  $('previewImage').addEventListener('load',()=>{$('previewState').textContent='';});$('previewVideo').addEventListener('loadeddata',()=>{$('previewState').textContent='';});
  for(const id of ['previewImage','previewVideo'])$(id).addEventListener('error',()=>{
    if($('preview').hidden)return;
    if(id==='previewVideo'&&!$('previewVideo').src.includes('proxy=1')){
      $('previewVideo').src=gallery[galleryIndex]+'?proxy=1';$('previewState').textContent='正在重新加载视频…';return;
    }
    $('previewState').textContent='预览暂不可用，可以重试或直接保存原文件。';
  });
  $('galleryPrev').onclick=()=>{if(galleryIndex>0){galleryIndex--;updatePreview();}};$('galleryNext').onclick=()=>{if(galleryIndex<gallery.length-1){galleryIndex++;updatePreview();}};
  $('previewClose').onclick=closePreview;$('preview').onclick=e=>{if(e.target===$('preview'))closePreview();};
  document.addEventListener('keydown',e=>{if($('preview').hidden)return;if(e.key==='Escape')closePreview();if(e.key==='ArrowLeft')$('galleryPrev').click();if(e.key==='ArrowRight')$('galleryNext').click();if(e.key==='Tab'){const focus=[...$('preview').querySelectorAll('button:not([hidden]),a')].filter(n=>n.offsetParent!==null),first=focus[0],last=focus.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}});
  $('previewSave').onclick=()=>prepare([gallery[galleryIndex]],$('previewTitle').textContent,previewSource);
  const mb=n=>(n/1048576).toFixed(1)+' MB';
  function persistJobs(){write(jobsKey,downloads.filter(d=>d.id&&d.state!=='failed').slice(-8).map(({id,title,media,source})=>({id,title,media,source})));}
  function renderDownloads(){
    $('downloadList').innerHTML=downloads.map((d,i)=>{let label=d.saving?`正在读取视频 · ${mb(d.networkBytes||0)} / ${mb(d.bytes)}`:d.state==='ready'?`文件已就绪 · ${mb(d.bytes)}${d.auto?' · 已发起浏览器下载':''}`:d.state==='failed'?d.error:`正在准备 ${d.done||0}/${d.total||d.media?.length||1} 个文件${d.file_total?` · ${mb(d.file_bytes||0)} / ${mb(d.file_total)}`:''}`;
      return `<div class="download-row"><div class="download-title">${escape(d.title||'作品文件')}</div><p class="download-state">${escape(label)}</p>${!['ready','failed'].includes(d.state)?`<progress ${d.total?`value="${(d.done||0)+(d.file_total?(d.file_bytes||0)/d.file_total:0)}" max="${d.total}"`:''}></progress>`:''}${d.state==='ready'?`<a class="primary" data-download="${i}" href="${escape(d.download)}" download="${escape(d.filename)}">${d.auto?'再次下载':'下载文件'}</a>${navigator.share&&navigator.canShare?`<button data-share="${i}">分享 / 存储</button>`:''}`:d.state==='failed'?`<button data-retry="${i}">重新准备</button>`:''}</div>`;}).join('');
  }
  async function triggerDownload(d){
    if(d.saving)return;
    let downloadUrl=d.download,objectUrl='';
    d.saving=true;d.networkBytes=0;renderDownloads();
    try {
      if(d.direct&&d.bytes<=64*1048576){
        const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),12000);
        try {
          const response=await fetch(d.direct,{mode:'cors',credentials:'omit',referrerPolicy:'no-referrer',signal:controller.signal});
          if(!response.ok||!response.body)throw new Error('retry');
          const length=Number(response.headers.get('Content-Length')||0);if(length>64*1048576)throw new Error('retry');
          const reader=response.body.getReader(),chunks=[];let bytes=0,last=0;
          try {while(true){const {done,value}=await reader.read();if(done)break;bytes+=value.length;
            if(bytes>64*1048576)throw new Error('retry');chunks.push(value);d.networkBytes=bytes;
            if(Date.now()-last>200){renderDownloads();last=Date.now();}
          }}finally{reader.releaseLock();}
          if(bytes!==d.bytes)throw new Error('retry');
          objectUrl=URL.createObjectURL(new Blob(chunks,{type:'video/mp4'}));downloadUrl=objectUrl;d.fast=true;
        }catch { /* Standard same-origin download remains available. */ }
        finally{clearTimeout(timer);controller.abort();}
      }
      const a=document.createElement('a');a.href=downloadUrl;a.download=d.filename;document.body.append(a);a.click();a.remove();d.auto=true;
      if(objectUrl)setTimeout(()=>URL.revokeObjectURL(objectUrl),60000);
    }finally{d.saving=false;renderDownloads();}
  }
  async function poll(d,auto=false){try{while(true){const state=await api(`/api/xhs/jobs/${d.id}`);Object.assign(d,state);renderDownloads();persistJobs();if(d.state==='ready'){if(auto)triggerDownload(d);return;}if(d.state==='failed')return;await new Promise(r=>setTimeout(r,1500));}}catch(e){d.state='failed';d.error=e.message;renderDownloads();}}
  async function prepare(media,title,source){
    const existing=downloads.find(d=>d.media?.join()===media.join()&&d.state!=='failed');$('downloads').hidden=false;
    if(existing){if(existing.state==='ready')triggerDownload(existing);return;}
    const d={title,media,source,state:'preparing',done:0,total:media.length};downloads.push(d);renderDownloads();
    try{Object.assign(d,await api('/api/xhs/jobs',{media}));persistJobs();renderDownloads();if(d.state==='ready')triggerDownload(d);else await poll(d,true);}
    catch(e){d.state='failed';d.error=e.message;renderDownloads();}
  }
  $('downloadList').onclick=async e=>{
    const download=e.target.closest('[data-download]');if(download){e.preventDefault();return triggerDownload(downloads[Number(download.dataset.download)]);}
    const retry=e.target.closest('[data-retry]');if(retry){const i=Number(retry.dataset.retry),d=downloads[i];downloads.splice(i,1);try{await parseOne(d.source);await prepare(d.media,d.title,d.source);}catch(err){$('status').textContent=err.message;}return;}
    const share=e.target.closest('[data-share]');if(share){const d=downloads[Number(share.dataset.share)];share.disabled=true;share.textContent='读取文件…';try{
      if((d.file_total||d.bytes)>100*1048576)throw new Error('大文件请使用下载文件，再从文件应用分享');
      const r=await fetch(d.download);if(!r.ok)throw new Error('文件已过期，请重新准备');const file=new File([await r.blob()],d.filename,{type:r.headers.get('Content-Type')||'application/octet-stream'});
      if(!navigator.canShare({files:[file]}))throw new Error('当前浏览器不支持分享此文件，请使用下载文件');
      // A second real tap preserves user activation even after a large fetch.
      share.disabled=false;share.textContent='点击选择存储位置';share.onclick=async ev=>{ev.stopPropagation();try{await navigator.share({files:[file],title:d.title});}catch(err){if(err.name!=='AbortError')$('status').textContent='请使用下载文件保存。';}};
    }catch(err){$('status').textContent=err.message;share.textContent='分享 / 存储';share.disabled=false;}}
  };
  $('downloadClose').onclick=()=>{$('downloads').hidden=true;};
  $('historyList').onclick=e=>{const b=e.target.closest('[data-history]');if(b){$('links').value=b.dataset.history;openNote(b.dataset.history,b);}};
  $('clearHistory').onclick=()=>{write(historyKey,[]);renderHistory();};
  function exportFile(name,type,value){const url=URL.createObjectURL(new Blob([value],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
  $('exportJson').onclick=()=>exportFile('小红书作品.json','application/json;charset=utf-8',JSON.stringify(results,null,2));
  $('exportCsv').onclick=()=>{const q=v=>`"${text(v).replace(/"/g,'""')}"`;const safe=v=>/^[=+\-@\t\r]/.test(text(v))?'\''+text(v):v;const rows=[['作品ID','标题','作者','类型','点赞','收藏','评论','分享','作品链接'],...results.filter(i=>i.kind!=='author').map(i=>[i.id,i.title,i.author,i.type,i.stats?.liked,i.stats?.collected,i.stats?.commented,i.stats?.shared,i.web_url])];exportFile('小红书作品.csv','text/csv;charset=utf-8','\ufeff'+rows.map(r=>r.map(v=>q(safe(v))).join(',')).join('\r\n'));};
  if(!localStorage.getItem(historyKey)){
    const old=read('siyumenghai-xhs-history-v1',[]);
    write(historyKey,old.filter(i=>i.id&&i.web_url).map(({id,type,title,author,web_url,saved_at})=>({id,type,title,author,web_url,saved_at})));
  }
  renderHistory();
  for(const d of read(jobsKey,[]).slice(-8)){downloads.push({...d,state:'preparing'});void poll(downloads.at(-1));}
})();
