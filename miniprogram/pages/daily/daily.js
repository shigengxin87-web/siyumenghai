const { reports } = require('../../data/reports')

const app = getApp()

const dateKey = (d) => {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

// 群聊复现：与官网 chat/<date>.json 实时同步的原始群聊
// 日期集合以官网 miniprogram-content.json 的 days 索引为准，失败时降级本地打包日报
Page({
  data: {
    weekdays: WEEKDAYS,
    cells: [],
    title: '',
    recent: []
  },

  onLoad() {
    this.contentSet = {}
    this.recent = []
    this.applyIndex(null)
    this.loadIndex()
    this.openMonth(new Date())
  },

  // index: 官网 days 数组（key/dateLabel/weekday/messages/title，倒序）；null 则用本地 reports
  applyIndex(days) {
    let list
    if (days && days.length) {
      list = days
        .filter((d) => d && d.key)
        .map((d) => ({ key: d.key, dateLabel: d.dateLabel || d.key, weekday: d.weekday || '', title: d.title || '', messages: d.messages || 0 }))
    } else {
      list = Object.keys(reports).sort().reverse().map((k) => ({
        key: k,
        dateLabel: reports[k].dateLabel,
        weekday: reports[k].weekday,
        title: reports[k].title,
        messages: reports[k].messages || 0
      }))
    }
    this.contentSet = {}
    list.forEach((d) => { this.contentSet[d.key] = true })
    this.recent = list.slice(0, 8)
    this.setData({ recent: this.recent })
    // 若日历已渲染，刷新打点
    if (this.year !== undefined) this.openMonth(new Date(this.year, this.month, 1))
  },

  loadIndex() {
    wx.request({
      url: app.globalData.contentApi + '?v=' + Date.now(),
      method: 'GET',
      timeout: 15000,
      success: (res) => {
        if (res.statusCode === 200 && res.data && Array.isArray(res.data.days)) {
          this.applyIndex(res.data.days)
        }
      },
      fail: () => {} // 静默降级：沿用本地打包数据
    })
  },

  makeCell(d, inMonth, todayKey) {
    const key = dateKey(d)
    return {
      key,
      day: d.getDate(),
      inMonth,
      isToday: key === todayKey,
      has: !!this.contentSet[key]
    }
  },

  openMonth(date) {
    const year = date.getFullYear()
    const month = date.getMonth()
    const startWeekday = new Date(year, month, 1).getDay()
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const todayKey = dateKey(new Date())
    const cells = []
    const pushDay = (d, inMonth) => cells.push(this.makeCell(d, inMonth, todayKey))
    for (let i = startWeekday - 1; i >= 0; i--) pushDay(new Date(year, month, -i), false)
    for (let d = 1; d <= daysInMonth; d++) pushDay(new Date(year, month, d), true)
    let tail = 1
    while (cells.length % 7 !== 0) pushDay(new Date(year, month + 1, tail++), false)
    this.year = year
    this.month = month
    this.setData({ cells, title: `${year} 年 ${month + 1} 月` })
  },

  prevMonth() { this.openMonth(new Date(this.year, this.month - 1, 1)) },
  nextMonth() { this.openMonth(new Date(this.year, this.month + 1, 1)) },
  goToday() { this.openMonth(new Date()) },

  onDayTap(e) {
    const key = e.currentTarget.dataset.key
    if (!key || !this.contentSet[key]) return
    wx.navigateTo({ url: '/pages/discuss-day/discuss-day?id=' + encodeURIComponent(key) })
  },

  onShareAppMessage() {
    return { title: '石董会｜群聊复现', path: '/pages/daily/daily' }
  }
})
