const DEFAULT_URL = 'https://siyumenghai.cn/member-view/video-downloader-20260808-17.html';

Page({
  data: { url: '', title: '', failed: false, copied: false },

  onLoad(options) {
    const requestedUrl = decodeURIComponent(options.url || DEFAULT_URL);
    const allowedPrefixes = [
      'https://siyumenghai.cn/',
      'https://my.feishu.cn/',
    ];
    const url = allowedPrefixes.some((prefix) => requestedUrl.startsWith(prefix)) ? requestedUrl : DEFAULT_URL;
    const title = decodeURIComponent(options.title || '视频号下载');
    wx.setNavigationBarTitle({ title });
    this.copyOnError = options.copyOnError === '1';
    this.setData({ url, title });
  },

  onWebError() {
    this.setData({ failed: true });
    if (this.copyOnError) {
      wx.setClipboardData({
        data: this.data.url,
        success: () => this.setData({ copied: true }),
      });
    }
  },

  copyUrl() {
    wx.setClipboardData({ data: this.data.url });
  },
});
