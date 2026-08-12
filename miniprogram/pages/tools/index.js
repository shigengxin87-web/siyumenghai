const SERVICES = {
  video: {
    title: '视频号下载',
    url: 'https://siyumenghai.cn/member-view/video-downloader.html',
  },
  ima: {
    title: 'IMA 知识库',
    url: 'https://ima.qq.com/wiki/?shareId=9ac78c43931491aa0c6bfff1ac1be9de7e4c81bc22cd066d2c2fd2cb2ffe2a79',
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
  openVideoTool() {
    const url = encodeURIComponent(SERVICES.video.url);
    const title = encodeURIComponent(SERVICES.video.title);
    wx.navigateTo({ url: `/pages/webview/index?url=${url}&title=${title}` });
  },

  copyService(event) {
    const service = SERVICES[event.currentTarget.dataset.service];
    if (!service) return;
    wx.setClipboardData({
      data: service.url,
      success: () => wx.showModal({
        title: `${service.title}入口已复制`,
        content: '可粘贴到微信聊天或系统浏览器中打开。',
        showCancel: false,
        confirmText: '知道了',
      }),
    });
  },

  onShareAppMessage() {
    return { title: '石董会｜社群工具与知识库', path: '/pages/tools/index' };
  },
});
