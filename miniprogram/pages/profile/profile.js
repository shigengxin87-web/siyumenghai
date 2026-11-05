const app = getApp()
const { uid } = require('../../utils/uid')

const SCHEMA_CACHE = 'sdh_profile_schema'

Page({
  data: {
    fields: [],
    profile: {},
    saving: false,
    loading: true,
    hasProfile: false
  },

  onLoad() {
    // 先用缓存渲染，避免白屏；再拉最新字段
    let cached = null
    try { cached = wx.getStorageSync(SCHEMA_CACHE) } catch (_) {}
    if (cached && Array.isArray(cached.fields) && cached.fields.length) {
      this.setData({ fields: cached.fields })
    }
    this.loadSchema()
    this.loadProfile()
  },

  loadSchema() {
    const url = app.globalData.agent.profileSchemaUrl
    wx.request({
      url,
      method: 'GET',
      success: (res) => {
        const d = res.data && res.data.data
        if (!d || !Array.isArray(d.fields) || !d.fields.length) return
        this.setData({ fields: d.fields })
        try { wx.setStorageSync(SCHEMA_CACHE, d) } catch (_) {}
      }
    })
  },

  loadProfile() {
    const url = app.globalData.agent.profileApi + '?user_id=' + encodeURIComponent(uid())
    wx.request({
      url,
      method: 'GET',
      success: (res) => {
        const d = res.data && res.data.data
        if (d && d.filled) {
          const p = {}
          const keys = this.data.fields.map((f) => f.key)
          keys.forEach((k) => { if (d[k]) p[k] = d[k] })
          this.setData({ profile: p, hasProfile: keys.some((k) => !!d[k]) })
        }
        this.setData({ loading: false })
      },
      fail: () => this.setData({ loading: false })
    })
  },

  pick(e) {
    const key = e.currentTarget.dataset.key
    const val = e.currentTarget.dataset.val
    if (!key) return
    // 再点一次取消，方便改主意
    const next = this.data.profile[key] === val ? '' : val
    this.setData({ ['profile.' + key]: next })
  },

  save() {
    if (this.data.saving) return
    const profile = {}
    this.data.fields.forEach((f) => {
      const v = this.data.profile[f.key]
      if (v) profile[f.key] = v
    })
    if (!Object.keys(profile).length) {
      wx.showToast({ title: '至少选一项', icon: 'none' })
      return
    }
    this.setData({ saving: true })
    wx.request({
      url: app.globalData.agent.profileApi,
      method: 'PUT',
      header: { 'Content-Type': 'application/json' },
      data: { user_id: uid(), profile },
      success: (res) => {
        this.setData({ saving: false })
        if (res.statusCode === 200 && res.data && res.data.ok) {
          try { wx.setStorageSync('sdh_profile_hint', 'off') } catch (_) {}
          wx.showToast({ title: '已保存', icon: 'success' })
          setTimeout(() => wx.navigateBack(), 600)
        } else {
          wx.showToast({ title: '保存失败，请重试', icon: 'none' })
        }
      },
      fail: () => {
        this.setData({ saving: false })
        wx.showToast({ title: '网络异常，请重试', icon: 'none' })
      }
    })
  },

  clear() {
    wx.showModal({
      title: '清空我的情况',
      content: '清空后，回答会回到通用版本。确定吗？',
      success: (r) => {
        if (!r.confirm) return
        wx.request({
          url: app.globalData.agent.profileApi,
          method: 'DELETE',
          header: { 'Content-Type': 'application/json' },
          data: { user_id: uid() },
          success: (res) => {
            if (res.statusCode === 200) {
              this.setData({ profile: {}, hasProfile: false })
              wx.showToast({ title: '已清空', icon: 'success' })
            } else {
              wx.showToast({ title: '操作失败', icon: 'none' })
            }
          },
          fail: () => wx.showToast({ title: '网络异常', icon: 'none' })
        })
      }
    })
  },

  back() {
    wx.navigateBack({ fail: () => wx.switchTab({ url: '/pages/chat/chat' }) })
  }
})
