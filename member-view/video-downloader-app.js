/*
 * This interface uses the wx_channels_download parsing service.
 * Copyright (c) 2025 ltaoo.
 * Licensed under the MIT License with Commons Clause License Condition v1.0.
 * Source: https://github.com/ltaoo/wx_channels_download
 */

const API_URL = '/api/video/profile';

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
const commentRefreshButton = document.querySelector('[data-comment-refresh]');
const commentExcelButton = document.querySelector('[data-comment-excel]');
const commentStatus = document.querySelector('[data-comment-status]');
const commentText = document.querySelector('[data-comment-text]');
const historySection = document.querySelector('[data-download-history]');
const historyList = document.querySelector('[data-history-list]');
const clearHistoryButton = document.querySelector('[data-clear-history]');

const HISTORY_KEY = 'siyumenghai-video-download-history-v1';
const HISTORY_LIMIT = 20;
const TRANSCRIPT_CACHE_KEY = 'siyumenghai-video-transcripts-v10-accuracy';
const TRANSCRIPT_CACHE_LIMIT = HISTORY_LIMIT;
const TRANSCRIPT_TASK_KEY = 'siyumenghai-video-transcript-tasks-v1';
const TRANSCRIPT_TASK_LIMIT = HISTORY_LIMIT;
const COMMENT_CACHE_KEY = 'siyumenghai-video-comments-v1';
const COMMENT_CACHE_LIMIT = HISTORY_LIMIT;
const TRANSCRIPT_API = '/api/transcripts/jobs';
const IMAGE_PROXY_API = '/api/transcripts/images?url=';
const MEDIA_PROXY_API = '/api/transcripts/media?url=';
const LOCAL_COMMENT_API = 'http://127.0.0.1:2022';
const COMMENT_LIMIT = 1000;
const COMMENT_PAGE_LIMIT = 200;
const COMMENT_BRIDGE_URL = 'http://127.0.0.1:2024/extract';
const COMMENT_BRIDGE_ORIGIN = 'http://127.0.0.1:2024';
const LOCAL_HELPER_STATUS_API = 'http://127.0.0.1:2024/status';
const LOCAL_HELPER_LAUNCH_API = 'http://127.0.0.1:2024/launch';
const BUILTIN_HOT_TERMS = [
  '陈祥榕', '戍边战士', '喀喇昆仑', '清澈的爱只为中国',
  '肖思远', '王焯冉', '陈红军', '边防', '祖国',
  '公域', '私域', '高变现', '获客难', '咨询陪跑',
  '群响', '群响私董会', '刘思毅', '千万级名师', 'MCN',
  '混元模型', '不紧不慢', '共情钩子', '视频号'
];
const DOMAIN_CORRECTIONS = new Map([
  ['公寓直播', '公域直播'],
  ['私域和公寓', '私域和公域'],
  ['高变线', '高变现'],
  ['咨询背包', '咨询陪跑'],
  ['破贺难', '获客难'],
  ['变相差', '变现差'],
  ['千万几名师', '千万级名师'],
  ['群想', '群响'],
  ['刘思议', '刘思毅'],
  ['群响思想思想会', '群响私董会'],
  ['群响思想会', '群响私董会'],
  ['IP和M森', 'IP和MCN'],
  ['混元3模型', '混元模型'],
  ['会员三模型', '混元模型'],
  ['会员模型', '混元模型'],
  ['会元模型', '混元模型'],
  ['混原模型', '混元模型'],
  ['不勤不慢', '不紧不慢'],
  ['不勤慢', '不紧不慢'],
  ['Workbuddy', 'WorkBuddy'],
  ['KimiK3', 'Kimi K3'],
  ['超盘', '操盘'],
  ['高变X', '高变现'],
  ['变X', '变现'],
  ['客难成本', '获客成本'],
  ['确确是', '确实是'],
  ['价值百W', '价值百万'],
  ['小书博主', '小红书博主'],
  ['小书广告', '小红书广告'],
  ['不自闭环', '不做闭环'],
  ['必4无疑', '必死无疑'],
  ['而且它模型质量很差的', '而且它的模型质量很差'],
  ['AI时代', 'AI 时代']
]);

