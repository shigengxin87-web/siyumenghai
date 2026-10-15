const ORIGIN = 'https://siyumenghai.cn';
function sameOrigin(path) {
  if (typeof path !== 'string') return '';
  const value = path.startsWith('/') && !path.startsWith('//') ? ORIGIN + path : path;
  if (!value.startsWith(ORIGIN + '/api/')) throw new Error('媒体地址无效，请重新解析');
  return value;
}
function proxy(raw, image) {
  if (!/^https:\/\//.test(raw || '')) return '';
  return `${ORIGIN}/api/transcripts/${image ? 'images' : 'media'}?url=${encodeURIComponent(raw)}`;
}
function normalize(platform, payload) {
  if (payload.error || (typeof payload.code === 'number' && payload.code !== 0)) throw new Error(payload.error || payload.msg || '解析失败');
  let p = payload;
  if (platform === 'channels') {
    const data = payload.data && payload.data.feedInfo ? payload.data : payload.data && payload.data.data || {};
    const f = data.feedInfo;
    if (!f || (payload.data && payload.data.errCode)) throw new Error('未找到作品，请检查分享链接');
    p = { title: f.description, description: f.description, author: data.authorInfo && data.authorInfo.nickname,
      stats: { digg_count: f.likeCount, comment_count: f.commentCount, share_count: f.forwardCount },
      cover: proxy(f.coverUrl, true), video: proxy(f.h264VideoInfo && f.h264VideoInfo.videoUrl || f.videoUrl, false), images: [] };
  }
  if (p.kind === 'author') throw new Error('请粘贴单条作品链接，暂不支持主页');
  const media = value => {
    const url = sameOrigin(value);
    return platform === 'xhs' && url ? url + (url.includes('?') ? '&' : '?') + 'proxy=1' : url;
  };
  const stats = platform === 'xhs' ? { digg_count: p.stats && p.stats.liked || undefined, comment_count: p.stats && p.stats.commented || undefined, share_count: p.stats && p.stats.shared || undefined, collect_count: p.stats && p.stats.collected || undefined } : p.stats || {};
  const items = [];
  if (p.video) items.push({ key: 'video', kind: 'video', url: media(p.video), label: '视频' });
  (p.images || []).forEach((url, i) => items.push({ key: `image-${i}`, kind: 'image', url: media(url), label: `图片 ${i + 1}` }));
  if (!items.length) throw new Error('作品未返回可保存资源');
  return { title: p.title || p.description || '作品预览', description: p.description || '',
    author: typeof p.author === 'string' ? p.author : p.author && p.author.nickname || '',
    cover: p.cover ? media(p.cover) : '', stats, items };
}
function detect(input, fallback) {
  const match = String(input || '').match(/https:\/\/([^/\s]+)/);
  const host = match && match[1].toLowerCase();
  if (host && /(^|\.)douyin\.com$|(^|\.)iesdouyin\.com$/.test(host)) return 'douyin';
  if (host && /(^|\.)xiaohongshu\.com$|(^|\.)xhslink\.com$/.test(host)) return 'xhs';
  if (host && /(^|\.)weixin\.qq\.com$|(^|\.)channels\.weixin\.qq\.com$/.test(host)) return 'channels';
  return fallback;
}
function parse(wxApi, platform, input, task) {
  const match = String(input || '').match(/https:\/\/[^\s<>"，。]+/);
  if (!match) return Promise.reject(new Error('请粘贴包含 https 链接的分享文案'));
  const url = match[0];
  const endpoint = platform === 'channels' ? `/api/video/profile?url=${encodeURIComponent(url)}` : `/api/${platform}/parse`;
  return new Promise((resolve, reject) => {
    task.current = wxApi.request({ url: ORIGIN + endpoint, method: platform === 'channels' ? 'GET' : 'POST', data: platform === 'channels' ? undefined : { url }, timeout: 120000,
      success: r => { try { if (r.statusCode !== 200) throw new Error(r.data && (r.data.error || r.data.msg) || `解析失败 (${r.statusCode})`); resolve(normalize(platform, r.data)); } catch (e) { reject(e); } },
      fail: () => reject(new Error('请求未完成，请检查网络后重试')) });
  });
}
module.exports = { normalize, parse, sameOrigin, detect };
