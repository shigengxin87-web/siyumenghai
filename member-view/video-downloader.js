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

let currentVideo = null;

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

function renderResult(payload) {
  const feedInfo = payload?.data?.feedInfo;
  const authorInfo = payload?.data?.authorInfo;
  const videoUrl = bestVideoUrl(feedInfo);
  if (!feedInfo || !videoUrl) throw new Error('没有找到可下载的视频，请确认分享链接是否有效');

  currentVideo = {
    url: videoUrl,
    rawUrl: rawVideoUrl(videoUrl),
    description: feedInfo.description || '',
    createTime: feedInfo.createtime || ''
  };

  videoNode.src = videoUrl;
  const coverUrl = validHttpUrl(feedInfo.coverUrl);
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
    renderResult(payload);
    showStatus('');
  } catch (error) {
    showStatus(`查询失败：${error.message}`, true);
  } finally {
    queryButton.disabled = false;
  }
});

downloadButton.addEventListener('click', () => downloadVideo(currentVideo?.url));
rawDownloadButton.addEventListener('click', () => downloadVideo(currentVideo?.rawUrl));
