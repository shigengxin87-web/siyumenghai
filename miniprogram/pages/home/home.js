const app = getApp()

Page({
  data: {
    entries: [
      { key: 'members', icon: '👥', title: '群友名录', desc: '成员列表与学习版入口' },
      { key: 'tools', icon: '🎬', title: '抖视红下载', desc: '抖音·视频号·小红书 一键保存到相册' }
    ]
  },

  onEntry(e) {
    const key = e.currentTarget.dataset.key
    if (key === 'members') {
      wx.navigateTo({ url: '/pages/members/index' })
    } else if (key === 'tools') {
      wx.navigateTo({ url: '/pages/tools/index' })
    }
  },

  onShareAppMessage() {
    return {
      title: '石董会 · 一起成长朋友圈',
      path: '/pages/home/home'
    }
  }
})
