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
const historySection = document.querySelector('[data-download-history]');
const historyList = document.querySelector('[data-history-list]');
const clearHistoryButton = document.querySelector('[data-clear-history]');

const HISTORY_KEY = 'siyumenghai-video-download-history-v1';
const HISTORY_LIMIT = 20;

let currentVideo = null;

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
