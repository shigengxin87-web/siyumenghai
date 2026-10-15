const favorites = require('../../utils/favorites')

const DEFAULT_TIPS = require('../../data/tips')

function normalizeTip(raw, i) {
  return {
    id: raw.id != null ? raw.id : (raw.key != null ? raw.key : i),
    cat: raw.cat || raw.category || '未分类',
    title: raw.title || '',
    summary: raw.summary || raw.desc || ''
  }
}

Page({
  data: {
    cats: ['全部', '私域运营', '内容制作', '产品经营', 'AI 工具', '微信生态'],
    activeCat: '全部',
    keyword: '',
    tips: DEFAULT_TIPS,
    filtered: [],
    favIds: []
  },

  onLoad() {
    const cache = wx.getStorageSync('sdh_real_tips');
    if (Array.isArray(cache) && cache.length) this.setData({ tips: cache.map(normalizeTip) });
    this.loadTips()
    this.refreshFav()
  },

  onShow() {
    this.refreshFav()
  },

  // 优先从服务端拉真实技巧内容；未配置或失败则用本地清单，保证离线可用
  loadTips() {
    const app = getApp()
    const url = ((app.globalData && app.globalData.tipsApi) || '').trim()
    if (!url) {
      this.applyFilter()
      return
    }
    wx.request({
      url,
      method: 'GET',
      timeout: 15000,
      success: (res) => {
        const body = res.data || {}
        const list = Array.isArray(body) ? body : body.tips
        if (res.statusCode === 200 && Array.isArray(list) && list.length) {
          this.setData({ tips: list.map(normalizeTip) });
          try { wx.setStorageSync('sdh_real_tips', list) } catch (_) {}
        }
        this.applyFilter()
      },
      fail: () => this.applyFilter()
    })
  },

  onSearchInput(e) {
    this.setData({ keyword: e.detail.value })
    this.applyFilter()
  },

  onSearchClear() {
    this.setData({ keyword: '' })
    this.applyFilter()
  },

  onCatTap(e) {
    this.setData({ activeCat: e.currentTarget.dataset.cat })
    this.applyFilter()
  },

  applyFilter() {
    const cat = this.data.activeCat
    const kw = (this.data.keyword || '').trim().toLowerCase()
    let list = cat === '全部' ? this.data.tips : this.data.tips.filter(t => t.cat === cat)
    if (kw) {
      list = list.filter(t => (t.title + ' ' + t.summary + ' ' + t.cat).toLowerCase().indexOf(kw) !== -1)
    }
    const favs = this.data.favIds
    this.setData({ filtered: list.map(t => Object.assign({}, t, { isFav: favs.indexOf(String(t.id)) !== -1 })) })
  },

  refreshFav() {
    const favIds = favorites.load().filter(i => i.type === 'tip').map(i => String(i.key))
    this.setData({ favIds })
    this.applyFilter()
  },

  toggleFav(e) {
    const id = String(e.currentTarget.dataset.id)
    const tip = this.data.tips.find(t => String(t.id) === id)
    if (!tip) return
    const r = favorites.toggle({ type: 'tip', key: id, title: tip.title, summary: tip.summary, cat: tip.cat })
    this.setData({ favIds: r.list.filter(i => i.type === 'tip').map(i => String(i.key)) })
    wx.showToast({ title: r.favorited ? '已收藏' : '已取消收藏', icon: 'none' })
  },

  goDetail(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: '/pages/tips-detail/tips-detail?id=' + id })
  },

  onShareAppMessage() {
    return { title: '石董会 · 技巧库', path: '/pages/tips/tips' }
  }
})