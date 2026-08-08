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
const transcriptButton = document.querySelector('[data-transcript-action]');
const transcriptStatus = document.querySelector('[data-transcript-status]');
const transcriptText = document.querySelector('[data-transcript-text]');
const historySection = document.querySelector('[data-download-history]');
const historyList = document.querySelector('[data-history-list]');
const clearHistoryButton = document.querySelector('[data-clear-history]');

const HISTORY_KEY = 'siyumenghai-video-download-history-v1';
const HISTORY_LIMIT = 20;
const TRANSCRIPT_CACHE_KEY = 'siyumenghai-video-transcripts-v1';
const TRANSCRIPT_CACHE_LIMIT = 12;

let currentVideo = null;
let transcriptWorker = null;
let transcriptWorkerReady = false;
let transcriptPromise = null;

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
  return typeof item?.text === 'string' ? item.text : '';
}

function saveTranscript(shareUrl, text) {
  if (!shareUrl || !text) return;
  try {
    const cache = readTranscriptCache();
    cache[shareUrl] = { text, savedAt: Date.now() };
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
  historySection.hidden = items.length === 0;

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
    time.textContent = `下载于 ${historyTime(item.downloadedAt)}`;
    const actions = document.createElement('div');
    actions.className = 'history-actions';
    actions.innerHTML = `<button type="button" data-history-query="${index}">重新查询</button><button type="button" data-history-delete="${index}">删除</button>`;

    content.append(author, title, time, actions);
    article.append(cover, content);
    historyList.appendChild(article);
  });
}

function saveCurrentDownload() {
  if (!currentVideo?.shareUrl) return;
  const item = {
    shareUrl: currentVideo.shareUrl,
    coverUrl: currentVideo.coverUrl,
    author: currentVideo.author,
    description: currentVideo.description,
    downloadedAt: new Date().toISOString()
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

function showTranscriptStatus(message, state = '') {
  transcriptStatus.textContent = message;
  transcriptStatus.classList.toggle('is-working', state === 'working');
  transcriptStatus.classList.toggle('is-error', state === 'error');
}

function resetTranscript() {
  transcriptText.value = '';
  transcriptText.hidden = true;
  transcriptButton.disabled = false;
  transcriptButton.textContent = '生成并复制逐字稿';
  showTranscriptStatus('尽量保留原话、重复和语气词；人名、方言或多人重叠说话仍建议核对。');
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
  const previousTranscript = cachedTranscript(shareUrl);
  if (previousTranscript) {
    transcriptText.value = previousTranscript;
    transcriptText.hidden = false;
    transcriptButton.textContent = '复制逐字稿';
    showTranscriptStatus('已读取这条视频在当前浏览器保存的逐字稿。');
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
    showTranscriptStatus(`首次使用正在下载识别模型，当前文件 ${percent}%（下载一次后会缓存）`, 'working');
  } else if (message.status === 'loading') {
    showTranscriptStatus(message.data || '正在载入语音识别模型…', 'working');
  }
}

async function ensureTranscriptWorker() {
  if (transcriptWorkerReady && transcriptWorker) return transcriptWorker;
  if (transcriptPromise) return transcriptPromise;

  transcriptPromise = new Promise((resolve, reject) => {
    const worker = new Worker('./video-transcript-worker.js?v=20260808-2', { type: 'module' });
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

async function copyText(value) {
  try {
    const copied = await Promise.race([
      navigator.clipboard.writeText(value).then(() => true, () => false),
      new Promise((resolve) => window.setTimeout(() => resolve(false), 1500))
    ]);
    if (copied) return true;
  } catch {
    // Fall back to selecting the visible transcript below.
  }
  transcriptText.hidden = false;
  transcriptText.focus();
  transcriptText.select();
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  }
}

async function transcribeCurrentVideo() {
  if (!currentVideo?.url) return;
  const video = { ...currentVideo };
  const existingText = transcriptText.value.trim();
  if (existingText) {
    const copied = await copyText(existingText);
    showTranscriptStatus(copied ? '逐字稿已复制到剪贴板。' : '请长按或全选下方逐字稿后复制。', copied ? '' : 'error');
    return;
  }

  transcriptButton.disabled = true;
  transcriptButton.textContent = '正在生成…';
  try {
    const audio = await videoAudio(video.url);
    const worker = await ensureTranscriptWorker();
    showTranscriptStatus('正在逐字识别，请保持页面打开…', 'working');
    const result = await new Promise((resolve, reject) => {
      const handleMessage = (event) => {
        if (event.data?.status === 'complete') {
          worker.removeEventListener('message', handleMessage);
          resolve(event.data.result);
        } else if (event.data?.status === 'error') {
          worker.removeEventListener('message', handleMessage);
          reject(new Error(event.data.message || '逐字稿识别失败'));
        }
      };
      worker.addEventListener('message', handleMessage);
      worker.postMessage({ type: 'run', data: { audio, language: 'zh' } }, [audio.buffer]);
    });

    const text = String(result?.text || '').trim();
    if (!text) throw new Error('没有识别到清晰的人声');
    if (currentVideo?.shareUrl !== video.shareUrl) return;
    transcriptText.value = text;
    transcriptText.hidden = false;
    saveTranscript(video.shareUrl, text);
    transcriptButton.textContent = '复制逐字稿';
    const copied = await copyText(text);
    showTranscriptStatus(copied ? '逐字稿已生成并复制到剪贴板。' : '逐字稿已生成，请再次点击“复制逐字稿”。', copied ? '' : 'error');
  } catch (error) {
    transcriptButton.textContent = '重新生成逐字稿';
    showTranscriptStatus(`逐字稿生成失败：${error.message}`, 'error');
  } finally {
    transcriptButton.disabled = false;
  }
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
    saveCurrentDownload();
    showStatus('下载已经开始');
  } catch (error) {
    showStatus(`下载失败：${error.message}`, true);
  } finally {
    downloadButton.disabled = false;
    rawDownloadButton.disabled = false;
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
    showStatus('');
  } catch (error) {
    showStatus(`查询失败：${error.message}`, true);
  } finally {
    queryButton.disabled = false;
  }
});

downloadButton.addEventListener('click', () => downloadVideo(currentVideo?.url));
rawDownloadButton.addEventListener('click', () => downloadVideo(currentVideo?.rawUrl));
transcriptButton.addEventListener('click', transcribeCurrentVideo);

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
