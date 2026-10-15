const { parse, detect } = require('../../utils/media-api');
const { AlbumSaver } = require('../../utils/album-saver');
const mediaHistory = require('../../utils/media-history');
const names = { channels: '视频号', douyin: '抖音', xhs: '小红书' };
const states = { idle: '待保存', queued: '排队中', downloading: '下载中', saving: '正在写入相册', saved: '已保存到相册', failed: '保存失败', cancelled: '已取消' };
Page({
  data: { platform: 'channels', name: '视频号', names, input: '', parsing: false, saving: false, post: null, items: [], message: '', permissionDenied: false, history: [] },
  onLoad(options) {
    const platform = names[options.platform] ? options.platform : 'channels';
    this.setData({ platform, name: names[platform], history: mediaHistory.load() });
    this.requestTask = {};
    this.saver = new AlbumSaver(wx, (key, patch) => {
      if (this.closed) return;
      const items = this.data.items.map(item => {
        if (item.key !== key) return item;
        if (patch.cancelPending) return ['queued', 'downloading', 'idle'].includes(item.state) ? { ...item, state: 'cancelled', status: states.cancelled } : item;
        return { ...item, ...patch, status: states[patch.state] || item.status };
      });
      this.setData({ items });
    });
  },
  onUnload() { this.closed = true; this.generation = (this.generation || 0) + 1; this.saver.cancel(); if (this.requestTask.current) this.requestTask.current.abort(); },
  input(e) { this.setData({ input: e.detail.value }); },
  switchPlatform(e) {
    if (this.data.parsing || this.data.saving) return;
    const platform = e.currentTarget.dataset.platform;
    this.setData({ platform, name: names[platform], post: null, items: [], message: '' });
  },
  async parse() {
    if (this.data.parsing || this.data.saving) return;
    const generation = this.generation = (this.generation || 0) + 1;
    const platform = detect(this.data.input, this.data.platform);
    this.setData({ platform, name: names[platform], parsing: true, message: '正在解析作品…', post: null, items: [] });
    try {
      const post = await parse(wx, this.data.platform, this.data.input, this.requestTask);
      if (this.closed || generation !== this.generation) return;
      const history = mediaHistory.save(post, this.data.input, this.data.platform);
      this.setData({ post, items: post.items.map(item => ({ ...item, state: 'idle', status: states.idle, progress: 0 })), message: `已找到 ${post.items.length} 个文件`, history });
    } catch (e) { if (!this.closed && generation === this.generation) this.setData({ message: e.message }); }
    finally { if (!this.closed && generation === this.generation) this.setData({ parsing: false }); }
  },
  useHistory(e) {
    if (this.data.parsing || this.data.saving) return;
    const id = e.currentTarget.dataset.id;
    const item = this.data.history.find(i => i.id === id);
    if (!item) return;
    this.setData({ input: item.url, platform: item.platform, name: names[item.platform], post: null, items: [], message: '' });
    if (item.post && Date.now() - item.createdAt < 20 * 60 * 1000) {
      this.setData({ post: item.post, items: item.post.items.map(i => ({ ...i, state: 'idle', status: states.idle, progress: 0 })), message: '已读取最近解析，链接失效时可重新解析' });
    } else this.parse();
  },
  clearHistory() {
    if (this.data.parsing || this.data.saving) return;
    wx.showModal({
      title: '清空最近解析',
      content: '清空后不可恢复，确定吗？',
      success: (r) => {
        if (r.confirm) {
          mediaHistory.clear();
          this.setData({ history: [] });
        }
      }
    });
  },
  cancel() {
    if (this.data.parsing) { this.generation++; this.requestTask.current.abort(); this.setData({ parsing: false, message: '已取消解析，可重新尝试' }); }
    if (this.data.saving) { this.saver.cancel(); this.setData({ message: '正在取消；已经开始的相册写入将完成' }); }
  },
  preview(e) {
    const images = this.data.items.filter(i => i.kind === 'image').map(i => i.url);
    wx.previewImage({ current: e.currentTarget.dataset.url, urls: images });
  },
  mediaError() { this.setData({ message: '预览加载失败，可重试保存；链接过期时请重新解析' }); },
  async save(e) {
    if (this.data.saving || this.data.parsing) return;
    const key = e.currentTarget.dataset.key;
    const items = this.data.items.filter(i => (!key || i.key === key) && i.state !== 'saved');
    if (!items.length) return;
    this.setData({ saving: true, message: '正在检查相册权限…', permissionDenied: false });
    try {
      const result = await this.saver.run(items);
      if (!this.closed && result) this.setData({ message: `${result.cancelled ? '已取消后续保存。' : ''}本次已保存 ${result.saved} 个，失败 ${result.failed} 个。${result.failed ? '再次保存只处理未成功项。' : ''}` });
    } catch (err) { if (!this.closed) this.setData({ message: err.message || '保存未完成，请重试', permissionDenied: !!err.permission }); }
    finally { if (!this.closed) this.setData({ saving: false }); }
  },
  settings() { wx.openSetting({ success: r => this.setData({ permissionDenied: !r.authSetting['scope.writePhotosAlbum'], message: r.authSetting['scope.writePhotosAlbum'] ? '相册权限已开启，请再次点击保存' : '相册权限尚未开启' }) }); },
  privacy() { wx.openPrivacyContract({ fail: () => this.setData({ message: '隐私保护指引暂不可用，请联系管理员配置' }) }); },
  onShareAppMessage() { return { title: `${this.data.name}作品预览与保存`, path: `/pages/media/index?platform=${this.data.platform}` }; }
});
