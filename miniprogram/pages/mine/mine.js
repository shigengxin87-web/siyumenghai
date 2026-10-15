Page({
  data: {
    brand: '石董会',
    slogan: '一起成长，一起越来越好',
    version: 'v2.1.0 开发预览'
  },

  openFavorites() {
    wx.navigateTo({ url: '/pages/favorites/favorites' })
  },

  copyContact() {
    wx.setClipboardData({
      data: '石董会 · 一起成长朋友圈',
      success: () => wx.showToast({ title: '已复制，可在社群内找到石董', icon: 'none' })
    })
  },

  onShareAppMessage() {
    return { title: '石董会 · 一起成长朋友圈', path: '/pages/home/home' }
  }
})
