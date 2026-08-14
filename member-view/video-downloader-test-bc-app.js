(function () {
  'use strict';

  const variant = String(document.documentElement.dataset.transcriptVariant || '').toLowerCase();
  if (!['b', 'c'].includes(variant)) throw new Error('B/C 逐字稿脚本只能用于测试 B 或 C');

  const productionC = document.documentElement.dataset.transcriptProduction === 'c';
  const apiBase = variant === 'b' ? 'http://127.0.0.1:8768/jobs' : '/api/transcripts-test-cloud/jobs';
  const locationLabel = variant === 'b' ? '本机处理用时' : '云端处理用时';
  const storagePrefix = productionC ? 'siyumenghai-video-production-c' : `siyumenghai-video-test-${variant}`;
  const payloadCacheKey = `${storagePrefix}-transcripts-deepseek-chat-bc-proofread-zh-v1.0.1`;
  const jobShareKey = `${storagePrefix}-transcript-job-share-v1`;
  const lastShareKey = `${storagePrefix}-last-transcript-share-v1`;
  const jobToShare = readJson(jobShareKey, {});
  let lastRenderedSignature = '';

  const style = document.createElement('style');
  style.textContent = `
    .bc-transcript-dual{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;margin-top:14px}
    .bc-transcript-dual[hidden]{display:none!important}
    .transcript-switch[data-transcript-switch],textarea[data-transcript-text]{display:none!important}
    .bc-transcript-pane{min-width:0;border:1px solid #dce8e3;border-radius:12px;background:#f8fcfa;padding:12px}
    .bc-transcript-pane header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px}
    .bc-transcript-pane header div{display:flex;flex-direction:column;gap:2px}.bc-transcript-pane header small{color:#64756f}
    .bc-transcript-actions{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
    .bc-transcript-pane textarea{display:block;width:100%;min-height:260px;box-sizing:border-box;resize:vertical;border:1px solid #cfddd7;border-radius:9px;background:white;padding:11px;color:#17241f;line-height:1.7;font:inherit}
    .bc-transcript-meta{grid-column:1/-1;margin:0;color:#53655f;font-size:13px;line-height:1.6}
    .bc-diff-details{grid-column:1/-1;border-top:1px solid #dce8e3;padding-top:10px}.bc-diff-details summary{cursor:pointer;font-weight:750;color:#067653}
    .bc-diff-list{display:grid;gap:8px;margin:10px 0 0;padding:0;list-style:none}.bc-diff-item{display:grid;grid-template-columns:24px 1fr;gap:8px;align-items:start;background:white;border:1px solid #e0eae6;border-radius:8px;padding:8px}
    .bc-diff-index{display:grid;place-items:center;width:22px;height:22px;border-radius:50%;background:#dff7eb;color:#067653;font-size:12px;font-weight:800}.bc-diff-item small{color:#73817c}.bc-diff-item p{margin:4px 0 0}.bc-diff-item del{color:#a43b3b;background:#fff0f0}.bc-diff-item ins{color:#067653;background:#eaf8f1;text-decoration:none}.bc-diff-empty{color:#64756f}
    @media(max-width:760px){.bc-transcript-dual{grid-template-columns:1fr}.bc-transcript-pane textarea{min-height:220px}}
  `;
  document.head.appendChild(style);

  const originalFetch = window.fetch.bind(window);
  window.fetch = async function bcTranscriptFetch(resource, options) {
    const response = await originalFetch(resource, options);
    try {
      const url = typeof resource === 'string' ? resource : resource?.url || '';
      if (isTranscriptUrl(url)) {
        const payload = await response.clone().json();
        capturePayload(url, options || {}, payload);
      }
    } catch {
      // The original request must remain unaffected by display instrumentation.
    }
    return response;
  };

  function isTranscriptUrl(url) {
    try {
      const parsed = new URL(url, location.href);
      return parsed.pathname.includes('/transcripts-test-cloud/jobs') || parsed.port === '8768';
    } catch {
      return false;
    }
  }

  function readJson(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(key) || 'null');
      return value && typeof value === 'object' ? value : fallback;
    } catch {
      return fallback;
    }
  }

  function writeJson(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* no-op */ }
  }

  function capturePayload(url, options, payload) {
    if (!payload?.id) return;
    let shareUrl = jobToShare[payload.id] || '';
    if (String(options.method || 'GET').toUpperCase() === 'POST' && options.body) {
      try { shareUrl = String(JSON.parse(options.body).share_url || shareUrl); } catch { /* no-op */ }
    }
    if (!shareUrl) {
      const tasks = readJson(`${storagePrefix}-transcript-tasks-v1`, {});
      shareUrl = Object.values(tasks).find((task) => task?.jobId === payload.id)?.shareUrl || '';
    }
    if (!shareUrl) shareUrl = document.querySelector('[data-share-url]')?.value.trim() || '';
    if (!shareUrl) return;
    jobToShare[payload.id] = shareUrl;
    writeJson(jobShareKey, jobToShare);
    if (payload.status === 'completed') {
      const cache = readJson(payloadCacheKey, {});
      cache[shareUrl] = { ...payload, share_url: shareUrl, saved_at: Date.now() };
      const entries = Object.entries(cache)
        .sort((left, right) => Number(right[1]?.saved_at || 0) - Number(left[1]?.saved_at || 0))
        .slice(0, 20);
      writeJson(payloadCacheKey, Object.fromEntries(entries));
      window.setTimeout(() => renderPayload(cache[shareUrl]), 0);
    }
  }

  function formatTime(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds < 0) return '—';
    return seconds < 60 ? `${seconds.toFixed(seconds < 10 ? 1 : 0)} 秒` : `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
  }

  function textCount(value) {
    return Array.from(String(value || '').replace(/\s/g, '')).length;
  }

  function createChangeItem(change, index) {
    const item = document.createElement('li');
    item.className = 'bc-diff-item';
    const indexNode = document.createElement('span');
    indexNode.className = 'bc-diff-index';
    indexNode.textContent = String(index + 1);
    const body = document.createElement('div');
    const context = document.createElement('small');
    context.textContent = `${change.context_before || ''}〔修改处〕${change.context_after || ''}`;
    const edit = document.createElement('p');
    const before = document.createElement('del');
    before.textContent = change.from || '∅';
    const arrow = document.createTextNode(' → ');
    const after = document.createElement('ins');
    after.textContent = change.to || '∅';
    edit.append(before, arrow, after);
    body.append(context, edit);
    item.append(indexNode, body);
    return item;
  }

  function renderPayload(payload) {
    const container = document.querySelector('[data-transcript-dual]');
    if (!container || payload?.status !== 'completed') return;
    const raw = String(payload.raw_text || '');
    const corrected = String(payload.corrected_text || '');
    if (!raw.trim()) return;
    const signature = `${payload.id}:${payload.correction_status}:${raw.length}:${corrected.length}:${payload.correction_count}`;
    const status = document.querySelector('[data-transcript-status]');
    const statusText = payload.correction_status === 'completed'
      ? `原始稿与 DeepSeek 校正稿均已完成，共修改 ${Number(payload.correction_count || 0)} 处。`
      : `原始识别稿已完整生成；DeepSeek 校正失败：${payload.correction_error || '请重试校正'}。`;
    if (signature === lastRenderedSignature) {
      if (status && status.textContent !== statusText) {
        status.textContent = statusText;
        status.classList.toggle('is-error', payload.correction_status !== 'completed');
        status.classList.remove('is-working');
      }
      return;
    }
    const rawNode = container.querySelector('[data-transcript-raw-text]');
    const correctedNode = container.querySelector('[data-transcript-corrected-text]');
    rawNode.value = raw;
    correctedNode.value = corrected;
    correctedNode.placeholder = payload.correction_status === 'failed'
      ? `DeepSeek 校正失败：${payload.correction_error || '可点击重试校正'}。原始识别稿不受影响。`
      : '';
    container.hidden = false;
    const action = document.querySelector('[data-transcript-action]');
    if (action) action.hidden = true;

    const rawCount = textCount(raw);
    const correctedCount = textCount(corrected);
    container.querySelector('[data-transcript-raw-count]').textContent = `${rawCount} 字`;
    container.querySelector('[data-transcript-corrected-count]').textContent = corrected ? `${correctedCount} 字` : '校正失败';
    const model = payload.correction_actual_model || payload.correction_model || '—';
    container.querySelector('[data-transcript-meta]').textContent =
      `${locationLabel}：ASR ${formatTime(payload.asr_elapsed)} · DeepSeek ${formatTime(payload.correction_elapsed)} · 总计 ${formatTime(payload.total_elapsed || payload.elapsed)}；模型 ${model}；提示词 ${payload.prompt_version || '—'}；原稿 ${rawCount} 字，校正稿 ${correctedCount} 字。`;

    const retry = container.querySelector('[data-transcript-retry]');
    retry.hidden = payload.correction_status === 'completed';
    retry.dataset.jobId = payload.id;
    const changes = Array.isArray(payload.correction_changes) ? payload.correction_changes : [];
    const details = container.querySelector('[data-transcript-diff]');
    details.querySelector('summary').textContent = `查看修改差异（${changes.length} 处，程序确定性比对）`;
    const list = details.querySelector('[data-transcript-diff-list]');
    list.replaceChildren(...changes.map(createChangeItem));
    if (!changes.length) {
      const empty = document.createElement('p');
      empty.className = 'bc-diff-empty';
      empty.textContent = payload.correction_status === 'completed' ? 'DeepSeek 未修改原始识别稿。' : '校正尚未成功，没有可展示的修改。';
      list.appendChild(empty);
    }

    if (status && status.textContent !== statusText) {
      status.textContent = statusText;
      status.classList.toggle('is-error', payload.correction_status !== 'completed');
      status.classList.remove('is-working');
    }
    lastRenderedSignature = signature;
  }

  function restoreForCurrentShare() {
    const shareUrl = document.querySelector('[data-share-url]')?.value.trim() || '';
    const payload = readJson(payloadCacheKey, {})[shareUrl];
    if (payload) renderPayload(payload);
  }

  async function copyFrom(selector, button) {
    const node = document.querySelector(selector);
    const value = node?.value || '';
    if (!value) return;
    let copied = false;
    try {
      copied = await navigator.clipboard.writeText(value).then(() => true, () => false);
    } catch { /* fallback below */ }
    if (!copied) {
      node.focus();
      node.select();
      try { copied = document.execCommand('copy'); } catch { copied = false; }
    }
    const original = button.textContent;
    button.textContent = copied ? '已复制' : '请手动复制';
    window.setTimeout(() => { button.textContent = original; }, 1400);
  }

  async function retryCorrection(button) {
    const jobId = button.dataset.jobId;
    if (!jobId) return;
    button.disabled = true;
    button.textContent = '正在重试…';
    try {
      const response = await window.fetch(`${apiBase}/${encodeURIComponent(jobId)}/correction`, {
        method: 'POST',
        ...(variant === 'b' ? { targetAddressSpace: 'loopback' } : {}),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `服务器返回 ${response.status}`);
      capturePayload(`${apiBase}/${jobId}/correction`, { method: 'POST' }, payload);
    } catch (error) {
      const status = document.querySelector('[data-transcript-status]');
      if (status) status.textContent = `DeepSeek 校正重试失败：${error.message}`;
    } finally {
      button.disabled = false;
      button.textContent = '重试校正';
    }
  }

  document.addEventListener('click', (event) => {
    const copy = event.target.closest('[data-transcript-copy-kind]');
    if (copy) {
      const selector = copy.dataset.transcriptCopyKind === 'raw'
        ? '[data-transcript-raw-text]' : '[data-transcript-corrected-text]';
      copyFrom(selector, copy);
      return;
    }
    const retry = event.target.closest('[data-transcript-retry]');
    if (retry) retryCorrection(retry);
  });
  document.addEventListener('submit', (event) => {
    if (!event.target.matches('[data-download-form]')) return;
    const container = document.querySelector('[data-transcript-dual]');
    if (container) container.hidden = true;
    const action = document.querySelector('[data-transcript-action]');
    if (action) action.hidden = false;
    const shareUrl = document.querySelector('[data-share-url]')?.value.trim() || '';
    if (shareUrl) {
      try { localStorage.setItem(lastShareKey, shareUrl); } catch { /* no-op */ }
    }
    lastRenderedSignature = '';
  }, true);

  const observer = new MutationObserver(() => {
    const result = document.querySelector('[data-video-result]');
    if (result && !result.hidden) restoreForCurrentShare();
  });
  observer.observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['hidden'] });

  const legacy = document.createElement('script');
  legacy.src = productionC
    ? './video-downloader-app.js?v=20260814-production-c-1'
    : './video-downloader-test-app.js?v=20260814-abc-1';
  legacy.onload = () => {
    restoreForCurrentShare();
    const navigation = performance.getEntriesByType('navigation')[0];
    if (navigation?.type !== 'reload') return;
    let shareUrl = '';
    try { shareUrl = localStorage.getItem(lastShareKey) || ''; } catch { /* no-op */ }
    if (!shareUrl || !readJson(payloadCacheKey, {})[shareUrl]) return;
    const input = document.querySelector('[data-share-url]');
    const form = document.querySelector('[data-download-form]');
    if (input && form) {
      input.value = shareUrl;
      form.requestSubmit();
    }
  };
  document.head.appendChild(legacy);
})();
