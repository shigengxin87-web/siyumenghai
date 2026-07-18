const batchModeButtons = document.querySelectorAll('[data-mode-button]');
const batchModePanels = document.querySelectorAll('[data-mode-panel]');
const batchInput = document.querySelector('[data-batch-input]');
const batchFile = document.querySelector('[data-batch-file]');
const batchFileName = document.querySelector('[data-batch-file-name]');
const batchCount = document.querySelector('[data-batch-count]');
const batchStartButton = document.querySelector('[data-batch-start]');
const batchStatus = document.querySelector('[data-batch-status]');
const batchProgress = document.querySelector('[data-batch-progress]');
const batchSummary = document.querySelector('[data-batch-summary]');
const batchProgressBar = document.querySelector('[data-batch-progress-bar]');
const batchPauseButton = document.querySelector('[data-batch-pause]');
const batchCancelButton = document.querySelector('[data-batch-cancel]');
const batchResults = document.querySelector('[data-batch-results]');
const batchResultList = document.querySelector('[data-batch-result-list]');
const batchExportButton = document.querySelector('[data-batch-export]');
const batchDownloadAllButton = document.querySelector('[data-batch-download-all]');

const BATCH_LIMIT = 100;
const BATCH_CONCURRENCY = 2;
const BATCH_RETRIES = 1;
const BATCH_TIMEOUT = 30000;

let batchItems = [];
let batchLinkNotes = new Map();
let batchRunning = false;
let batchPaused = false;
let batchCancelled = false;
let batchResumeWaiters = [];
let batchControllers = new Set();

function batchDelay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function extractBatchLinks(text) {
  const matches = String(text || '').match(/https?:\/\/weixin\.qq\.com\/sph\/[a-z0-9_-]+/gi) || [];
  return [...new Set(matches.map((value) => value.replace(/[，。；、)）\]}】>》]+$/g, '')))];
}

function setBatchStatus(message, isError = false) {
  batchStatus.textContent = message;
  batchStatus.classList.toggle('is-error', isError);
  batchStatus.hidden = !message;
}

function currentBatchLinks() {
  return extractBatchLinks(batchInput.value).slice(0, BATCH_LIMIT);
}

function updateBatchCount() {
  const links = currentBatchLinks();
  const allLinks = extractBatchLinks(batchInput.value);
  batchCount.textContent = allLinks.length > BATCH_LIMIT
    ? `已识别 ${allLinks.length} 条，本次最多处理 ${BATCH_LIMIT} 条`
    : `已识别 ${links.length} 条链接`;
  batchStartButton.disabled = batchRunning || links.length === 0;
}

function switchBatchMode(mode) {
  batchModeButtons.forEach((button) => {
    const active = button.dataset.modeButton === mode;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-selected', String(active));
  });
  batchModePanels.forEach((panel) => {
    panel.hidden = panel.dataset.modePanel !== mode;
  });
  if (mode === 'single') {
    batchProgress.hidden = true;
    batchResults.hidden = true;
    if (currentVideo) resultNode.hidden = false;
  } else {
    resultNode.hidden = true;
    batchProgress.hidden = batchItems.length === 0;
    batchResults.hidden = batchItems.length === 0;
  }
}

function itemVideoUrl(feedInfo) {
  return validHttpUrl(feedInfo?.h264VideoInfo?.videoUrl)
    || validHttpUrl(feedInfo?.h265VideoInfo?.videoUrl)
    || validHttpUrl(feedInfo?.videoUrl);
}

function statusText(item) {
  if (item.status === 'pending') return '等待解析';
  if (item.status === 'working') return item.attempts > 1 ? '正在重试' : '正在解析';
  if (item.status === 'success') return '解析成功';
  if (item.status === 'cancelled') return '已取消';
  return item.error || '解析失败';
}

