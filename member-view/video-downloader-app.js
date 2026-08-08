/*
 * This interface uses the wx_channels_download parsing service.
 * Copyright (c) 2025 ltaoo.
 * Licensed under the MIT License with Commons Clause License Condition v1.0.
 * Source: https://github.com/ltaoo/wx_channels_download
 */

const API_URL = 'https://sph.litao.workers.dev/api/fetch_video_profile';

const form = document.querySelector('[data-download-form]');
const input = document.querySelector('[data-share-url]');
const queryButton = document.querySelector('[data-query-button]');
const statusNode = document.querySelector('[data-tool-status]');
const resultNode = document.querySelector('[data-video-result]');
const videoNode = document.querySelector('[data-video]');
const authorAvatar = document.querySelector('[data-author-avatar]');
const authorName = document.querySelector('[data-author-name]');
const descriptionNode = document.querySelector('[data-video-description]');
const statsNode = document.querySelector('[data-video-stats]');
const downloadButton = document.querySelector('[data-download-video]');
const rawDownloadButton = document.querySelector('[data-download-raw]');
const coverDownloadButton = document.querySelector('[data-download-cover]');
const transcriptButton = document.querySelector('[data-transcript-action]');
const transcriptStatus = document.querySelector('[data-transcript-status]');
const transcriptText = document.querySelector('[data-transcript-text]');
const transcriptSwitch = document.querySelector('[data-transcript-switch]');
const transcriptViewButtons = [...document.querySelectorAll('[data-transcript-view]')];
const commentButton = document.querySelector('[data-comment-action]');
const commentExcelButton = document.querySelector('[data-comment-excel]');
const commentStatus = document.querySelector('[data-comment-status]');
const commentText = document.querySelector('[data-comment-text]');
const historySection = document.querySelector('[data-download-history]');
const historyList = document.querySelector('[data-history-list]');
const clearHistoryButton = document.querySelector('[data-clear-history]');

const HISTORY_KEY = 'siyumenghai-video-download-history-v1';
const HISTORY_LIMIT = 20;
const TRANSCRIPT_CACHE_KEY = 'siyumenghai-video-transcripts-v3';
const TRANSCRIPT_CACHE_LIMIT = 12;
const LOCAL_TRANSCRIPT_HELPER = 'http://127.0.0.1:2025/transcribe';
const LOCAL_COMMENT_API = 'http://127.0.0.1:2022';
const COMMENT_LIMIT = 200;
const COMMENT_BRIDGE_URL = 'http://127.0.0.1:2024/extract';
const COMMENT_BRIDGE_ORIGIN = 'http://127.0.0.1:2024';
const BUILTIN_HOT_TERMS = [
  '陈祥榕', '戍边战士', '喀喇昆仑', '清澈的爱只为中国',
  '肖思远', '王焯冉', '陈红军', '边防', '祖国'
];

let currentVideo = null;
let currentTranscript = null;
let transcriptWorker = null;
let transcriptWorkerReady = false;
let transcriptPromise = null;
let currentCommentRows = [];

function readHistory() {
  try {
    const value = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    return Array.isArray(value) ? value.filter((item) => item?.shareUrl) : [];
  } catch {
    return [];
  }
}

function writeHistory(items) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, HISTORY_LIMIT)));
  } catch {
    // Downloading still works when local storage is unavailable.
  }
}

function readTranscriptCache() {
  try {
    const value = JSON.parse(localStorage.getItem(TRANSCRIPT_CACHE_KEY) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}

function cachedTranscript(shareUrl) {
  const item = readTranscriptCache()[shareUrl];
  if (typeof item?.corrected !== 'string' || !item.corrected.trim()) return null;
  return {
    corrected: item.corrected,
    raw: typeof item.raw === 'string' ? item.raw : item.corrected,
    correctionCount: Number(item.correctionCount || 0)
  };
}

function saveTranscript(shareUrl, result) {
  if (!shareUrl || !result?.corrected) return;
  try {
    const cache = readTranscriptCache();
    cache[shareUrl] = { ...result, savedAt: Date.now() };
    const entries = Object.entries(cache)
      .sort((left, right) => (right[1]?.savedAt || 0) - (left[1]?.savedAt || 0))
      .slice(0, TRANSCRIPT_CACHE_LIMIT);
    localStorage.setItem(TRANSCRIPT_CACHE_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // Transcription still works when local storage is unavailable.
  }
}

function historyTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'
  }).format(date);
}

