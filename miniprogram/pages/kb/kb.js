const app = getApp()

Page({
  data: {
    items: [
      { key: 'feishu', icon: '📘', title: '飞书知识库', desc: '运营案例 · 行业拆解 · 专题沉淀', url: app.globalData.links.feishu, mode: 'copy' },
      { key: 'ima', icon: '🧠', title: '腾讯 ima 知识库', desc: 'AI 知识库问答 · 共享资料', url: app.globalData.links.ima, mode: 'copy' },
      { key: 'video', icon: '🎬', title: '视频号下载', desc: '原生预览并保存到相册', platform: 'channels', mode: 'media' }
    ]
  },

  onTap(e) {
    const key = e.currentTarget.dataset.key
    const item = this.data.items.find(i => i.key === key)
    if (!item) return
    if (item.mode === 'media') {
      wx.navigateTo({ url: '/pages/media/index?platform=' + item.platform })
    } else if (item.mode === 'webview') {
      wx.navigateTo({ url: '/pages/webview/webview?url=' + encodeURIComponent(item.url) })
    } else {
      wx.setClipboardData({
        data: item.url,
        success: () => wx.showToast({ title: '链接已复制，去浏览器打开', icon: 'none' })
      })
    }
  }
})
