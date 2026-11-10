const app = getApp()

Page({
  data: {
    items: [
      { key: 'feishu', icon: '📘', title: '飞书知识库', desc: '运营案例 · 行业拆解 · 专题沉淀', url: app.globalData.links.feishu, mode: 'copy' },
      { key: 'ima', icon: '🧠', title: '腾讯 ima 知识库', desc: 'AI 知识库问答 · 共享资料 · 点击直达', url: app.globalData.links.ima, mode: 'ima' }
    ]
  },

  onTap(e) {
    const key = e.currentTarget.dataset.key
    const item = this.data.items.find(i => i.key === key)
    if (!item) return
    if (item.mode === 'media') {
      wx.navigateTo({ url: '/pages/media/index?platform=' + item.platform })
    } else if (item.mode === 'ima') {
      this.openIma(item)
    } else {
      this.copyLink(item.url)
    }
  },

  // 直接拉起 ima 官方小程序并定位到石董会知识库
  // 限制：必须在用户点击事件中同步调用；目标 appId 需在 app.json navigateToMiniProgramAppIdList 中声明
  openIma(item) {
    const shareId = (item.url.split('shareId=')[1] || '').split('&')[0]
    if (!shareId) return this.copyLink(item.url)
    wx.navigateToMiniProgram({
      appId: 'wx4c6401744b734596',
      path: 'pages/index/index?shareId=' + shareId,
      success: () => {},
      fail: () => {
        // 降级：拉不起（如低版本/审核期）就复制 H5 链接
        this.copyLink(item.url)
      }
    })
  },

  copyLink(url) {
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: '链接已复制，去浏览器打开', icon: 'none' })
    })
  }
})
