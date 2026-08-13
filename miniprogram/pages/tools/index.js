const SERVICES = {
  video: {
    title: '视频号下载',
    url: 'https://siyumenghai.cn/member-view/video-downloader-20260808-17.html',
  },
  ima: {
    title: 'IMA 知识库',
    url: 'https://ima.qq.com/wiki/?shareId=9ac78c43931491aa0c6bfff1ac1be9de7e4c81bc22cd066d2c2fd2cb2ffe2a79',
    appId: 'wx4c6401744b734596',
  },
  feishu: {
    title: '飞书知识库',
    url: 'https://my.feishu.cn/wiki/space/7663061611179003182?ccm_open_type=lark_wiki_spaceLink&open_tab_from=wiki_home',
  },
  website: {
    title: '社群官网',
    url: 'https://siyumenghai.cn/member-view/',
  },
};

Page({
  openWebService(service) {
    const url = encodeURIComponent(service.url);
    const title = encodeURIComponent(service.title);
    wx.navigateTo({
      url: `/pages/webview/index?url=${url}&title=${title}&copyOnError=1`,
      fail: () => this.copyWithHelp(service),
    });
  },

  openVideoTool() {
    this.openWebService(SERVICES.video);
  },

  openIma() {
    const service = SERVICES.ima;
    wx.navigateToMiniProgram({
      appId: service.appId,
      extraData: { shareId: service.url.split('shareId=')[1] },
      envVersion: 'release',
      fail: () => this.copyWithHelp(service),
    });
  },

  openFeishu() {
    const service = SERVICES.feishu;
    wx.setClipboardData({
      data: service.url,
      success: () => this.openWebService(service),
      fail: () => this.openWebService(service),
    });
  },

  copyWithHelp(service) {
    wx.setClipboardData({
      data: service.url,
      success: () => wx.showModal({
        title: `${service.title}链接已复制`,
        content: '微信未允许直接打开时，可粘贴到聊天或对应 App 中继续打开。',
        showCancel: false,
        confirmText: '知道了',
      }),
    });
  },

  copyWebsite() {
    this.copyWithHelp(SERVICES.website);
  },

  onShareAppMessage() {
    return { title: '石董会｜社群工具与知识库', path: '/pages/tools/index' };
  },
});
