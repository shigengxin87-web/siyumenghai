(function () {
  'use strict';

  const reader = document.querySelector('[data-transcript-reader]');
  const textarea = document.querySelector('[data-transcript-corrected-text]');
  const hint = document.querySelector('[data-transcript-seek-hint]');
  const video = document.querySelector('[data-video]');
  if (!reader || !textarea || !hint || !video) return;
  const requests = new Map();
  let currentPayload = null;
  let pendingSeek = null;
  let cues = [];

  const style = document.createElement('style');
  style.textContent = `
    .transcript-reader{min-height:360px;max-height:64vh;overflow:auto;box-sizing:border-box;padding:24px 26px;color:#1b2924;font:16px/1.9 ui-sans-serif,system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;letter-spacing:.015em;white-space:pre-wrap;overflow-wrap:anywhere}
    .transcript-reader[hidden],.final-transcript-result textarea[hidden]{display:none!important}
    .transcript-reader .transcript-cue{display:inline;border:0;border-radius:3px;background:transparent;padding:0;color:inherit;font:inherit;letter-spacing:inherit;white-space:pre-wrap;text-align:left;cursor:pointer;user-select:text}
    .transcript-reader .transcript-cue:hover,.transcript-reader .transcript-cue:focus-visible{background:#e3f8ed;outline:2px solid #81cdb0;outline-offset:2px}
    .transcript-reader .transcript-cue.is-current{background:#d9f3e5;color:#075e43}
    .transcript-seek-hint{margin:0;padding:10px 22px;color:#63736d;font-size:13px;line-height:1.6;border-bottom:1px solid #edf3f0}
    @media(max-width:760px){.transcript-reader{min-height:300px;padding:19px 18px;font-size:15px}.transcript-seek-hint{padding:10px 17px}}
  `;
  document.head.appendChild(style);

  function units(text) {
    const result = [];
    let offset = 0;
    for (const character of text) {
      if (!/\s/u.test(character)) result.push({ character, offset });
      offset += character.length;
    }
    return result;
  }

  // Match edits against actual recognized sentences; never estimate time by text length.
  function align(source, target) {
    const mapping = new Int32Array(target.length).fill(-1);
    let left = 0;
    let sourceEnd = source.length;
    let targetEnd = target.length;
    while (left < sourceEnd && left < targetEnd && source[left].character === target[left].character) {
      mapping[left] = left;
      left++;
    }
    while (sourceEnd > left && targetEnd > left && source[sourceEnd - 1].character === target[targetEnd - 1].character) {
      mapping[--targetEnd] = --sourceEnd;
    }
    const rows = sourceEnd - left;
    const columns = targetEnd - left;
    if ((rows + 1) * (columns + 1) > 4000000) return null;
    const width = columns + 1;
    const lengths = new Uint16Array((rows + 1) * width);
    for (let i = 1; i <= rows; i++) {
      for (let j = 1; j <= columns; j++) {
        lengths[i * width + j] = source[left + i - 1].character === target[left + j - 1].character
          ? lengths[(i - 1) * width + j - 1] + 1
          : Math.max(lengths[(i - 1) * width + j], lengths[i * width + j - 1]);
      }
    }
    let i = rows;
    let j = columns;
    while (i > 0 && j > 0) {
      if (source[left + i - 1].character === target[left + j - 1].character) {
        mapping[left + j - 1] = left + i - 1;
        i--; j--;
      } else if (lengths[(i - 1) * width + j] >= lengths[i * width + j - 1]) i--;
      else j--;
    }
    return mapping;
  }

  function timeLabel(seconds) {
    const value = Math.floor(seconds);
    return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
  }

  function sameVideo(payload) {
    return payload?.share_url === document.querySelector('[data-video-result]')?.dataset.videoShareUrl;
  }

  async function loadTiming(payload) {
    if (requests.has(payload.id)) return;
    const request = window.fetch(`/api/transcripts-test-tencent/jobs/${encodeURIComponent(payload.id)}/timing`, { cache: 'no-store' });
    requests.set(payload.id, request);
    try {
      const response = await request;
      if (!response.ok) throw new Error('timing unavailable');
      const next = await response.json();
      if (next.id !== payload.id || next.status !== 'completed') throw new Error('invalid timing response');
      if (currentPayload?.id === payload.id && sameVideo(next)) render(next, textarea.value, !textarea.readOnly);
    } catch {
      requests.delete(payload.id);
      if (currentPayload?.id !== payload.id || !sameVideo(payload)) return;
      hint.replaceChildren(document.createTextNode('暂时无法加载句子定位。'));
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.textContent = '重试定位';
      retry.addEventListener('click', () => { hint.textContent = '正在加载句子定位…'; loadTiming(payload); });
      hint.appendChild(retry);
    }
  }

  function render(payload, text, editing) {
    currentPayload = payload;
    cues = [];
    reader.hidden = true;
    textarea.hidden = false;
    reader.replaceChildren();
    hint.hidden = false;
    const segments = (Array.isArray(payload.segments) ? payload.segments : []).filter(segment =>
      typeof segment.text === 'string' && Number.isFinite(segment.start) && Number.isFinite(segment.end)
      && segment.start >= 0 && segment.end > segment.start);
    if (!segments.length) {
      hint.textContent = payload.timing_status === 'unavailable'
        ? '这份旧逐字稿未保存句子时间，暂不支持点击定位。'
        : '正在加载句子定位…';
      if (payload.timing_status !== 'unavailable') loadTiming(payload);
      return;
    }
    if (editing) {
      hint.textContent = '编辑中；保存后可点击文案回听对应视频。';
      return;
    }
    const source = segments.flatMap((segment, index) => units(segment.text).map(unit => ({ ...unit, segment: index })));
    const target = units(text);
    const mapping = align(source, target);
    if (!mapping || (target.length && Array.from(mapping).filter(index => index >= 0).length / target.length < 0.7)) {
      hint.textContent = '文案改动较大，暂时无法可靠定位；已保留完整文案。';
      return;
    }
    const owners = Array.from(mapping, index => index < 0 ? -1 : source[index].segment);
    // Small corrections inside one recognized sentence keep that sentence's real start time.
    for (let index = 0; index < owners.length;) {
      if (owners[index] >= 0) { index++; continue; }
      const start = index;
      while (index < owners.length && owners[index] < 0) index++;
      const before = owners[start - 1];
      const after = owners[index];
      if (index - start <= 12 && before >= 0 && before === after) owners.fill(before, start, index);
    }
    let offset = 0;
    let index = 0;
    while (index < target.length) {
      const owner = owners[index];
      let end = index + 1;
      while (end < target.length && owners[end] === owner) end++;
      const nextOffset = end < target.length ? target[end].offset : text.length;
      const value = text.slice(offset, nextOffset);
      if (owner >= 0) {
        const segment = segments[owner];
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'transcript-cue';
        button.textContent = value;
        button.dataset.seekStart = String(segment.start);
        button.title = `从 ${timeLabel(segment.start)} 回听`;
        button.addEventListener('click', () => {
          if (!window.getSelection()?.isCollapsed || !sameVideo(payload)) return;
          pendingSeek = { shareUrl: payload.share_url, start: segment.start };
          seek();
        });
        cues.push({ button, start: segment.start, end: segment.end });
        reader.appendChild(button);
      } else reader.appendChild(document.createTextNode(value));
      offset = nextOffset;
      index = end;
    }
    if (!target.length) reader.textContent = text;
    if (!cues.length) {
      hint.textContent = '当前文案没有可可靠对应的句子，暂不支持点击定位。';
      return;
    }
    reader.hidden = false;
    textarea.hidden = true;
    hint.textContent = owners.includes(-1)
      ? '点击文案回听对应视频；部分新增文字暂无定位。'
      : '点击任意一句文案，回听对应视频。';
    highlight();
  }

  function seek() {
    if (!pendingSeek || pendingSeek.shareUrl !== document.querySelector('[data-video-result]')?.dataset.videoShareUrl) return;
    if (video.readyState < 1) {
      hint.textContent = '正在等待视频加载，加载后会跳到所选句子。';
      return;
    }
    const start = pendingSeek.start;
    pendingSeek = null;
    if (Number.isFinite(video.duration) && start >= video.duration) {
      hint.textContent = '该句时间超出当前视频时长，请重新查询视频后再试。';
      return;
    }
    video.currentTime = start;
    hint.textContent = `已定位到 ${timeLabel(start)}。`;
    video.play().catch(() => { hint.textContent = `已定位到 ${timeLabel(start)}，点击播放器即可播放。`; });
    video.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    highlight();
  }

  function highlight() {
    for (const cue of cues) {
      const active = video.currentTime >= cue.start && video.currentTime < cue.end;
      cue.button.classList.toggle('is-current', active);
      if (active) cue.button.setAttribute('aria-current', 'true');
      else cue.button.removeAttribute('aria-current');
    }
  }
  video.addEventListener('loadedmetadata', seek);
  video.addEventListener('timeupdate', highlight);
  video.addEventListener('error', () => {
    if (pendingSeek) hint.textContent = '视频暂时无法播放，请重新查询视频后再定位。';
  });
  window.videoTranscriptSeek = {
    render,
    setEditing(editing) { if (currentPayload) render(currentPayload, textarea.value, editing); },
    clear() { currentPayload = null; pendingSeek = null; cues = []; reader.replaceChildren(); reader.hidden = true; hint.hidden = true; textarea.hidden = false; },
  };
})();
