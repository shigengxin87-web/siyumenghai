Page({
  data: {
    url: ''
  },

  onLoad(options) {
    this.rawUrl = decodeURIComponent(options.url || '')
    this.copyOnError = options.copyOnError === '1'
    this.setData({ url: this.rawUrl })
  },

  onError(e) {
    console.error('web-view error', e.detail)
    // web-view 是原生组件，无法在其上覆盖提示，因此出错后复制链接并返回来源页，
    // 让用户拿到链接去浏览器打开；非复制场景仅提示业务域名未配置。
    if (this.copyOnError && this.rawUrl) {
      wx.setClipboardData({
        data: this.rawUrl,
        success: () => {
          wx.showToast({ title: '链接已复制，请在浏览器打开', icon: 'none' })
          setTimeout(() => wx.navigateBack(), 900)
        },
        fail: () => this.fallbackToast()
      })
    } else {
      this.fallbackToast()
    }
  },

  fallbackToast() {
    wx.showToast({ title: '链接无法打开，请检查业务域名配置', icon: 'none' })
    setTimeout(() => wx.navigateBack(), 900)
  }
})