function renderHistory() {
  const items = readHistory();
  historyList.replaceChildren();
  historySection.hidden = false;

  if (items.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'history-empty';
    empty.textContent = '暂无查询记录，查询成功后会自动保存在这里。';
    historyList.appendChild(empty);
    return;
  }

  items.forEach((item, index) => {
    const article = document.createElement('article');
    article.className = 'history-item';

    const cover = document.createElement('img');
    cover.className = 'history-cover';
    cover.alt = '';
    cover.loading = 'lazy';
    if (validHttpUrl(item.coverUrl)) cover.src = item.coverUrl;

    const content = document.createElement('div');
    content.className = 'history-content';
    const author = document.createElement('div');
    author.className = 'history-author';
    author.textContent = item.author || '视频号作者';
    const title = document.createElement('p');
    title.className = 'history-title';
    title.textContent = item.description || '视频号视频';
    const time = document.createElement('time');
    time.className = 'history-time';
    time.textContent = `查询于 ${historyTime(item.queriedAt || item.downloadedAt)}`;
    const actions = document.createElement('div');
    actions.className = 'history-actions';
    actions.innerHTML = `<button type="button" data-history-query="${index}">重新查询</button><button type="button" data-history-delete="${index}">删除</button>`;

    content.append(author, title, time, actions);
    article.append(cover, content);
    historyList.appendChild(article);
  });
}

function saveCurrentQuery() {
  if (!currentVideo?.shareUrl) return;
  const item = {
    shareUrl: currentVideo.shareUrl,
    coverUrl: currentVideo.coverUrl,
    author: currentVideo.author,
    description: currentVideo.description,
    queriedAt: new Date().toISOString()
  };
  const items = readHistory().filter((entry) => entry.shareUrl !== item.shareUrl);
  writeHistory([item, ...items]);
  renderHistory();
}

function showStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.classList.toggle('is-error', isError);
  statusNode.hidden = !message;
}

function showTranscriptStatus(message, state = '', asHtml = false) {
  if (asHtml) transcriptStatus.innerHTML = message; else transcriptStatus.textContent = message;
  transcriptStatus.classList.toggle('is-working', state === 'working');
  transcriptStatus.classList.toggle('is-error', state === 'error');
}

function resetTranscript() {
  currentTranscript = null;
  transcriptText.value = '';
  transcriptText.hidden = true;
  transcriptSwitch.hidden = true;
  transcriptButton.disabled = false;
  transcriptButton.textContent = '生成并复制逐字稿';
  showTranscriptStatus('建议优先把<strong style="color:#059669;font-weight:850">视频链接</strong>直接转发给你的微信好友<strong style="color:#059669;font-weight:850">“元宝”</strong>，并附提示词<strong style="color:#059669;font-weight:850">“提取逐字稿”</strong>。（<strong style="color:#059669;font-weight:850">速度更快</strong>）', '', true);
}

function showCommentStatus(message, state = '') {
  commentStatus.textContent = message;
  commentStatus.classList.toggle('is-working', state === 'working');
  commentStatus.classList.toggle('is-error', state === 'error');
}

function resetComments() {
  currentCommentRows = [];
  commentText.value = '';
  commentText.hidden = true;
  commentButton.disabled = false;
  commentButton.textContent = '提取并复制评论';
  commentExcelButton.hidden = true;
  commentStatus.innerHTML = '点击下载<span aria-hidden="true" style="display:inline-block;margin:0 2px 0 6px;color:#059669;font-size:18px;font-weight:900">→</span><a href="./local-comment-helper.html" target="_blank" rel="noopener noreferrer" style="display:inline-block;padding:2px 7px;background:#eaf8f1;border-radius:7px">「本地助手」</a>，发送并上传给你的Agent，自主安装并指导你使用。';
  commentStatus.classList.remove('is-working', 'is-error');
}

function validHttpUrl(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : '';
  } catch {
    return '';
  }
}

function bestVideoUrl(feedInfo) {
  return validHttpUrl(feedInfo?.h264VideoInfo?.videoUrl)
    || validHttpUrl(feedInfo?.h265VideoInfo?.videoUrl)
    || validHttpUrl(feedInfo?.videoUrl);
}

