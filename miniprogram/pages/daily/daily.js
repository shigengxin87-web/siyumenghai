const { reports } = require('../../data/reports')

const dateKey = (d) => {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

Page({
  data: {
    weekdays: WEEKDAYS,
    cells: [],
    title: '',
    recent: []
  },

  onLoad() {
    const keys = Object.keys(reports)
    this.contentSet = {}
    keys.forEach((k) => { this.contentSet[k] = true })
    const recent = keys.slice().sort().reverse().slice(0, 8).map((k) => ({
      key: k,
      dateLabel: reports[k].dateLabel,
      weekday: reports[k].weekday,
      title: reports[k].title
    }))
    this.setData({ recent })
    this.openMonth(new Date())
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
    wx.navigateTo({ url: '/pages/report/index?date=' + encodeURIComponent(key) })
  },

  onShareAppMessage() {
    return { title: '石董会｜每日内容', path: '/pages/daily/daily' }
  }
})
