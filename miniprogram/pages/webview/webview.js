Page({
  data: {
    url: ''
  },

  onLoad(options) {
    this.setData({ url: decodeURIComponent(options.url || '') })
  },

  onError(e) {
    wx.showToast({
      title: '页面打开失败，请检查业务域名配置',
      icon: 'none'
    })
    console.error('web-view error', e.detail)
  }
})
