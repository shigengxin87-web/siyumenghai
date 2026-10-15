const app = getApp()

// 每日原始讨论：与官网 chat/<date>.json 实时同步
Page({
  data: {
    date: '',
    dateLabel: '',
    messages: [],
    loading: true,
    error: ''
  },

  onLoad(options) {
    const id = options.id || ''
    this.setData({ date: id })
    wx.setNavigationBarTitle({ title: id + ' · 原始讨论' })
    this.loadChat(id)
  },

  loadChat(date) {
    if (!date) {
      this.setData({ loading: false, error: '缺少日期参数' })
      return
    }
    this.setData({ loading: true, error: '' })
    wx.request({
      url: app.globalData.siteBase + '/chat/' + date + '.json?v=' + Date.now(),
      method: 'GET',
      timeout: 20000,
      success: (res) => {
        if (res.statusCode !== 200 || !res.data || !Array.isArray(res.data.messages)) { this.setData({ loading: false, error: '当天原始记录暂不可用，请稍后再试' }); return; }
        const body = res.data || {}
        const raw = body.messages || []
        const messages = raw.map((m, i) => {
          const media = m.media || null
          // media 里的相对路径转成官网绝对地址，小程序里可直接加载图片
          let mediaUrl = ''
          if (media && media.kind === 'image' && media.url) {
            mediaUrl = media.url.indexOf('http') === 0
              ? media.url
              : app.globalData.siteBase + '/' + media.url.replace(/^\.\//, '')
          }
          return {
            id: m.id || ('m' + i),
            timeShort: this.shortTime(m.time),
            sender: m.sender || '',
            type: m.type || 'text',
            text: m.text || '',
            isSystem: m.type === 'system',
            mediaKind: media ? media.kind : null,
            mediaUrl,
            mediaAlt: media ? media.alt || '' : '',
            hasMedia: !!(media),
            redacted: !!m.redacted,
            links: Array.isArray(m.links) ? m.links.filter(l => l && l.url) : []
          }
        })
        this.setData({ messages, dateLabel: body.date || date, loading: false })
      },
      fail: () => {
        this.setData({ loading: false, error: '当天记录加载失败，请稍后再试' })
      }
    })
  },

  shortTime(t) {
    if (!t) return ''
    const s = String(t)
    return s.length >= 16 ? s.slice(11, 16) : s
  },

  copyLink(e) {
    const url = e.currentTarget.dataset.url
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: '链接已复制', icon: 'none' })
    })
  },

  previewImage(e) {
    const url = e.currentTarget.dataset.url
    if (!url) return
    wx.previewImage({ current: url, urls: [url] })
  },

  onShareAppMessage() {
    return { title: this.data.date + ' · 原始讨论', path: '/pages/discuss-day/discuss-day?id=' + this.data.date }
  }
})
