const favorites = require('../../utils/favorites')

const TYPE_LABEL = { tip: '技巧', day: '讨论' }

Page({
  data: {
    types: ['全部', '技巧', '讨论'],
    activeType: '全部',
    list: [],
    shown: []
  },

  onLoad() {
    this.reload()
  },

  onShow() {
    this.reload()
  },

  reload() {
    const list = favorites.load().map(i => Object.assign({}, i, {
      id: [i.type, i.key].join(':'),
      typeLabel: TYPE_LABEL[i.type] || '收藏'
    }))
    this.setData({ list })
    this.applyFilter()
  },

  applyFilter() {
    const t = this.data.activeType
    this.setData({ shown: t === '全部' ? this.data.list : this.data.list.filter(i => i.typeLabel === t) })
  },

  onTypeTap(e) {
    this.setData({ activeType: e.currentTarget.dataset.type })
    this.applyFilter()
  },

  openItem(e) {
    const id = e.currentTarget.dataset.id
    const item = this.data.list.find(i => i.id === id)
    if (!item) return
    if (item.type === 'tip') {
      wx.navigateTo({ url: '/pages/tips-detail/tips-detail?id=' + encodeURIComponent(item.key) })
    } else if (item.type === 'day') {
      wx.navigateTo({ url: '/pages/discuss-day/discuss-day?id=' + item.key })
    } else if (item.type === 'media') {
      wx.switchTab({ url: '/pages/home/home' })
    }
  },

  copy(e) {
    const id = e.currentTarget.dataset.id
    const item = this.data.list.find(i => i.id === id)
    if (!item) return
    const text = [item.title, item.summary || item.sub || ''].filter(Boolean).join('\n')
    wx.setClipboardData({ data: text, success: () => wx.showToast({ title: '已复制', icon: 'none' }) })
  },

  remove(e) {
    const id = e.currentTarget.dataset.id
    const item = this.data.list.find(i => i.id === id)
    if (!item) return
    wx.showModal({
      title: '取消收藏',
      content: '确定取消收藏这条内容吗？',
      success: (r) => {
        if (r.confirm) {
          favorites.remove({ type: item.type, key: item.key })
          this.reload()
        }
      }
    })
  },

  onShareAppMessage() {
    return { title: '石董会 · 我的收藏', path: '/pages/favorites/favorites' }
  }
})