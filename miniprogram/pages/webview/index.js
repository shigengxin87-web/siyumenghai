const DEFAULT_URL = 'https://siyumenghai.cn/member-view/video-downloader.html';

Page({
  data: { url: '', failed: false },

  onLoad(options) {
    const requestedUrl = decodeURIComponent(options.url || DEFAULT_URL);
    const url = requestedUrl.startsWith('https://siyumenghai.cn/') ? requestedUrl : DEFAULT_URL;
    const title = decodeURIComponent(options.title || '视频号下载');
    wx.setNavigationBarTitle({ title });
    this.setData({ url });
  },

  onWebError() {
    this.setData({ failed: true });
  },

  copyUrl() {
    wx.setClipboardData({ data: this.data.url });
  },
});