function rawVideoUrl(value) {
  try {
    const url = new URL(decodeURIComponent(value));
    const fileKey = url.searchParams.get('encfilekey');
    const token = url.searchParams.get('token');
    if (!fileKey || !token) return value;
    const raw = new URL(`${url.origin}${url.pathname}`);
    raw.searchParams.set('encfilekey', fileKey);
    raw.searchParams.set('token', token);
    return raw.toString();
  } catch {
    return value;
  }
}

function simplifiedChinese(value) {
  const text = String(value || '');
  try {
    return window.OpenCC?.Converter({ from: 'tw', to: 'cn' })(text) || text;
  } catch {
    return text;
  }
}

function pinyinKey(value) {
  try {
    return window.pinyinPro?.pinyin(value, {
      toneType: 'none',
      type: 'array',
      nonZh: 'removed'
    }).join('') || '';
  } catch {
    return '';
  }
}

function transcriptHotTerms(video) {
  const values = new Set(BUILTIN_HOT_TERMS);
  const description = simplifiedChinese(video?.description || '');
  const author = simplifiedChinese(video?.author || '');

  if (/^[\p{Script=Han}·]{2,8}$/u.test(author)) values.add(author);
  for (const match of description.matchAll(/#([\p{Script=Han}A-Za-z0-9·]{2,16})/gu)) {
    values.add(match[1]);
  }
  for (const match of description.matchAll(/[“"《]([\p{Script=Han}·]{2,16})[”"》]/gu)) {
    values.add(match[1]);
  }
  const leadingName = description.match(/^([\p{Script=Han}·]{2,8})(?=\d|[，。,.#\s])/u)?.[1];
  if (leadingName) values.add(leadingName);

  return [...values]
    .map((term) => simplifiedChinese(term).trim())
    .filter((term) => /^[\p{Script=Han}·]{2,16}$/u.test(term))
    .sort((left, right) => right.length - left.length);
}

function correctHomophones(value, terms) {
  let correctionCount = 0;
  const prepared = terms.map((term) => ({ term, key: pinyinKey(term) })).filter((item) => item.key);
  const corrected = value.replace(/[\p{Script=Han}·]{2,}/gu, (run) => {
    let output = run;
    for (const { term, key } of prepared) {
      if (term.length > output.length || output.includes(term)) continue;
      for (let index = 0; index <= output.length - term.length; index += 1) {
        const candidate = output.slice(index, index + term.length);
        if (candidate !== term && pinyinKey(candidate) === key) {
          output = `${output.slice(0, index)}${term}${output.slice(index + term.length)}`;
          correctionCount += 1;
        }
      }
    }
    return output;
  });
  return { text: corrected, correctionCount };
}

function cleanSegment(value, terms) {
  const simplified = simplifiedChinese(value)
    .replace(/([\p{Script=Han}])\s+(?=[\p{Script=Han}])/gu, '$1')
    .replace(/\s+/g, ' ')
    .trim();
  if (!simplified) return { text: '', correctionCount: 0 };
  const corrected = correctHomophones(simplified, terms);
  const text = /[。！？!?…]$/u.test(corrected.text) ? corrected.text : `${corrected.text}。`;
  return { text, correctionCount: corrected.correctionCount };
}

function buildTranscriptResult(result, video) {
  const rawSegments = Array.isArray(result?.segments) && result.segments.length
    ? result.segments.map((item) => String(item?.text || '').trim()).filter(Boolean)
    : String(result?.text || '').split('\n').map((item) => item.trim()).filter(Boolean);
  const terms = transcriptHotTerms(video);
  let correctionCount = 0;
  const correctedSegments = rawSegments.map((segment) => {
    const item = cleanSegment(segment, terms);
    correctionCount += item.correctionCount;
    return item.text;
  }).filter(Boolean);
  return {
    raw: rawSegments.join('\n'),
    corrected: correctedSegments.join('\n'),
    correctionCount
  };
}

function showTranscriptView(view = 'corrected') {
  if (!currentTranscript) return;
  transcriptText.value = currentTranscript[view] || currentTranscript.corrected;
  transcriptText.hidden = false;
  transcriptSwitch.hidden = false;
  transcriptViewButtons.forEach((button) => {
    const active = button.dataset.transcriptView === view;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

function filename(description, createTime) {
  const cleaned = String(description || '').replace(/[\\/:*?"<>|]/g, '').trim().slice(0, 80);
  if (cleaned) return `${cleaned}.mp4`;
  if (createTime) {
    const date = new Date(Number(createTime) * 1000);
    const pad = (value) => String(value).padStart(2, '0');
    return `视频号_${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}.mp4`;
  }
  return '视频号视频.mp4';
}

function coverFilename(description, contentType = '') {
  const cleaned = String(description || '').replace(/[\\/:*?"<>|]/g, '').trim().slice(0, 70) || '视频号视频';
  const type = String(contentType).toLowerCase();
  const extension = type.includes('png') ? 'png' : type.includes('webp') ? 'webp' : type.includes('gif') ? 'gif' : 'jpg';
  return `${cleaned}_封面.${extension}`;
}

function addStat(label, value) {
  if (!value) return;
  const item = document.createElement('span');
  item.textContent = `${label} ${value}`;
  statsNode.appendChild(item);
}

function renderResult(payload, shareUrl) {
  const feedInfo = payload?.data?.feedInfo;
  const authorInfo = payload?.data?.authorInfo;
  const videoUrl = bestVideoUrl(feedInfo);
  if (!feedInfo || !videoUrl) throw new Error('没有找到可下载的视频，请确认分享链接是否有效');

  currentVideo = {
    url: videoUrl,
    rawUrl: rawVideoUrl(videoUrl),
    shareUrl,
    coverUrl: validHttpUrl(feedInfo.coverUrl),
    author: authorInfo?.nickname || '视频号作者',
    description: feedInfo.description || '',
    createTime: feedInfo.createtime || ''
  };

  resetTranscript();
  resetComments();
  const previousTranscript = cachedTranscript(shareUrl);
  if (previousTranscript) {
    currentTranscript = previousTranscript;
    showTranscriptView('corrected');
    transcriptButton.textContent = '复制逐字稿';
    showTranscriptStatus(`已读取本机缓存的校正逐字稿${previousTranscript.correctionCount ? `，其中 ${previousTranscript.correctionCount} 处按专名热词校正` : ''}。`);
  }

  videoNode.src = videoUrl;
  const coverUrl = currentVideo.coverUrl;
  if (coverUrl) videoNode.poster = coverUrl; else videoNode.removeAttribute('poster');

  authorName.textContent = authorInfo?.nickname || '视频号作者';
  const avatarUrl = validHttpUrl(authorInfo?.headImgUrl);
  if (avatarUrl) {
    authorAvatar.src = avatarUrl;
    authorAvatar.alt = `${authorName.textContent}的头像`;
    authorAvatar.hidden = false;
  } else {
    authorAvatar.hidden = true;
    authorAvatar.removeAttribute('src');
  }

  descriptionNode.textContent = feedInfo.description || '该视频没有文字说明';
  statsNode.replaceChildren();
  addStat('赞', feedInfo.likeCountFmt);
  addStat('爱心', feedInfo.favCountFmt);
  addStat('转发', feedInfo.forwardCountFmt);
  addStat('评论', feedInfo.commentCountFmt);

  resultNode.hidden = false;
  resultNode.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function transcriptProgress(message) {
  if (message.status === 'progress' && Number.isFinite(message.progress)) {
    const percent = Math.max(0, Math.min(100, Math.round(message.progress)));
    showTranscriptStatus(`首次使用正在下载中文识别组件，当前文件 ${percent}%（下载一次后会缓存）`, 'working');
  } else if (message.status === 'loading') {
    showTranscriptStatus(message.data || '正在载入语音识别模型…', 'working');
  } else if (message.status === 'recognizing') {
    showTranscriptStatus(`正在识别第 ${message.current || 1}/${message.total || 1} 段人声…`, 'working');
  }
}

async function ensureTranscriptWorker() {
  if (transcriptWorkerReady && transcriptWorker) return transcriptWorker;
  if (transcriptPromise) return transcriptPromise;

  transcriptPromise = new Promise((resolve, reject) => {
    const worker = new Worker('./video-transcript-worker.js?v=20260808-8');
    transcriptWorker = worker;

    const handleMessage = (event) => {
      transcriptProgress(event.data || {});
      if (event.data?.status === 'ready') {
        transcriptWorkerReady = true;
        worker.removeEventListener('message', handleMessage);
        resolve(worker);
      } else if (event.data?.status === 'error') {
        worker.removeEventListener('message', handleMessage);
        worker.terminate();
        if (transcriptWorker === worker) transcriptWorker = null;
        transcriptPromise = null;
        reject(new Error(event.data.message || '语音识别模型加载失败'));
      }
    };

    worker.addEventListener('message', handleMessage);
    worker.addEventListener('error', (event) => {
      worker.terminate();
      if (transcriptWorker === worker) transcriptWorker = null;
      transcriptPromise = null;
      reject(new Error(event.message || '语音识别组件加载失败'));
    }, { once: true });
    worker.postMessage({ type: 'load' });
  });

  return transcriptPromise;
}

async function videoAudio(url) {
  showTranscriptStatus('正在读取视频中的声音…', 'working');
  const response = await fetch(url);
  if (!response.ok) throw new Error(`视频读取失败（${response.status}）`);
  const buffer = await response.arrayBuffer();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error('当前浏览器不支持音频读取，请使用最新版 Chrome 或 Safari');
  const audioContext = new AudioContextClass({ sampleRate: 16000 });
  try {
    const decoded = await audioContext.decodeAudioData(buffer.slice(0));
    const channelCount = decoded.numberOfChannels;
    const audio = new Float32Array(decoded.length);
    const scale = channelCount > 1 ? Math.sqrt(channelCount) / channelCount : 1;
    for (let channel = 0; channel < channelCount; channel += 1) {
      const values = decoded.getChannelData(channel);
      for (let index = 0; index < values.length; index += 1) audio[index] += values[index] * scale;
    }
    return audio;
  } finally {
    await audioContext.close();
  }
}

async function copyText(value, fallbackNode = transcriptText) {
  try {
    const copied = await Promise.race([
      navigator.clipboard.writeText(value).then(() => true, () => false),
      new Promise((resolve) => window.setTimeout(() => resolve(false), 1500))
    ]);
    if (copied) return true;
  } catch {
    // Fall back to selecting the visible transcript below.
  }
  fallbackNode.hidden = false;
  fallbackNode.focus();
  fallbackNode.select();
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  }
}

async function localCommentRequest(path, params) {
  const url = new URL(path, LOCAL_COMMENT_API);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== '' && value !== undefined && value !== null) url.searchParams.set(key, value);
  });
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 16000);
  try {
    const response = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
      cache: 'no-store',
      credentials: 'omit',
      targetAddressSpace: 'local'
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || (payload.code !== undefined && Number(payload.code) !== 0)) {
      throw new Error(payload.msg || payload.message || `本地助手返回 ${response.status}`);
    }
    return payload.data ?? payload;
  } finally {
    window.clearTimeout(timeout);
  }
}

function localCommentError(error) {
  const message = String(error?.message || '未知错误');
  if (error?.name === 'AbortError') return '本地助手响应超时，请确认微信电脑版已经打开视频号页面';
  if (error?.name === 'NotAllowedError' || /permission|not allowed|access denied/i.test(message)) {
    return '浏览器未允许访问本地网络；请在地址栏左侧的网站设置中允许“本地网络访问”，刷新后重试';
  }
  if (/Failed to fetch|NetworkError|Load failed|fetch resource/i.test(message)) {
    return '无法连接本地评论助手；请保持助手运行，并在浏览器提示时允许“本地网络访问”';
  }
  if (/socket|初始化客户端|not connected|timeout/i.test(message)) {
    return '本地助手已启动，但尚未连接微信视频号；请在微信电脑版打开任意视频号页面';
  }
  return message;
}

function commentTime(value) {
  const timestamp = Number(value);
  if (!timestamp) return '';
  const date = new Date(timestamp * 1000);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
  }).format(date);
}

function inlineReplies(comment) {
  const replies = comment?.levelTwoComment;
  return Array.isArray(replies) ? replies.filter((item) => item && typeof item === 'object') : [];
}

function formatComments(comments) {
  const replyCount = comments.reduce((total, item) => total + inlineReplies(item).length, 0);
  const lines = [`视频评论区（主评论 ${comments.length} 条${replyCount ? `，回复 ${replyCount} 条` : ''}）`, ''];
  comments.forEach((comment, index) => {
    const nickname = comment.nickname || comment.authorContact?.nickname || '匿名用户';
    const meta = [
      nickname,
      commentTime(comment.createtime),
      Number(comment.likeCount) ? `赞 ${comment.likeCount}` : '',
      comment.ipRegionInfo?.regionText || ''
    ].filter(Boolean).join(' · ');
    const content = String(comment.content || '').trim() || '[非文字评论]';
    lines.push(`${index + 1}. ${meta}`, content);
    inlineReplies(comment).forEach((reply) => {
      const replyName = reply.nickname || reply.authorContact?.nickname || '匿名用户';
      const replyContent = String(reply.content || reply.replyContent || '').trim() || '[非文字回复]';
      lines.push(`   ↳ ${replyName}：${replyContent}`);
    });
    lines.push('');
  });
  return lines.join('\n').trim();
}

function commentRows(comments) {
  const rows = [];
  comments.forEach((comment, index) => {
    const mainName = comment.nickname || comment.authorContact?.nickname || '匿名用户';
    rows.push({
      主评论序号: index + 1,
      类型: '主评论',
      昵称: mainName,
      评论内容: String(comment.content || '').trim() || '[非文字评论]',
      点赞数: Number(comment.likeCount) || 0,
      发布时间: Number(comment.createtime) ? new Date(Number(comment.createtime) * 1000) : '',
      IP属地: comment.ipRegionInfo?.regionText || '',
      回复对象: ''
    });
    inlineReplies(comment).forEach((reply) => {
      rows.push({
        主评论序号: index + 1,
        类型: '回复',
        昵称: reply.nickname || reply.authorContact?.nickname || '匿名用户',
        评论内容: String(reply.content || reply.replyContent || '').trim() || '[非文字回复]',
        点赞数: Number(reply.likeCount) || 0,
        发布时间: Number(reply.createtime) ? new Date(Number(reply.createtime) * 1000) : '',
        IP属地: reply.ipRegionInfo?.regionText || '',
        回复对象: reply.replyNickname || mainName
      });
    });
  });
  return rows;
}

function exportCommentsExcel() {
  if (!currentCommentRows.length) return showCommentStatus('请先提取评论，再导出 Excel。', 'error');
  if (!window.XLSX?.utils) return showCommentStatus('Excel 导出组件尚未加载，请刷新页面后重试。', 'error');
  const worksheet = XLSX.utils.json_to_sheet(currentCommentRows, { cellDates: true });
  const sheetRange = XLSX.utils.decode_range(worksheet['!ref']);
  for (let row = 1; row <= sheetRange.e.r; row += 1) {
    const cell = worksheet[XLSX.utils.encode_cell({ r: row, c: 5 })];
    if (cell) cell.z = 'yyyy-mm-dd hh:mm';
  }
  worksheet['!cols'] = [
    { wch: 12 }, { wch: 10 }, { wch: 20 }, { wch: 56 },
    { wch: 10 }, { wch: 20 }, { wch: 14 }, { wch: 20 }
  ];
  worksheet['!autofilter'] = { ref: worksheet['!ref'] };
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, worksheet, '视频评论');
  const label = `${currentVideo?.author || '视频号'}-${currentVideo?.description || '评论'}`
    .replace(/[\\/:*?"<>|]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 60) || '视频评论';
  XLSX.writeFile(workbook, `${label}-评论.xlsx`, { compression: true });
  showCommentStatus(`已导出 ${currentCommentRows.length} 行评论到 Excel。`);
}

async function resolveLocalVideo(shareUrl) {
  const profile = await localCommentRequest('/api/channels/feed/profile', { url: shareUrl });
  if (profile?.errCode) throw new Error(profile.errMsg || '本地助手无法解析该视频');
  const object = profile?.data?.object || {};
  const objectId = String(object.id || profile?.payload?.objectid || profile?.payload?.objectId || '');
  const nonceId = String(object.objectNonceId || profile?.payload?.objectNonceId || '');
  if (!objectId || !nonceId) throw new Error('没有取得评论所需的作品编号，请在微信电脑版打开这条视频后重试');
  return { objectId, nonceId };
}

async function fetchLocalComments(objectId, nonceId) {
  const comments = [];
  const ids = new Set();
  const markers = new Set();
  let nextMarker = '';
  for (let pageIndex = 0; pageIndex < 30 && comments.length < COMMENT_LIMIT; pageIndex += 1) {
    const response = await localCommentRequest('/api/channels/feed/comment/list', {
      oid: objectId,
      nid: nonceId,
      next_marker: nextMarker
    });
    if (response?.errCode) throw new Error(response.errMsg || '评论读取失败');
    const page = response?.data || {};
    const items = Array.isArray(page.commentInfo) ? page.commentInfo : [];
    items.forEach((item) => {
      const id = String(item?.commentId || `${item?.username || ''}:${item?.createtime || ''}:${item?.content || ''}`);
      if (!ids.has(id) && comments.length < COMMENT_LIMIT) {
        ids.add(id);
        comments.push(item);
      }
    });
    showCommentStatus(`正在提取评论，已获得 ${comments.length} 条…`, 'working');
    const marker = String(page.lastBuffer || '');
    if (!items.length || !marker || Number(page.downContinueFlag) === 0 || markers.has(marker)) break;
    markers.add(marker);
    nextMarker = marker;
  }
  return comments;
}

async function extractCurrentComments() {
  if (!currentVideo?.shareUrl) return;
  const existingText = commentText.value.trim();
  if (existingText) {
    const copied = await copyText(existingText, commentText);
    showCommentStatus(copied ? '评论区内容已复制到剪贴板。' : '请长按或全选下方评论后复制。', copied ? '' : 'error');
    return;
  }

  const video = { ...currentVideo };
  const isLocalPage = ['127.0.0.1', 'localhost'].includes(location.hostname);
  if (!isLocalPage) {
    const bridgeUrl = new URL(COMMENT_BRIDGE_URL);
    bridgeUrl.searchParams.set('url', video.shareUrl);
    const popup = window.open(bridgeUrl, 'siyumenghai-comment-bridge', 'width=760,height=760');
    showCommentStatus(
      popup ? '已打开安全评论窗口；浏览器询问本地网络权限时请选择“允许”。' : '浏览器拦截了评论窗口，请允许此网站打开弹窗后重试。',
      popup ? 'working' : 'error'
    );
    return;
  }
  commentButton.disabled = true;
  commentButton.textContent = '正在提取…';
  try {
    showCommentStatus('正在连接本地评论助手…', 'working');
    const { objectId, nonceId } = await resolveLocalVideo(video.shareUrl);
    showCommentStatus('已识别视频，正在分页读取评论…', 'working');
    const comments = await fetchLocalComments(objectId, nonceId);
    if (!comments.length) throw new Error('这条视频没有返回可见评论');
    if (currentVideo?.shareUrl !== video.shareUrl) return;
    const text = formatComments(comments);
    currentCommentRows = commentRows(comments);
    commentText.value = text;
    commentText.hidden = false;
    commentButton.textContent = '复制评论';
    commentExcelButton.hidden = false;
    const copied = await copyText(text, commentText);
    const limited = comments.length >= COMMENT_LIMIT ? `（已达到 ${COMMENT_LIMIT} 条上限）` : '';
    showCommentStatus(copied ? `已提取 ${comments.length} 条主评论${limited}并复制到剪贴板。` : `已提取 ${comments.length} 条主评论，请再次点击“复制评论”。`, copied ? '' : 'error');
  } catch (error) {
    commentButton.textContent = '重新提取评论';
    showCommentStatus(`评论提取失败：${localCommentError(error)}`, 'error');
  } finally {
    commentButton.disabled = false;
  }
}

window.addEventListener('message', (event) => {
  if (event.origin !== COMMENT_BRIDGE_ORIGIN || event.data?.type !== 'siyumenghai-comments') return;
  const text = String(event.data.text || '').trim();
  if (!text) return;
  currentCommentRows = Array.isArray(event.data.rows) ? event.data.rows.map((row) => ({
    ...row,
    发布时间: row.发布时间 ? new Date(row.发布时间) : ''
  })) : [];
  commentText.value = text;
  commentText.hidden = false;
  commentButton.textContent = '复制评论';
  commentExcelButton.hidden = currentCommentRows.length === 0;
  showCommentStatus(String(event.data.message || '评论已提取并复制。'));
});

async function transcribeCurrentVideo() {
  if (!currentVideo?.url) return;
  const video = { ...currentVideo };
  if (currentTranscript?.corrected) {
    const copied = await copyText(currentTranscript.corrected);
    showTranscriptStatus(copied ? '逐字稿已复制到剪贴板。' : '请长按或全选下方逐字稿后复制。', copied ? '' : 'error');
    return;
  }

  const helperUrl = new URL(LOCAL_TRANSCRIPT_HELPER);
  helperUrl.hash = encodeURIComponent(JSON.stringify({
    videoUrl: video.url,
    shareUrl: video.shareUrl,
    author: video.author,
    description: video.description
  }));
  const popup = window.open(helperUrl.href, 'siyumenghai-transcript-helper', 'width=840,height=760');
  if (!popup) {
    showTranscriptStatus('浏览器拦截了本机助手窗口，请允许弹窗后重试。', 'error');
    return;
  }
  transcriptButton.textContent = '再次打开本机助手';
  showTranscriptStatus('已交给本机助手识别；完成后会自动复制逐字稿。', 'working');
}

async function downloadVideo(url) {
  if (!currentVideo || !url) return;
  downloadButton.disabled = true;
  rawDownloadButton.disabled = true;
  showStatus('正在准备视频文件，请稍候…');
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`服务器返回 ${response.status}`);
    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename(currentVideo.description, currentVideo.createTime);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
    showStatus('下载已经开始');
  } catch (error) {
    showStatus(`下载失败：${error.message}`, true);
  } finally {
    downloadButton.disabled = false;
    rawDownloadButton.disabled = false;
  }
}

async function downloadCover() {
  const url = currentVideo?.coverUrl;
  if (!url) {
    showStatus('该视频没有可下载的封面', true);
    return;
  }

  coverDownloadButton.disabled = true;
  showStatus('正在准备封面图片…');
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`服务器返回 ${response.status}`);
    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = coverFilename(currentVideo.description, blob.type);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
    showStatus('封面下载已经开始');
  } catch (error) {
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.click();
    showStatus('封面已打开；如果没有直接保存，请长按图片保存');
  } finally {
    coverDownloadButton.disabled = false;
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const shareUrl = validHttpUrl(input.value.trim());
  if (!shareUrl) {
    showStatus('请粘贴完整的视频号分享链接', true);
    input.focus();
    return;
  }

  queryButton.disabled = true;
  resultNode.hidden = true;
  videoNode.removeAttribute('src');
  videoNode.load();
  currentVideo = null;
  showStatus('正在查询视频信息…');

  try {
    const response = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: shareUrl })
    });
    const payload = await response.json();
    if (!response.ok || payload.errCode) throw new Error(payload.errMsg || '查询失败');
    renderResult(payload, shareUrl);
    saveCurrentQuery();
    showStatus('');
  } catch (error) {
    showStatus(`查询失败：${error.message}`, true);
  } finally {
    queryButton.disabled = false;
  }
});

downloadButton.addEventListener('click', () => downloadVideo(currentVideo?.url));
rawDownloadButton.addEventListener('click', () => downloadVideo(currentVideo?.rawUrl));
coverDownloadButton.addEventListener('click', downloadCover);
transcriptButton.addEventListener('click', transcribeCurrentVideo);
transcriptSwitch.addEventListener('click', (event) => {
  const target = event.target.closest('[data-transcript-view]');
  if (target) showTranscriptView(target.dataset.transcriptView);
});
commentButton.addEventListener('click', extractCurrentComments);
commentExcelButton.addEventListener('click', exportCommentsExcel);

historyList.addEventListener('click', (event) => {
  const queryTarget = event.target.closest('[data-history-query]');
  const deleteTarget = event.target.closest('[data-history-delete]');
  const items = readHistory();

  if (queryTarget) {
    const item = items[Number(queryTarget.dataset.historyQuery)];
    if (!item) return;
    input.value = item.shareUrl;
    form.requestSubmit();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  if (deleteTarget) {
    items.splice(Number(deleteTarget.dataset.historyDelete), 1);
    writeHistory(items);
    renderHistory();
  }
});

clearHistoryButton.addEventListener('click', () => {
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
});

renderHistory();
