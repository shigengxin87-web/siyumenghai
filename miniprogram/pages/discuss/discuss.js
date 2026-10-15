const app = getApp()
const favorites = require('../../utils/favorites')

// 讨论板块：日期清单与官网实时同步
// 数据源：官网 app.js 里内嵌的 days 对象（含 archiveDays + 后续补充日报）
Page({
  data: {
    days: [],
    shown: [],
    months: [],
    activeMonth: '全部',
    keyword: '',
    loading: true,
    error: ''
  },

  onLoad() {
    this.loadDays(false)
  },

  onPullDownRefresh() {
    this.loadDays(true)
  },

  applyFilter() {
    const kw = (this.data.keyword || '').trim().toLowerCase()
    const month = this.data.activeMonth
    let list = this.data.days
    if (month && month !== '全部') list = list.filter(d => (d.key || '').slice(0, 7) === month)
    if (kw) {
      list = list.filter(d => ((d.title || '') + ' ' + (d.dateLabel || '') + ' ' + (d.key || '') + ' ' + (d.weekday || '')).toLowerCase().indexOf(kw) !== -1)
    }
    this.setData({ shown: list })
  },

  buildMonths() {
    const set = {}
    for (const d of this.data.days) {
      const m = (d.key || '').slice(0, 7)
      if (m) set[m] = true
    }
    const months = Object.keys(set).sort((a, b) => b.localeCompare(a))
    this.setData({ months, activeMonth: months.indexOf(this.data.activeMonth) === -1 ? '全部' : this.data.activeMonth })
  },

  onSearchInput(e) {
    this.setData({ keyword: e.detail.value })
    this.applyFilter()
  },

  onSearchClear() {
    this.setData({ keyword: '' })
    this.applyFilter()
  },

  onMonthTap(e) {
    this.setData({ activeMonth: e.currentTarget.dataset.month })
    this.applyFilter()
  },

  toggleFav(e) {
    const key = e.currentTarget.dataset.key
    const day = this.data.days.find(d => d.key === key)
    if (!day) return
    const r = favorites.toggle({ type: 'day', key, title: day.title || day.dateLabel || day.key, sub: day.messages + ' 条群聊记录' })
    wx.showToast({ title: r.favorited ? '已收藏' : '已取消收藏', icon: 'none' })
    this.applyFilter()
  },

  loadDays(force) {
    const cached = wx.getStorageSync('sdh_days')
    const now = Date.now()
    if (!force && cached && cached.list && now - (cached.ts || 0) < 6 * 3600 * 1000) {
      this.setData({ days: cached.list, loading: false })
      this.buildMonths()
      this.applyFilter()
      return
    }

    this.setData({ loading: true, error: '' })
    wx.request({
      url: app.globalData.contentApi + '?v=' + now,
      method: 'GET',
      timeout: 20000,
      success: (res) => {
        try {
          if (res.statusCode !== 200 || !res.data || !Array.isArray(res.data.days)) throw new Error('invalid content');
          const list = res.data.days
          wx.setStorageSync('sdh_days', { list, ts: now })
          this.setData({ days: list, loading: false })
          this.buildMonths()
          this.applyFilter()
        } catch (e) {
          this.setData({ loading: false, error: '数据解析失败，请稍后再试' })
        }
      },
      fail: () => {
        if (cached && cached.list) {
          this.setData({ days: cached.list, loading: false, error: '网络异常，展示缓存数据' })
          this.buildMonths()
          this.applyFilter()
        } else {
          this.setData({ loading: false, error: '网络异常，请检查网络后下拉刷新' })
        }
      },
      complete: () => {
        wx.stopPullDownRefresh()
      }
    })
  },

  goDay(e) {
    const key = e.currentTarget.dataset.key
    wx.navigateTo({ url: '/pages/discuss-day/discuss-day?id=' + key })
  },

  onShareAppMessage() {
    return { title: '石董会 · 每日原始讨论', path: '/pages/discuss/discuss' }
  }
})
