// 三平台作品解析历史记录（本地缓存）
const KEY = 'media_parse_history_v1';
const MAX = 50;

function extractUrl(input) {
  const m = String(input || '').match(/https:\/\/[^\s<>"，。]+/);
  return m ? m[0] : '';
}

function load() {
  try { const data = wx.getStorageSync(KEY); return Array.isArray(data) ? data : []; } catch (_) { return []; }
}

function normalize(post, input, platform) {
  const url = extractUrl(input) || extractUrl(post.description || '') || extractUrl(post.title || '');
  return {
    id: 'h' + Date.now(),
    platform,
    title: (post.title || '未命名作品').slice(0, 80),
    author: (post.author || '').slice(0, 40),
    cover: post.cover || '',
    url,
    post, createdAt: Date.now()
  };
}

function save(post, input, platform) {
  const item = normalize(post, input, platform);
  let list = load();
  if (item.url) {
    list = list.filter(i => i.url !== item.url);
  } else {
    // 没有可稳定去重的 URL，则限制同一标题不重复
    list = list.filter(i => i.title !== item.title || i.platform !== item.platform);
  }
  list.unshift(item);
  if (list.length > MAX) list = list.slice(0, MAX);
  try { wx.setStorageSync(KEY, list); } catch (_) {}
  return list;
}

function clear() {
  try { wx.removeStorageSync(KEY); } catch (_) {}
}

module.exports = { load, save, clear };
