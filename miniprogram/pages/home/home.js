const app = getApp()

Page({
  data: {
    entries: [
      { key: 'chat', icon: '💬', title: 'AI 问答', desc: '运营问题直接问，会话自动保存' },
      { key: 'archive', icon: '📅', title: '日报归档', desc: '每日复盘与关键观点快速回看' },
      { key: 'members', icon: '👥', title: '群友名录', desc: '成员列表与学习版入口' },
      { key: 'tools', icon: '🎬', title: '抖视红下载', desc: '抖音·视频号·小红书 一键保存到相册' }
    ]
  },

  onEntry(e) {
    const key = e.currentTarget.dataset.key
    if (key === 'chat') {
      wx.switchTab({ url: '/pages/chat/chat' })
    } else if (key === 'archive') {
      wx.navigateTo({ url: '/pages/archive/index' })
    } else if (key === 'members') {
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