function renderBatchResults() {
  batchResultList.replaceChildren();
  batchItems.forEach((item, index) => {
    const row = document.createElement('article');
    row.className = 'batch-result-item';

    const number = document.createElement('span');
    number.className = 'batch-result-index';
    number.textContent = String(index + 1).padStart(2, '0');

    let cover;
    if (item.coverUrl) {
      cover = document.createElement('img');
      cover.src = item.coverUrl;
      cover.alt = '';
      cover.loading = 'lazy';
    } else {
      cover = document.createElement('div');
      cover.textContent = item.status === 'failed' ? '×' : '…';
    }
    cover.className = 'batch-result-cover';

    const main = document.createElement('div');
    main.className = 'batch-result-main';
    const title = document.createElement('strong');
    title.textContent = item.description || item.note || '等待获取视频信息';
    const meta = document.createElement('small');
    meta.textContent = item.author || item.url;
    main.append(title, meta);

    const state = document.createElement('span');
    state.className = `batch-result-status is-${item.status}`;
    state.textContent = statusText(item);

    const actions = document.createElement('div');
    actions.className = 'batch-result-buttons';
    const download = document.createElement('button');
    download.type = 'button';
    download.textContent = '下载';
    download.dataset.batchDownload = String(index);
    download.disabled = item.status !== 'success';
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.textContent = '重试';
    retry.dataset.batchRetry = String(index);
    retry.disabled = item.status !== 'failed';
    actions.append(download, retry);

    row.append(number, cover, main, state, actions);
    batchResultList.appendChild(row);
  });

  const successCount = batchItems.filter((item) => item.status === 'success').length;
  batchExportButton.disabled = batchItems.length === 0;
  batchDownloadAllButton.disabled = successCount === 0 || batchRunning;
}

function updateBatchProgress() {
  const total = batchItems.length;
  const completed = batchItems.filter((item) => ['success', 'failed', 'cancelled'].includes(item.status)).length;
  const success = batchItems.filter((item) => item.status === 'success').length;
  const failed = batchItems.filter((item) => item.status === 'failed').length;
  const percent = total ? Math.round((completed / total) * 100) : 0;
  batchProgressBar.style.width = `${percent}%`;
  batchSummary.textContent = `完成 ${completed}/${total} · 成功 ${success} · 失败 ${failed}`;
}

async function fetchBatchItem(item) {
  let lastError = new Error('解析失败');
  for (let attempt = 0; attempt <= BATCH_RETRIES; attempt += 1) {
    if (batchCancelled) throw new Error('已取消');
    item.attempts = attempt + 1;
    item.status = 'working';
    renderBatchResults();

    const controller = new AbortController();
    batchControllers.add(controller);
    const timer = window.setTimeout(() => controller.abort(), BATCH_TIMEOUT);
    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: item.url }),
        signal: controller.signal
      });
      const payload = await response.json();
      const feedInfo = payload?.data?.feedInfo;
      const videoUrl = itemVideoUrl(feedInfo);
      const upstreamMessage = payload?.data?.errMsg?.title || payload?.errMsg;
      if (!response.ok || payload?.errCode || !feedInfo || !videoUrl) {
        throw new Error(upstreamMessage || '没有找到可下载的视频');
      }
      item.status = 'success';
      item.author = payload?.data?.authorInfo?.nickname || '视频号作者';
      item.description = feedInfo.description || '该视频没有文字说明';
      item.coverUrl = validHttpUrl(feedInfo.coverUrl);
      item.videoUrl = videoUrl;
      item.rawUrl = rawVideoUrl(videoUrl);
      item.createTime = feedInfo.createtime || '';
      item.error = '';
      return;
    } catch (error) {
      lastError = error.name === 'AbortError' ? new Error('解析超时') : error;
      if (attempt < BATCH_RETRIES && !batchCancelled) await batchDelay(1200);
    } finally {
      window.clearTimeout(timer);
      batchControllers.delete(controller);
    }
  }
  throw lastError;
}

async function waitForBatchResume() {
  if (!batchPaused) return;
  await new Promise((resolve) => batchResumeWaiters.push(resolve));
}

