const app = getApp()

Page({
  data: {
    entries: [
      { key: 'chat', icon: '💬', title: 'AI 问答', desc: '运营问题直接问，会话自动保存' },
      { key: 'discuss', icon: '🗓', title: '最新讨论', desc: '每日群聊按关键词、日期查找' },
      { key: 'tips', icon: '📚', title: '技巧库', desc: '常用技巧与干货，支持搜索' },
      { key: 'favorites', icon: '★', title: '我的收藏', desc: '收藏的技巧与讨论随时回看' },
      { key: 'archive', icon: '📅', title: '日报归档', desc: '每日复盘快速浏览' },
      { key: 'members', icon: '👥', title: '群友名录', desc: '成员列表与学习版入口' },
      { key: 'tools', icon: '🛠', title: '社群工具', desc: '三平台保存 · 飞书 · ima' },
      { key: 'kb', icon: '🗂️', title: '知识库', desc: '飞书 · ima · 知识沉淀' }
    ]
  },

  onEntry(e) {
    const key = e.currentTarget.dataset.key
    if (key === 'chat') {
      wx.switchTab({ url: '/pages/chat/chat' })
    } else if (key === 'tips') {
      wx.switchTab({ url: '/pages/tips/tips' })
    } else if (key === 'discuss') {
      wx.switchTab({ url: '/pages/discuss/discuss' })
    } else if (key === 'favorites') {
      wx.navigateTo({ url: '/pages/favorites/favorites' })
    } else if (key === 'archive') {
      wx.navigateTo({ url: '/pages/archive/index' })
    } else if (key === 'members') {
      wx.navigateTo({ url: '/pages/members/index' })
    } else if (key === 'tools') {
      wx.navigateTo({ url: '/pages/tools/index' })
    } else if (key === 'kb') {
      wx.navigateTo({ url: '/pages/kb/kb' })
    }
  },

  onShareAppMessage() {
    return {
      title: '石董会 · 一起成长朋友圈',
      path: '/pages/home/home'
    }
  }
})