let currentVideo = null;
let currentTranscript = null;
let transcriptWorker = null;
let transcriptWorkerReady = false;
let transcriptPromise = null;
let transcriptMonitorTimer = 0;
let transcriptMonitorRunning = false;
let currentCommentRows = [];
let videoLoadTimer = 0;

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
  const correctedLength = item.corrected.replace(/\s/g, '').length;
  const audioLength = typeof item.audioRaw === 'string' ? item.audioRaw.replace(/\s/g, '').length : 0;
  if (item.source === 'ocr_asr_fusion' && audioLength && correctedLength < audioLength * 0.82) return null;
  return {
    corrected: item.corrected,
    raw: typeof item.raw === 'string' ? item.raw : item.corrected,
    correctionCount: Number(item.correctionCount || 0),
    source: String(item.source || 'asr'),
    audioRaw: typeof item.audioRaw === 'string' ? item.audioRaw : '',
    pipelineVersion: String(item.pipelineVersion || ''),
    calibrationStatus: String(item.calibrationStatus || ''),
    calibrationChanges: Number(item.calibrationChanges || 0)
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

function readTranscriptTasks() {
  try {
    const value = JSON.parse(localStorage.getItem(TRANSCRIPT_TASK_KEY) || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

function transcriptTask(shareUrl) {
  if (!shareUrl) return null;
  const task = readTranscriptTasks()[shareUrl];
  return task?.jobId ? task : null;
}

function writeTranscriptTasks(tasks) {
  try {
    const entries = Object.entries(tasks)
      .filter(([shareUrl, task]) => shareUrl && task?.jobId)
      .sort((left, right) => Number(right[1]?.updatedAt || 0) - Number(left[1]?.updatedAt || 0))
      .slice(0, TRANSCRIPT_TASK_LIMIT);
    localStorage.setItem(TRANSCRIPT_TASK_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // The server task keeps running even when local storage is unavailable.
  }
}

function saveTranscriptTask(task) {
  if (!task?.shareUrl || !task?.jobId) return;
  const tasks = readTranscriptTasks();
  tasks[task.shareUrl] = {
    ...tasks[task.shareUrl],
    ...task,
    updatedAt: Date.now()
  };
  writeTranscriptTasks(tasks);
}

function removeTranscriptTask(shareUrl) {
  const tasks = readTranscriptTasks();
  if (!tasks[shareUrl]) return;
  delete tasks[shareUrl];
  writeTranscriptTasks(tasks);
}

function isActiveTranscriptTask(task) {
  return Boolean(task?.jobId && !['completed', 'error'].includes(task.status));
}

function transcriptTaskLabel(task) {
  if (!task) return '';
  if (task.status === 'error') return '逐字稿识别失败';
  if (task.status === 'queued') {
    const ahead = Number(task.ahead || 0);
    return ahead > 0 ? `逐字稿排队中（前面 ${ahead} 条）` : '逐字稿排队中';
  }
  return '逐字稿后台识别中';
}

function readCommentCache() {
  try {
    const value = JSON.parse(localStorage.getItem(COMMENT_CACHE_KEY) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}

function cachedComments(shareUrl) {
  const item = readCommentCache()[shareUrl];
  const history = readHistory();
  const historyItem = history.find((entry) => entry.shareUrl === shareUrl);
  const text = typeof item?.text === 'string' && item.text.trim()
    ? item.text
    : typeof historyItem?.commentsText === 'string' ? historyItem.commentsText : '';
  if (!text.trim()) return null;
  if (historyItem && item?.text && historyItem.commentsText !== item.text) {
    historyItem.commentsText = item.text;
    writeHistory(history);
  }
  return {
    text,
    rows: Array.isArray(item?.rows) ? item.rows.map((row) => ({
      ...row,
      发布时间: row.发布时间 ? new Date(row.发布时间) : ''
    })) : []
  };
}

function saveComments(shareUrl, text, rows) {
  if (!shareUrl || !String(text || '').trim()) return;
  try {
    const cache = readCommentCache();
    cache[shareUrl] = { text, rows: Array.isArray(rows) ? rows : [], savedAt: Date.now() };
    const entries = Object.entries(cache)
      .sort((left, right) => (right[1]?.savedAt || 0) - (left[1]?.savedAt || 0))
      .slice(0, COMMENT_CACHE_LIMIT);
    localStorage.setItem(COMMENT_CACHE_KEY, JSON.stringify(Object.fromEntries(entries)));

    const history = readHistory();
    const historyItem = history.find((entry) => entry.shareUrl === shareUrl);
    if (historyItem) {
      historyItem.commentsText = text;
      writeHistory(history);
    }
  } catch {
    // Comment extraction still works when local storage is unavailable.
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
    cover.referrerPolicy = 'no-referrer';
    loadHistoryCover(item, cover);

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
    const transcript = cachedTranscript(item.shareUrl);
    const task = transcriptTask(item.shareUrl);
    const taskStatus = document.createElement('span');
    taskStatus.className = 'history-task-status';
    if (transcript) {
      taskStatus.textContent = '逐字稿已完成';
      taskStatus.classList.add('is-complete');
    } else if (task) {
      taskStatus.textContent = transcriptTaskLabel(task);
      taskStatus.classList.add(task.status === 'error' ? 'is-error' : 'is-working');
    } else {
      taskStatus.hidden = true;
    }
    const actions = document.createElement('div');
    actions.className = 'history-actions';
    actions.innerHTML = `<button type="button" data-history-copy="${index}">复制原视频链接</button><button type="button" data-history-transcript="${index}">复制逐字稿</button><button type="button" data-history-comments="${index}">复制评论</button><button type="button" data-history-query="${index}">重新查询</button><button type="button" data-history-delete="${index}">删除</button>`;

    content.append(author, title, time, taskStatus, actions);
    article.append(cover, content);
    historyList.appendChild(article);
  });
}

function saveCurrentQuery() {
  if (!currentVideo?.shareUrl) return;
  const item = {
    shareUrl: currentVideo.shareUrl,
    coverUrl: currentVideo.coverUrl,
    videoUrl: currentVideo.url,
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
  transcriptViewButtons.forEach((button) => {
    button.textContent = button.dataset.transcriptView === 'corrected' ? '校正逐字稿' : '原始识别稿';
  });
  transcriptButton.disabled = false;
  transcriptButton.textContent = '生成并复制逐字稿';
  const task = transcriptTask(currentVideo?.shareUrl);
  if (task) {
    transcriptButton.textContent = isActiveTranscriptTask(task) ? '查看后台进度' : '重新生成逐字稿';
    showTranscriptTaskStatus(task);
  } else {
    showTranscriptStatus('建议优先把<strong style="color:#059669;font-weight:850">视频链接</strong>直接转发给你的微信好友<strong style="color:#059669;font-weight:850">“元宝”</strong>，并附提示词<strong style="color:#059669;font-weight:850">“提取逐字稿”</strong>。（<strong style="color:#059669;font-weight:850">速度更快、更准</strong>）', '', true);
  }
}

function showCommentStatus(message, state = '') {
  commentStatus.textContent = message;
  commentStatus.classList.toggle('is-working', state === 'working');
  commentStatus.classList.toggle('is-error', state === 'error');
}

function localHelperPrompt() {
  return '本地助手：<a href="./local-comment-helper.html" target="_blank" rel="noopener noreferrer" data-local-helper-entry data-helper-action="checking" style="display:inline-block;padding:3px 9px;background:#eaf8f1;border-radius:7px;color:#067653;font-weight:750">正在自动检测…</a>';
}

function setLocalHelperEntry(label, action) {
  const entry = commentStatus.querySelector('[data-local-helper-entry]');
  if (!entry) return;
  entry.textContent = label;
  entry.dataset.helperAction = action;
  if (action === 'download') {
    entry.href = './local-comment-helper.html';
    entry.target = '_blank';
  } else {
    entry.href = '#';
    entry.removeAttribute('target');
  }
}

async function localHelperRequest(url, options = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 1800);
  try {
    const response = await fetch(url, {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
      targetAddressSpace: 'local',
      ...options,
      signal: controller.signal
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) throw new Error(payload.message || `本地助手返回 ${response.status}`);
    return payload;
  } finally {
    window.clearTimeout(timer);
  }
}

async function detectLocalHelper() {
  const isLocalBridgePage = ['127.0.0.1', 'localhost'].includes(location.hostname) && location.port === '2024';
  if (!isLocalBridgePage) {
    setLocalHelperEntry('浏览器将通过安全窗口连接', 'bridge');
    return;
  }
  setLocalHelperEntry('正在自动检测…', 'checking');
  try {
    const payload = await localHelperRequest(LOCAL_HELPER_STATUS_API);
    if (!payload.installed) return setLocalHelperEntry('未安装，点击下载', 'download');
    setLocalHelperEntry(payload.running ? '本地助手已打开' : '已安装，点击打开', payload.running ? 'running' : 'launch');
  } catch {
    setLocalHelperEntry('浏览器将通过安全窗口连接', 'bridge');
  }
}

function renderLocalHelperPrompt() {
  commentStatus.innerHTML = localHelperPrompt();
  commentStatus.classList.remove('is-working', 'is-error');
  detectLocalHelper();
}

function resetComments() {
  const cached = cachedComments(currentVideo?.shareUrl);
  currentCommentRows = cached?.rows || [];
  commentText.value = cached?.text || '';
  commentText.hidden = !cached;
  commentButton.disabled = false;
  commentButton.textContent = cached ? '复制评论' : '提取并复制评论';
  commentRefreshButton.hidden = !cached;
  commentExcelButton.hidden = false;
  if (cached) showCommentStatus('已读取本机缓存的评论，可直接复制或导出 Excel。');
  else renderLocalHelperPrompt();
}

function validHttpUrl(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : '';
  } catch {
    return '';
  }
}

function imageProxyUrl(value) {
  const url = validHttpUrl(value);
  return url ? `${IMAGE_PROXY_API}${encodeURIComponent(url)}` : '';
}

function highResolutionCoverUrl(value) {
  const url = validHttpUrl(value);
  if (!url) return '';
  try {
    const parsed = new URL(url);
    parsed.searchParams.delete('picformat');
    return parsed.toString();
  } catch {
    return url;
  }
}

function mediaProxyUrl(value) {
  const url = validHttpUrl(value);
  return url ? new URL(`${MEDIA_PROXY_API}${encodeURIComponent(url)}`, window.location.origin).toString() : '';
}

function displayHistoryCover(url, image, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error('cover timeout')), timeout);
    image.style.visibility = 'hidden';
    image.onload = () => {
      window.clearTimeout(timer);
      image.style.visibility = '';
      resolve();
    };
    image.onerror = () => {
      window.clearTimeout(timer);
      reject(new Error('cover failed'));
    };
    image.referrerPolicy = 'no-referrer';
    image.src = imageProxyUrl(url);
  });
}

function showHistoryFallback(image, videoUrl) {
  const playableUrl = validHttpUrl(videoUrl);
  if (playableUrl) {
    const preview = document.createElement('video');
    preview.className = 'history-cover';
    preview.muted = true;
    preview.playsInline = true;
    preview.preload = 'metadata';
    preview.src = playableUrl;
    preview.addEventListener('loadedmetadata', () => {
      try { preview.currentTime = Math.min(0.1, preview.duration || 0.1); } catch {}
    }, { once: true });
    image.replaceWith(preview);
    preview.load();
    return;
  }
  const fallback = document.createElement('div');
  fallback.className = 'history-cover history-cover-fallback';
  fallback.textContent = '重新查询';
  image.replaceWith(fallback);
}

async function loadHistoryCover(item, image) {
  try {
    const existingUrl = validHttpUrl(item?.coverUrl);
    if (!existingUrl) throw new Error('cover missing');
    await displayHistoryCover(existingUrl, image);
  } catch {
    await refreshHistoryCover(item, image);
  }
}

async function refreshHistoryCover(item, image) {
  if (!item?.shareUrl || image.dataset.refreshing) return;
  image.dataset.refreshing = '1';
  try {
    const payload = await queryVideoProfile(item.shareUrl);
    const freshCoverUrl = validHttpUrl(payload?.data?.feedInfo?.coverUrl);
    const freshVideoUrl = bestVideoUrl(payload?.data?.feedInfo) || validHttpUrl(item?.videoUrl);
    if (!freshCoverUrl) throw new Error('cover missing');
    item.coverUrl = freshCoverUrl;
    item.videoUrl = freshVideoUrl;
    const items = readHistory();
    const target = items.find((entry) => entry.shareUrl === item.shareUrl);
    if (target) {
      target.coverUrl = freshCoverUrl;
      target.videoUrl = freshVideoUrl;
      writeHistory(items);
    }
    await displayHistoryCover(freshCoverUrl, image);
  } catch {
    showHistoryFallback(image, item?.videoUrl);
  } finally {
    delete image.dataset.refreshing;
  }
}

function bestVideoUrl(feedInfo) {
  return validHttpUrl(feedInfo?.h264VideoInfo?.videoUrl)
    || validHttpUrl(feedInfo?.h265VideoInfo?.videoUrl)
    || validHttpUrl(feedInfo?.videoUrl);
}

async function queryVideoProfile(shareUrl) {
  const response = await fetch(`${API_URL}?url=${encodeURIComponent(shareUrl)}`, {
    method: 'GET',
    headers: { Accept: 'application/json' }
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || (typeof result?.code === 'number' && result.code !== 0)) {
    throw new Error(result?.msg || result?.errMsg || '解析服务暂时不可用');
  }
  return result?.data?.feedInfo ? result : result?.data || result;
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

function loadPlayableVideo(primaryUrl, fallbackUrl) {
  window.clearTimeout(videoLoadTimer);
  const primary = validHttpUrl(primaryUrl);
  const fallback = validHttpUrl(fallbackUrl);
  let usingFallback = false;

  const load = (url) => {
    videoNode.src = url;
    videoNode.load();
    videoLoadTimer = window.setTimeout(() => {
      if (videoNode.readyState === 0 && !usingFallback && fallback && fallback !== primary) {
        usingFallback = true;
        load(fallback);
      }
    }, 8000);
  };

  videoNode.onloadedmetadata = () => window.clearTimeout(videoLoadTimer);
  videoNode.onerror = () => {
    window.clearTimeout(videoLoadTimer);
    if (!usingFallback && fallback && fallback !== primary) {
      usingFallback = true;
      load(fallback);
    }
  };
  load(primary);
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
  let text = corrected.text;
  let correctionCount = corrected.correctionCount;
  const incompletePhraseMatches = text.match(/大错特(?!错)/gu) || [];
  if (incompletePhraseMatches.length) {
    text = text.replace(/大错特(?!错)/gu, '大错特错');
    correctionCount += incompletePhraseMatches.length;
  }
  for (const [wrong, right] of DOMAIN_CORRECTIONS) {
    const matches = text.split(wrong).length - 1;
    if (!matches) continue;
    text = text.replaceAll(wrong, right);
    correctionCount += matches;
  }
  text = /[。！？!?…]$/u.test(text) ? text : `${text}。`;
  return { text, correctionCount };
}

function correctContextConsistency(segments) {
  const combined = segments.join('');
  if (!combined.includes('粉丝') || !/(?:视频号|抖音|小红书|快手|微博|账号)/u.test(combined)) {
    return { segments, correctionCount: 0 };
  }
  const pattern = /((?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千万两]+)(?:万|千|百)?(?:\d+)?)(的?)(?:粉钉|粉色)(?=的|吧|呢|，|。|、|\s|$)/gu;
  let correctionCount = 0;
  return {
    segments: segments.map((segment) => segment.replace(pattern, (...match) => {
      correctionCount += 1;
      return `${match[1]}${match[2]}粉丝`;
    })),
    correctionCount
  };
}

function buildTranscriptResult(result, video) {
  const source = String(result?.source || 'asr');
  const correctedSource = Array.isArray(result?.segments) && result.segments.length
    ? result.segments.map((item) => String(item?.text || '').trim()).filter(Boolean)
    : String(result?.text || '').split('\n').map((item) => item.trim()).filter(Boolean);
  const rawSource = Array.isArray(result?.raw_segments) && result.raw_segments.length
    ? result.raw_segments.map((item) => String(item?.text || '').trim()).filter(Boolean).join('\n')
    : String(result?.audio_text || result?.text || '');
  const originalText = source === 'ocr_asr_fusion' && String(result?.ocr_text || '').trim()
    ? String(result.ocr_text)
    : rawSource;
  const rawSegments = originalText.split('\n').map((item) => item.trim()).filter(Boolean);
  const terms = transcriptHotTerms(video);
  let correctionCount = 0;
  for (const [wrong] of DOMAIN_CORRECTIONS) {
    correctionCount += originalText.split(wrong).length - 1;
  }
  correctionCount += (originalText.match(/大错特(?!错)/gu) || []).length;
  let correctedSegments = correctedSource.map((segment) => {
    const item = cleanSegment(segment, terms);
    correctionCount += item.correctionCount;
    return item.text;
  }).filter(Boolean);
  const consistent = correctContextConsistency(correctedSegments);
  correctedSegments = consistent.segments;
  correctionCount += consistent.correctionCount;
  const calibrationChanges = Array.isArray(result?.calibration_changes) ? result.calibration_changes.length : 0;
  correctionCount += calibrationChanges;
  return {
    raw: rawSegments.join('\n'),
    corrected: correctedSegments.join('\n'),
    correctionCount,
    source,
    audioRaw: String(result?.audio_text || ''),
    calibrationStatus: String(result?.calibration_status || ''),
    calibrationChanges
  };
}

function showTranscriptView(view = 'corrected') {
  if (!currentTranscript) return;
  const calibrated = currentTranscript.calibrationStatus === 'applied' || currentTranscript.source === 'calibrated';
  transcriptViewButtons.forEach((button) => {
    button.textContent = button.dataset.transcriptView === 'corrected'
      ? (calibrated ? '智能校准稿' : '校正逐字稿')
      : '原始识别稿';
  });
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
    rawUrl: validHttpUrl(feedInfo?.h265VideoInfo?.videoUrl) || videoUrl,
    shareUrl,
    coverUrl: validHttpUrl(feedInfo.coverUrl),
    author: authorInfo?.nickname || '视频号作者',
    description: feedInfo.description || '',
    createTime: feedInfo.createtime || ''
  };

  resetTranscript();
  resetComments();
  let previousTranscript = cachedTranscript(shareUrl);
  if (previousTranscript) {
    if (previousTranscript.raw === previousTranscript.corrected && previousTranscript.correctionCount === 0) {
      previousTranscript = buildTranscriptResult({ text: previousTranscript.raw }, currentVideo);
      saveTranscript(shareUrl, previousTranscript);
    }
    currentTranscript = previousTranscript;
    showTranscriptView('corrected');
    transcriptButton.textContent = '复制逐字稿';
    showTranscriptStatus(`已读取本机缓存的逐字稿${previousTranscript.correctionCount ? `，其中校正 ${previousTranscript.correctionCount} 处` : ''}。`);
  }

  // The stripped "raw" URL can resolve to HEVC even when the parser returned
  // H.264. Chromium then shows a disabled 0:00 player. Stream the explicit H.264
  // source through the same-origin relay for reliable metadata and Range seeks;
  // keep rawUrl for downloading only and fall back to the direct H.264 URL.
  loadPlayableVideo(mediaProxyUrl(videoUrl), videoUrl);
  const coverUrl = currentVideo.coverUrl;
  if (coverUrl) videoNode.poster = imageProxyUrl(coverUrl); else videoNode.removeAttribute('poster');

  authorName.textContent = authorInfo?.nickname || '视频号作者';
  const avatarUrl = validHttpUrl(authorInfo?.headImgUrl);
  if (avatarUrl) {
    authorAvatar.src = imageProxyUrl(avatarUrl);
    authorAvatar.alt = `${authorName.textContent}的头像`;
    authorAvatar.hidden = false;
    authorAvatar.onerror = () => {
      authorAvatar.hidden = true;
      authorAvatar.removeAttribute('src');
    };
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
    showTranscriptStatus(message.data || '正在准备识别组件…', 'working');
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
        reject(new Error(event.data.message || '识别组件加载失败'));
      }
    };

    worker.addEventListener('message', handleMessage);
    worker.addEventListener('error', (event) => {
      worker.terminate();
      if (transcriptWorker === worker) transcriptWorker = null;
      transcriptPromise = null;
      reject(new Error(event.message || '识别组件加载失败'));
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
  let temporaryNode = null;
  if (!fallbackNode) {
    temporaryNode = document.createElement('textarea');
    temporaryNode.value = value;
    temporaryNode.setAttribute('readonly', '');
    temporaryNode.style.position = 'fixed';
    temporaryNode.style.opacity = '0';
    document.body.appendChild(temporaryNode);
    fallbackNode = temporaryNode;
  } else {
    fallbackNode.hidden = false;
  }
  fallbackNode.focus();
  fallbackNode.select();
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    temporaryNode?.remove();
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
    { wch: 12 }, { wch: 10 }, { wch: 20 }, { wch: 80 },
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
  for (let pageIndex = 0; pageIndex < COMMENT_PAGE_LIMIT && comments.length < COMMENT_LIMIT; pageIndex += 1) {
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

async function extractCurrentComments(forceRefresh = false) {
  if (!currentVideo?.shareUrl) return;
  const existingText = commentText.value.trim();
  if (existingText && !forceRefresh) {
    const copied = await copyText(existingText, commentText);
    showCommentStatus(copied ? '评论区内容已复制到剪贴板。' : '请长按或全选下方评论后复制。', copied ? '' : 'error');
    return;
  }

  const video = { ...currentVideo };
  const isLocalPage = ['127.0.0.1', 'localhost'].includes(location.hostname);
  if (!isLocalPage) {
    const bridgeUrl = new URL(COMMENT_BRIDGE_URL);
    bridgeUrl.searchParams.set('url', video.shareUrl);
    bridgeUrl.searchParams.set('v', '20260814-1');
    const popup = window.open(bridgeUrl, 'siyumenghai-comment-bridge-v2', 'width=760,height=760');
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
    saveComments(video.shareUrl, text, currentCommentRows);
    commentButton.textContent = '复制评论';
    commentRefreshButton.hidden = false;
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
  commentRefreshButton.hidden = false;
  commentExcelButton.hidden = false;
  saveComments(currentVideo?.shareUrl, text, currentCommentRows);
  showCommentStatus(String(event.data.message || '评论已提取并复制。'));
});

async function transcribeCurrentVideo() {
  if (!currentVideo?.shareUrl) return;
  const video = { ...currentVideo };
  if (currentTranscript?.corrected) {
    const copied = await copyText(currentTranscript.corrected);
    showTranscriptStatus(copied ? '逐字稿已复制到剪贴板。' : '请长按或全选下方逐字稿后复制。', copied ? '' : 'error');
    return;
  }

  const existingTask = transcriptTask(video.shareUrl);
  if (isActiveTranscriptTask(existingTask)) {
    transcriptButton.textContent = '查看后台进度';
    showTranscriptTaskStatus(existingTask);
    await pollTranscriptTask(existingTask);
    ensureTranscriptMonitor();
    return;
  }

  transcriptButton.disabled = true;
  showTranscriptStatus('正在提交服务器识别任务…', 'working');
  try {
    const response = await fetch(TRANSCRIPT_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        share_url: video.shareUrl,
        video_url: video.url,
        description: video.description,
        author: video.author
      })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `服务器返回 ${response.status}`);
    const task = {
      shareUrl: video.shareUrl,
      jobId: payload.id,
      status: payload.status || 'queued',
      stage: payload.stage || '',
      ahead: Number(payload.ahead || 0),
      createdAt: Date.now(),
      video: {
        shareUrl: video.shareUrl,
        description: video.description,
        author: video.author
      }
    };
    saveTranscriptTask(task);
    renderHistory();
    await applyTranscriptPayload(payload, task);
    ensureTranscriptMonitor();
  } catch (error) {
    if (currentVideo?.shareUrl === video.shareUrl) {
      transcriptButton.textContent = '重新生成逐字稿';
      showTranscriptStatus(`逐字稿生成失败：${error.message}`, 'error');
    }
  } finally {
    if (currentVideo?.shareUrl === video.shareUrl) transcriptButton.disabled = false;
  }
}

function showTranscriptTaskStatus(task) {
  if (!task) return;
  if (task.status === 'error') {
    showTranscriptStatus(`逐字稿识别失败：${task.error || '请重新生成'}`, 'error');
    return;
  }
  if (task.status === 'queued') {
    const ahead = Number(task.ahead || 0);
    showTranscriptStatus(ahead > 0
      ? `任务已在后台排队，前面还有 ${ahead} 条；现在可以继续查询其他视频。`
      : '任务已在后台排队；现在可以继续查询其他视频。', 'working');
    return;
  }
  showTranscriptStatus(`${task.stage || '服务器正在后台生成逐字稿'}；现在可以继续查询其他视频。`, 'working');
}

function transcriptCompletionMessage(payload, result) {
  const cacheText = payload.cached ? '（已读取缓存）' : '';
  const seconds = Number(payload.elapsed || 0);
  const timeText = seconds > 0
    ? `，服务器用时 ${seconds < 60 ? `${Math.ceil(seconds)} 秒` : `${Math.round(seconds / 60)} 分钟`}`
    : '';
  const correctionText = result.calibrationStatus === 'applied'
    ? `，智能校准 ${result.calibrationChanges} 处（原始识别稿已保留）`
    : result.calibrationStatus === 'fallback'
    ? '，智能校准暂未完成，当前已保留基础校正稿和原始识别稿，可稍后重新生成'
    : (result.correctionCount
      ? `，脚本结合专名和常用表达校正 ${result.correctionCount} 处`
      : '，暂未命中词库校正项，仍建议对照口播复核');
  return `逐字稿已在后台生成${cacheText}${timeText}${correctionText}，请点击“复制逐字稿”。`;
}

async function applyTranscriptPayload(payload, originalTask) {
  const task = {
    ...originalTask,
    status: payload.status || originalTask.status || 'running',
    stage: payload.stage || originalTask.stage || '',
    ahead: Number(payload.ahead || 0),
    error: payload.error || '',
    pollFailures: 0
  };

  if (task.status === 'completed') {
    const text = String(payload.text || '').trim();
    if (!text) throw new Error('服务器没有返回逐字稿');
    const video = task.video || { shareUrl: task.shareUrl };
    const result = buildTranscriptResult(payload, video);
    saveTranscript(task.shareUrl, result);
    removeTranscriptTask(task.shareUrl);
    renderHistory();
    if (currentVideo?.shareUrl === task.shareUrl) {
      currentTranscript = result;
      showTranscriptView('corrected');
      transcriptButton.disabled = false;
      transcriptButton.textContent = '复制逐字稿';
      showTranscriptStatus(transcriptCompletionMessage(payload, result));
    }
    return;
  }

  if (task.status === 'error') {
    saveTranscriptTask(task);
    renderHistory();
    if (currentVideo?.shareUrl === task.shareUrl) {
      transcriptButton.disabled = false;
      transcriptButton.textContent = '重新生成逐字稿';
      showTranscriptTaskStatus(task);
    }
    return;
  }

  saveTranscriptTask(task);
  renderHistory();
  if (currentVideo?.shareUrl === task.shareUrl) {
    transcriptButton.disabled = false;
    transcriptButton.textContent = '查看后台进度';
    showTranscriptTaskStatus(task);
  }
}

async function pollTranscriptTask(task) {
  if (!task?.jobId) return;
  try {
    const response = await fetch(`${TRANSCRIPT_API}/${encodeURIComponent(task.jobId)}`, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `服务器返回 ${response.status}`);
    await applyTranscriptPayload(payload, task);
  } catch (error) {
    const failures = Number(task.pollFailures || 0) + 1;
    const failedTask = {
      ...task,
      status: failures >= 3 ? 'error' : (task.status || 'running'),
      pollFailures: failures,
      error: error.message || '无法读取任务状态'
    };
    saveTranscriptTask(failedTask);
    renderHistory();
    if (currentVideo?.shareUrl === task.shareUrl) {
      if (failures >= 3) {
        transcriptButton.textContent = '重新生成逐字稿';
        showTranscriptTaskStatus(failedTask);
      } else {
        transcriptButton.textContent = '查看后台进度';
        showTranscriptStatus('暂时无法读取进度，服务器任务仍在后台运行，系统会自动重试。', 'working');
      }
    }
  }
}

async function monitorTranscriptTasks() {
  if (transcriptMonitorRunning) return;
  transcriptMonitorRunning = true;
  window.clearTimeout(transcriptMonitorTimer);
  try {
    const tasks = Object.values(readTranscriptTasks()).filter(isActiveTranscriptTask);
    await Promise.all(tasks.map((task) => pollTranscriptTask(task)));
  } finally {
    transcriptMonitorRunning = false;
    ensureTranscriptMonitor();
  }
}

function ensureTranscriptMonitor(delay = 5000) {
  window.clearTimeout(transcriptMonitorTimer);
  const hasActiveTasks = Object.values(readTranscriptTasks()).some(isActiveTranscriptTask);
  if (!hasActiveTasks) return;
  transcriptMonitorTimer = window.setTimeout(monitorTranscriptTasks, delay);
}

async function downloadVideo(url) {
  if (!currentVideo || !url) return;
  downloadButton.disabled = true;
  rawDownloadButton.disabled = true;
  const suggestedName = filename(currentVideo.description, currentVideo.createTime);
  let fileHandle = null;

  if (window.isSecureContext && 'showSaveFilePicker' in window) {
    try {
      fileHandle = await window.showSaveFilePicker({
        suggestedName,
        types: [{ description: 'MP4 视频', accept: { 'video/mp4': ['.mp4'] } }]
      });
    } catch (error) {
      if (error?.name === 'AbortError') {
        showStatus('已取消下载');
        downloadButton.disabled = false;
        rawDownloadButton.disabled = false;
        return;
      }
      fileHandle = null;
    }
  }

  showStatus('正在从视频源高速下载…');
  try {
    let response;
    try {
      response = await fetch(url, { mode: 'cors', credentials: 'omit' });
      if (!response.ok) throw new Error(`视频源返回 ${response.status}`);
    } catch (directError) {
      showStatus('视频源直连失败，正在切换备用下载通道…');
      response = await fetch(mediaProxyUrl(url));
      if (!response.ok) throw new Error(`备用通道返回 ${response.status}`);
    }

    if (fileHandle && response.body) {
      const writable = await fileHandle.createWritable();
      await response.body.pipeTo(writable);
      showStatus('视频已保存');
      return;
    }

    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = suggestedName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
    showStatus('下载已经开始');
  } catch (error) {
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.click();
    showStatus('浏览器已打开视频文件；如果没有自动保存，请长按视频或使用浏览器下载菜单。');
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
  const downloadUrl = highResolutionCoverUrl(url);
  try {
    const response = await fetch(imageProxyUrl(downloadUrl));
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
    link.href = imageProxyUrl(downloadUrl);
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
  window.clearTimeout(videoLoadTimer);
  videoNode.onerror = null;
  videoNode.onloadedmetadata = null;
  videoNode.removeAttribute('src');
  videoNode.load();
  currentVideo = null;
  showStatus('正在查询视频信息…');

  try {
    const payload = await queryVideoProfile(shareUrl);
    if (payload.errCode) throw new Error(payload.errMsg || '查询失败');
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
commentButton.addEventListener('click', () => extractCurrentComments(false));
commentRefreshButton.addEventListener('click', () => extractCurrentComments(true));
commentExcelButton.addEventListener('click', exportCommentsExcel);
commentStatus.addEventListener('click', async (event) => {
  const entry = event.target.closest('[data-local-helper-entry]');
  if (!entry || entry.dataset.helperAction === 'download') return;
  if (entry.dataset.helperAction === 'bridge') {
    extractCurrentComments(false);
    return;
  }
  event.preventDefault();
  if (entry.dataset.helperAction === 'running') {
    showCommentStatus('本地助手已经打开，可以直接提取评论。');
    return;
  }
  if (entry.dataset.helperAction !== 'launch') return;
  setLocalHelperEntry('正在打开…', 'checking');
  try {
    const payload = await localHelperRequest(LOCAL_HELPER_LAUNCH_API, { method: 'POST' });
    showCommentStatus(payload.running ? '本地助手已经运行，可以直接提取评论。' : '已打开本地助手终端，请按提示输入 Mac 密码并保持窗口运行。', payload.running ? '' : 'working');
  } catch {
    window.open('./local-comment-helper.html', '_blank', 'noopener');
    showCommentStatus('没有检测到可启动的本地助手，已打开下载说明。', 'error');
  }
});

historyList.addEventListener('click', async (event) => {
  const copyTarget = event.target.closest('[data-history-copy]');
  const transcriptTarget = event.target.closest('[data-history-transcript]');
  const commentsTarget = event.target.closest('[data-history-comments]');
  const queryTarget = event.target.closest('[data-history-query]');
  const deleteTarget = event.target.closest('[data-history-delete]');
  const items = readHistory();

  const showResult = (button, message) => {
    const original = button.textContent;
    button.textContent = message;
    window.setTimeout(() => {
      if (button.isConnected) button.textContent = original;
    }, 1600);
  };

  if (copyTarget) {
    const item = items[Number(copyTarget.dataset.historyCopy)];
    if (!item?.shareUrl) return;
    const copied = await copyText(item.shareUrl, null);
    showResult(copyTarget, copied ? '原视频链接已复制' : '复制失败，请重试');
  }

  if (transcriptTarget) {
    const item = items[Number(transcriptTarget.dataset.historyTranscript)];
    const transcript = item?.shareUrl ? cachedTranscript(item.shareUrl) : null;
    if (!transcript?.corrected) {
      const task = item?.shareUrl ? transcriptTask(item.shareUrl) : null;
      return showResult(transcriptTarget, task
        ? (task.status === 'error' ? '识别失败，请重新生成' : '后台识别中')
        : '暂无逐字稿');
    }
    const copied = await copyText(transcript.corrected, null);
    showResult(transcriptTarget, copied ? '逐字稿已复制' : '复制失败，请重试');
  }

  if (commentsTarget) {
    const item = items[Number(commentsTarget.dataset.historyComments)];
    const comments = item?.shareUrl ? cachedComments(item.shareUrl) : null;
    if (!comments?.text) return showResult(commentsTarget, '暂无评论记录');
    const copied = await copyText(comments.text, null);
    showResult(commentsTarget, copied ? '评论已复制' : '复制失败，请重试');
  }

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
renderLocalHelperPrompt();
ensureTranscriptMonitor(800);