async function batchWorker() {
  while (true) {
    await waitForBatchResume();
    if (batchCancelled) return;
    const item = batchItems.find((candidate) => candidate.status === 'pending');
    if (!item) return;
    item.status = 'working';
    try {
      await fetchBatchItem(item);
    } catch (error) {
      item.status = batchCancelled ? 'cancelled' : 'failed';
      item.error = batchCancelled ? '已取消' : error.message;
    }
    renderBatchResults();
    updateBatchProgress();
  }
}

async function runBatchQueue() {
  batchRunning = true;
  batchCancelled = false;
  batchPaused = false;
  batchPauseButton.textContent = '暂停';
  batchPauseButton.disabled = false;
  batchCancelButton.disabled = false;
  batchStartButton.disabled = true;
  batchProgress.hidden = false;
  batchResults.hidden = false;
  setBatchStatus('');
  renderBatchResults();
  updateBatchProgress();

  await Promise.all(Array.from({ length: Math.min(BATCH_CONCURRENCY, batchItems.length) }, () => batchWorker()));

  batchRunning = false;
  batchPauseButton.disabled = true;
  batchCancelButton.disabled = true;
  batchItems.forEach((item) => {
    if (item.status === 'pending' || item.status === 'working') item.status = batchCancelled ? 'cancelled' : 'failed';
  });
  renderBatchResults();
  updateBatchProgress();
  updateBatchCount();
  if (batchCancelled) setBatchStatus('批量任务已经取消');
  else setBatchStatus('批量解析完成');
}

function buildBatchItems() {
  return currentBatchLinks().map((url, index) => ({
    id: `${Date.now()}-${index}`,
    url,
    note: batchLinkNotes.get(url) || '',
    status: 'pending',
    attempts: 0,
    author: '',
    description: '',
    coverUrl: '',
    videoUrl: '',
    rawUrl: '',
    createTime: '',
    error: ''
  }));
}

async function importBatchWorkbook(file) {
  if (!window.XLSX) throw new Error('Excel 读取组件没有加载，请刷新页面后重试');
  const workbook = XLSX.read(await file.arrayBuffer(), { type: 'array' });
  const importedLinks = [];
  batchLinkNotes = new Map();
  workbook.SheetNames.forEach((sheetName) => {
    const rows = XLSX.utils.sheet_to_json(workbook.Sheets[sheetName], { header: 1, raw: false, defval: '' });
    rows.forEach((row) => {
      const rowLinks = extractBatchLinks(row.join(' '));
      rowLinks.forEach((url) => {
        importedLinks.push(url);
        const note = String(row[2] || '').trim();
        if (note) batchLinkNotes.set(url, note);
      });
    });
  });
  const combined = [...new Set([...currentBatchLinks(), ...importedLinks])];
  batchInput.value = combined.join('\n');
  batchFileName.textContent = `${file.name} · 导入 ${new Set(importedLinks).size} 条链接`;
  updateBatchCount();
  if (!importedLinks.length) throw new Error('表格中没有识别到视频号分享链接');
}

function recordBatchDownload(item) {
  const historyItem = {
    shareUrl: item.url,
    coverUrl: item.coverUrl,
    author: item.author,
    description: item.description,
    downloadedAt: new Date().toISOString()
  };
  const items = readHistory().filter((entry) => entry.shareUrl !== historyItem.shareUrl);
  writeHistory([historyItem, ...items]);
  renderHistory();
}

async function downloadBatchItem(item) {
  if (!item?.videoUrl) return;
  const response = await fetch(item.videoUrl);
  if (!response.ok) throw new Error(`下载服务器返回 ${response.status}`);
  const blobUrl = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = blobUrl;
  link.download = filename(item.description, item.createTime);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
  recordBatchDownload(item);
}

