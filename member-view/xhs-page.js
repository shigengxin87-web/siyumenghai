(() => {
  const $ = id => document.getElementById(id);
  const form = $('parseForm'), input = $('links'), status = $('status'), resultsNode = $('results'), actions = $('actions'), historyList = $('historyList');
  const previewImageEl = $('previewImage'), previewVideoEl = $('previewVideo');
  const historyKey = 'siyumenghai-xhs-history-v1';
  const isMobile = matchMedia('(max-width: 720px)').matches || /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent);
  let results = [], previewUrl = '', previewKind = '', previewUrls = [], previewIndex = 0;
  // Device-tuned copy: desktop never mentions phones, mobile never mentions desktops.
  if (isMobile) {
    $('previewHint').textContent = '点“保存”调起系统分享，可选“存储到照片”；也可以打开原文件后长按画面保存。';
    $('previewSave').textContent = '保存';
  }
  const text = value => value == null ? '' : String(value);
  const escape = value => text(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function urls(value) {
    const found = text(value).match(/https:\/\/[^\s<>"“”]+/gu) || [];
    return [...new Set(found.map(item => item.replace(/[，。！？；：、,.!?;:）)\]}]+$/u, '')).filter(item => /(?:xiaohongshu\.com|xhslink\.(?:com|cn))/i.test(item)))].slice(0, 20);
  }
  async function parse(url) {
    const response = await fetch('/api/xhs/parse', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({url})});
    let body;
    try { body = await response.json(); } catch { throw new Error('解析服务响应异常'); }
    if (!response.ok) throw new Error(body.error || '解析失败');
    return body;
  }
  const metric = (label, value) => value == null || value === '' ? '' : `<span>${label} ${escape(value)}</span>`;
  function mediaButton(item, url, kind, index) {
    const image = kind === 'video' ? item.cover : url;
    return `<button class="media-button" type="button" data-preview="${escape(url)}" data-kind="${kind}" data-gallery-index="${kind === 'image' ? index : ''}" aria-label="预览${kind === 'video' ? '视频' : `图片 ${index + 1}`}"><img src="${escape(image || '')}" alt="${escape(item.title || item.description || '作品媒体')}">${kind === 'video' ? '<span class="play">▶</span>' : ''}</button>`;
  }
  function card(item, index) {
    const media = item.video ? mediaButton(item, item.video, 'video', 0) : item.images.map((url, i) => mediaButton(item, url, 'image', i)).join('');
    const badge = item.cached ? '<span class="cache-badge">秒开缓存</span>' : '';
    const actions = item.video
      ? `<button class="primary save-direct" type="button" data-save-direct="${escape(item.video)}" data-kind="video">保存视频</button><button type="button" data-preview="${escape(item.video)}" data-kind="video">预览播放</button><a href="${escape(item.web_url)}" target="_blank" rel="noopener noreferrer">查看原作品</a>`
      : `<button class="primary" type="button" data-preview-gallery="${index}" data-start="0">预览图集</button><button type="button" data-save-all="${index}">保存全部 ${item.images.length} 张</button><a href="${escape(item.web_url)}" target="_blank" rel="noopener noreferrer">查看原作品</a>`;
    return `<article class="xhs-card ${item.video ? 'is-video' : ''}" data-index="${index}"><div class="card-body"><div class="media-grid ${item.video ? 'is-single' : ''}">${media}</div><div class="card-copy"><div class="eyebrow-row">${badge}<span class="card-eyebrow">${item.video ? '视频作品' : `图集 · ${item.images.length} 张`}</span></div><h2>${escape(item.title || item.description || '小红书作品')}</h2><p class="author">${escape(item.author || '作者信息未公开')}</p><p class="description">${escape(item.description)}</p><div class="stats">${metric('点赞', item.stats?.liked)}${metric('收藏', item.stats?.collected)}${metric('评论', item.stats?.commented)}${metric('分享', item.stats?.shared)}</div><div class="card-actions">${actions}</div></div></div></article>`;
  }
  function authorCard(author) {
    const notes = author.notes || [];
    const grid = notes.map(note => `<button class="author-note" type="button" data-author-note="${escape(note.web_url)}"><img src="${escape(note.cover || '')}" alt=""><span class="author-note-type">${note.type === 'video' ? '视频' : '图'}</span><span class="author-note-title">${escape(note.title || '无标题作品')}</span></button>`).join('');
    return `<article class="author-card"><header><strong>@${escape(author.author?.nickname || '博主')}</strong><small>${notes.length} 条最新作品${author.cached ? ' · 缓存秒开' : ''}，点击任意一条即可解析下载</small></header><div class="author-grid">${grid || '<p class="history-empty">没有取到作品列表</p>'}</div></article>`;
  }
  function render() {
    resultsNode.innerHTML = results.map((item, index) => item.kind === 'author' ? authorCard(item) : card(item, index)).join('');
    actions.hidden = !results.some(item => item.kind !== 'author');
  }
  function getHistory() { try { return JSON.parse(localStorage.getItem(historyKey) || '[]'); } catch { return []; } }
  function saveHistory(item) {
    const entry = {id:item.id,type:item.type || (item.video ? 'video' : 'image'),title:item.title || item.description || '小红书作品',author:item.author || '',cover:item.cover || item.images?.[0] || '',web_url:item.web_url,saved_at:new Date().toISOString()};
    localStorage.setItem(historyKey, JSON.stringify([entry, ...getHistory().filter(old => old.id !== entry.id)].slice(0, 30)));
    renderHistory();
  }
  function renderHistory() {
    const items = getHistory();
    historyList.innerHTML = items.length ? items.map(item => `<div class="history-item"><img src="${escape(item.cover)}" alt=""><div><strong>${escape(item.title)}</strong><small>${item.type === 'video' ? '视频' : '图集'} · ${escape(item.author)} · ${new Date(item.saved_at).toLocaleString('zh-CN')}</small></div><button type="button" data-history-url="${escape(item.web_url)}">再次查询</button></div>`).join('') : '<div class="history-empty">还没有查询记录</div>';
  }
  function showGalleryImage() {
    const url = previewUrls[previewIndex];
    previewImageEl.src = url;
    previewUrl = url;
    $('galleryCounter').hidden = previewUrls.length <= 1;
    $('galleryCounter').textContent = `${previewIndex + 1} / ${previewUrls.length}`;
    $('galleryPrev').hidden = previewIndex === 0;
    $('galleryNext').hidden = previewIndex === previewUrls.length - 1;
  }
  function openPreview(url, kind) {
    if (!url) return;
    previewUrls = []; previewIndex = 0;
    previewUrl = url; previewKind = kind;
    previewImageEl.hidden = kind !== 'image'; previewVideoEl.hidden = kind !== 'video';
    $('galleryPrev').hidden = true; $('galleryNext').hidden = true; $('galleryCounter').hidden = true;
    if (kind === 'image') previewImageEl.src = url; else { previewVideoEl.preload = 'metadata'; previewVideoEl.src = url; }
    $('previewOpen').href = url; $('preview').hidden = false; document.body.style.overflow = 'hidden';
  }
  function openGallery(itemIndex, startIndex) {
    const item = results[itemIndex];
    if (!item || !item.images?.length) return;
    previewUrls = item.images; previewIndex = startIndex; previewKind = 'image';
    previewImageEl.hidden = false; previewVideoEl.hidden = true;
    showGalleryImage();
    $('previewOpen').href = previewUrls[previewIndex];
    $('preview').hidden = false; document.body.style.overflow = 'hidden';
  }
  function closePreview() {
    $('preview').hidden = true; previewVideoEl.pause(); previewVideoEl.removeAttribute('src'); previewImageEl.removeAttribute('src'); previewUrls = []; previewIndex = 0; document.body.style.overflow = '';
  }
  async function saveAllImages(urls) {
    status.textContent = '正在下载全部图片…';
    try {
      const files = [];
      for (let i = 0; i < urls.length; i++) {
        status.textContent = `正在下载 ${i + 1}/${urls.length}…`;
        const res = await fetch(`${urls[i]}${urls[i].includes('?') ? '&' : '?'}download=1`);
        if (!res.ok) continue;
        const blob = await res.blob();
        files.push(new File([blob], `xhs-${String(i + 1).padStart(2, '0')}.jpg`, {type: blob.type || 'image/jpeg'}));
      }
      if (!files.length) throw new Error('没有图片下载成功');
      if (navigator.canShare?.({files})) {
        await navigator.share({files, title:'保存小红书图集'});
        status.textContent = `已交给系统保存 ${files.length} 张。`;
      } else {
        for (const f of files) { const a = document.createElement('a'); a.href = URL.createObjectURL(f); a.download = f.name; a.click(); }
        status.textContent = `已开始下载 ${files.length} 张。`;
      }
    } catch (error) {
      if (error?.name !== 'AbortError') status.textContent = `保存失败：${error.message}`;
    }
  }
  async function saveToPhone(url, kind) {
    status.textContent = '正在准备文件…';
    try {
      const response = await fetch(`${url}${url.includes('?') ? '&' : '?'}download=1`);
      if (!response.ok) throw new Error('文件读取失败');
      const blob = await response.blob();
      const extension = kind === 'video' ? 'mp4' : ((blob.type.split('/')[1] || 'jpg').replace('jpeg','jpg'));
      const file = new File([blob], `xiaohongshu-${Date.now()}.${extension}`, {type:blob.type || (kind === 'video' ? 'video/mp4' : 'image/jpeg')});
      if (navigator.canShare?.({files:[file]})) await navigator.share({files:[file], title:'保存小红书作品'});
      else { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = file.name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 15000); }
      status.textContent = '文件已交给系统保存。';
    } catch (error) {
      if (error?.name !== 'AbortError') {
        window.open(url, '_blank', 'noopener');
        status.textContent = isMobile ? '已打开原文件；长按画面选择“存储到照片”。' : '已打开原文件；在原文件上右键另存为即可。';
      }
    }
  }
  function download(name, type, content) {
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([content], {type})); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 15000);
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const list = urls(input.value);
    if (!list.length) { status.textContent = '没有识别到小红书作品链接。'; return; }
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true; results = []; render(); let failed = 0, errors = [];
    for (let i = 0; i < list.length; i++) {
      status.textContent = `正在解析 ${i + 1}/${list.length}…`;
      try { const item = await parse(list[i]); results.push(item); if (item.kind !== 'author') saveHistory(item); render(); }
      catch (error) { failed++; errors.push(`第 ${i + 1} 条：${error.message}`); }
    }
    button.disabled = false;
    status.textContent = `完成：成功 ${results.length} 条，失败 ${failed} 条。${errors.length ? `\n${errors.join('\n')}` : ''}`;
  });
  async function parseNote(noteUrl) {
    status.textContent = '正在解析该作品…';
    try {
      const item = await parse(noteUrl);
      if (item.kind === 'author') throw new Error('该链接不是单条作品');
      results.unshift(item); saveHistory(item); render();
      status.textContent = `已解析：${item.title || '作品'}（${item.cached ? '缓存秒开' : '完成'}）`;
    } catch (error) { status.textContent = `解析失败：${error.message}`; }
  }
  resultsNode.addEventListener('click', async event => {
    const authorNote = event.target.closest('[data-author-note]');
    if (authorNote) return parseNote(authorNote.dataset.authorNote);
    const direct = event.target.closest('[data-save-direct]');
    if (direct) return saveToPhone(direct.dataset.saveDirect, direct.dataset.kind || 'video');
    const galleryBtn = event.target.closest('[data-preview-gallery]');
    if (galleryBtn) return openGallery(Number(galleryBtn.dataset.previewGallery), Number(galleryBtn.dataset.start || 0));
    const preview = event.target.closest('[data-preview]');
    if (preview) {
      const gIdx = preview.dataset.galleryIndex;
      if (gIdx !== '' && gIdx !== undefined) return openGallery(Number(preview.closest('.xhs-card')?.dataset.index || 0), Number(gIdx));
      return openPreview(preview.dataset.preview, preview.dataset.kind);
    }
    const all = event.target.closest('[data-save-all]');
    if (all) return saveAllImages(results[Number(all.dataset.saveAll)].images);
  });
  historyList.addEventListener('click', event => { const button = event.target.closest('[data-history-url]'); if (!button) return; input.value = button.dataset.historyUrl; form.requestSubmit(); window.scrollTo({top:0,behavior:'smooth'}); });
  $('clearHistory').addEventListener('click', () => { localStorage.removeItem(historyKey); renderHistory(); });
  $('previewClose').addEventListener('click', closePreview);
  $('galleryPrev').addEventListener('click', () => { if (previewIndex > 0) { previewIndex--; showGalleryImage(); } });
  $('galleryNext').addEventListener('click', () => { if (previewIndex < previewUrls.length - 1) { previewIndex++; showGalleryImage(); } });
  $('preview').addEventListener('click', event => { if (event.target === $('preview')) closePreview(); });
  $('previewSave').addEventListener('click', () => saveToPhone(previewUrl, previewKind));
  $('exportJson').addEventListener('click', () => download('xiaohongshu-results.json','application/json;charset=utf-8',JSON.stringify(results,null,2)));
  $('exportCsv').addEventListener('click', () => {
    const quote = value => `"${text(value).replace(/"/g,'""')}"`;
    const rows = [['作品ID','类型','标题','作者','点赞','收藏','评论','作品链接'], ...results.map(item => [item.id,item.type,item.title,item.author,item.stats?.liked,item.stats?.collected,item.stats?.commented,item.web_url])];
    download('xiaohongshu-results.csv','text/csv;charset=utf-8','\ufeff'+rows.map(row => row.map(quote).join(',')).join('\n'));
  });
  renderHistory();
})();