function exportBatchResults() {
  if (!window.XLSX || !batchItems.length) return;
  const rows = batchItems.map((item, index) => ({
    序号: index + 1,
    原始链接: item.url,
    解析状态: statusText(item),
    作者: item.author,
    视频标题: item.description,
    备注: item.note,
    封面链接: item.coverUrl,
    视频地址: item.videoUrl,
    失败原因: item.status === 'failed' ? item.error : ''
  }));
  const sheet = XLSX.utils.json_to_sheet(rows);
  sheet['!cols'] = [
    { wch: 8 }, { wch: 38 }, { wch: 14 }, { wch: 22 }, { wch: 45 },
    { wch: 20 }, { wch: 42 }, { wch: 42 }, { wch: 28 }
  ];
  sheet['!autofilter'] = { ref: sheet['!ref'] };
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, sheet, '批量解析结果');
  const stamp = new Date().toISOString().slice(0, 10).replaceAll('-', '');
  XLSX.writeFile(workbook, `视频号批量解析结果_${stamp}.xlsx`);
}

batchModeButtons.forEach((button) => {
  button.addEventListener('click', () => switchBatchMode(button.dataset.modeButton));
});

batchInput.addEventListener('input', updateBatchCount);

batchFile.addEventListener('change', async () => {
  const file = batchFile.files?.[0];
  if (!file) return;
  try {
    await importBatchWorkbook(file);
    setBatchStatus('Excel 导入成功');
  } catch (error) {
    setBatchStatus(`Excel 导入失败：${error.message}`, true);
  } finally {
    batchFile.value = '';
  }
});

batchStartButton.addEventListener('click', () => {
  if (batchRunning) return;
  batchItems = buildBatchItems();
  if (!batchItems.length) {
    setBatchStatus('请先粘贴链接或上传 Excel', true);
    return;
  }
  runBatchQueue();
});

batchPauseButton.addEventListener('click', () => {
  if (!batchRunning) return;
  batchPaused = !batchPaused;
  batchPauseButton.textContent = batchPaused ? '继续' : '暂停';
  if (!batchPaused) {
    batchResumeWaiters.splice(0).forEach((resolve) => resolve());
  }
});

batchCancelButton.addEventListener('click', () => {
  if (!batchRunning) return;
  batchCancelled = true;
  batchPaused = false;
  batchResumeWaiters.splice(0).forEach((resolve) => resolve());
  batchControllers.forEach((controller) => controller.abort());
});

batchResultList.addEventListener('click', async (event) => {
  const downloadTarget = event.target.closest('[data-batch-download]');
  const retryTarget = event.target.closest('[data-batch-retry]');
  if (downloadTarget) {
    const item = batchItems[Number(downloadTarget.dataset.batchDownload)];
    downloadTarget.disabled = true;
    try {
      await downloadBatchItem(item);
      setBatchStatus('下载已经开始');
    } catch (error) {
      setBatchStatus(`下载失败：${error.message}`, true);
    } finally {
      downloadTarget.disabled = false;
    }
  }
  if (retryTarget && !batchRunning) {
    const item = batchItems[Number(retryTarget.dataset.batchRetry)];
    if (!item) return;
    item.status = 'pending';
    item.error = '';
    batchRunning = true;
    renderBatchResults();
    await batchWorker();
    batchRunning = false;
    renderBatchResults();
    updateBatchProgress();
  }
});

batchExportButton.addEventListener('click', exportBatchResults);

batchDownloadAllButton.addEventListener('click', async () => {
  const successful = batchItems.filter((item) => item.status === 'success');
  batchDownloadAllButton.disabled = true;
  for (let index = 0; index < successful.length; index += 1) {
    setBatchStatus(`正在准备第 ${index + 1}/${successful.length} 个视频…`);
    try {
      await downloadBatchItem(successful[index]);
    } catch (error) {
      setBatchStatus(`第 ${index + 1} 个视频下载失败：${error.message}`, true);
    }
    await batchDelay(700);
  }
  batchDownloadAllButton.disabled = false;
  setBatchStatus('依次下载任务已完成；如果浏览器有提示，请允许多个文件下载');
});

updateBatchCount();
