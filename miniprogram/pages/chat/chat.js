const app = getApp()
const { Utf8Decoder, EventReader } = require('../../utils/chat-stream')
const { uid } = require('../../utils/uid')
const KEY = 'sdh_chat_messages'
// 档案引导只出现一次；用户关闭过（或已填过）就不再打扰
const PROFILE_HINT = 'sdh_profile_hint'
const WELCOME = '你好，我是更新哥的运营实战顾问。\n\n获客、产品、转化、交付、经营、团队……你的运营问题，直接问我，我会从实战案例库里给你找答案。'
const sessionId = () => 's' + Date.now().toString(36) + Math.random().toString(36).slice(2)
// 把模型返回的 Markdown 清洗成纯文本：去掉符号、把标题/列表转成换行，便于小程序展示
function clean(text) {
  if (!text) return ''
  let t = String(text)
  t = t.replace(/!\[[^\]]*\]\([^)]*\)/g, '')            // 图片 ![alt](url) -> 去掉
  t = t.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')         // 链接 [文字](url) -> 文字
  t = t.replace(/^#{1,6}\s+/gm, '\n')                   // 标题 # 转成前后换行
  t = t.replace(/^>\s?/gm, '')                          // 引用 > 去掉
  t = t.replace(/^\s*[-*+]\s+/gm, '\n• ')               // 无序列表 -> 换行+项目符号
  t = t.replace(/^\s*\d+\.\s+/gm, '\n• ')               // 有序列表 -> 换行+项目符号
  t = t.replace(/\*\*([^*]+)\*\*/g, '$1')               // 粗体 **x**
  t = t.replace(/__([^_]+)__/g, '$1')                   // 粗体 __x__
  t = t.replace(/\*([^*]+)\*/g, '$1')                   // 斜体 *x*
  t = t.replace(/_([^_]+)_/g, '$1')                     // 斜体 _x_
  t = t.replace(/`([^`]+)`/g, '$1')                     // 行内代码 `x`
  t = t.replace(/^\s*([-*])\1{2,}\s*$/gm, '\n')         // 分隔线 --- / *** -> 换行
  t = t.replace(/【([^】]+)】\([^)]*\)/g, '$1')         // 部分平台链接变体
  t = t.replace(/\n{3,}/g, '\n\n').trim()               // 折叠多余空行
  return t
}
Page({
  data: { messages: [], input: '', sending: false, firstToken: false, scrollTop: 0, seq: 0, showGuide: false },
  onLoad() { this.closed = false; this.generation = 0; this.loadSession() },
  onShow() { this.checkProfileHint() },
  onUnload() { this.closed = true; this.generation++; if (this.task) this.task.abort(); this.saveSession() },
  onInput(e) { this.setData({ input: e.detail.value }) },
  goProfile() { this.hideGuide(); wx.navigateTo({ url: '/pages/profile/profile' }) },
  // 首次进来、还没聊过、也没填过档案时，给一条可关闭的引导卡片
  checkProfileHint() {
    let flag = ''
    try { flag = wx.getStorageSync(PROFILE_HINT) } catch (_) {}
    if (flag === 'off') return
    if (this.data.messages.length > 1) return       // 已经在聊了就别打扰
    if (!this.data.showGuide) this.setData({ showGuide: true })
    if (this._hintChecked) return                   // 每次进页面只核对一次
    this._hintChecked = true
    wx.request({
      url: app.globalData.agent.profileApi + '?user_id=' + encodeURIComponent(uid()),
      method: 'GET',
      success: (res) => {
        const d = res.data && res.data.data
        if (d && d.filled) this.hideGuide()          // 别的设备填过了，不用再提示
      }
    })
  },
  hideGuide() {
    try { wx.setStorageSync(PROFILE_HINT, 'off') } catch (_) {}
    if (this.data.showGuide) this.setData({ showGuide: false })
  },
  loadSession() {
    let stored; try { stored = wx.getStorageSync(KEY) } catch (_) {}
    this.conversation = stored && stored.conversation || sessionId()
    const messages = stored && Array.isArray(stored.messages) ? stored.messages.filter(m => m && typeof m.text === 'string').slice(-100).map(m => {
      const failed = m.status === 'pending' || m.status === 'failed' || m.canRetry === true
      return { ...m, status: failed ? 'failed' : 'done', canRetry: m.role === 'assistant' && failed, text: m.text || (failed ? '上次回复未完成，请重试。' : '') }
    }) : []
    this.setData({ messages: messages.length ? messages : [{ role: 'assistant', text: WELCOME, id: 'm1', status: 'done' }], seq: Math.max(Number(stored && stored.seq) || 0, 1) })
    this.scrollToBottom(true)
  },
  saveSession() { try { wx.setStorageSync(KEY, { messages: this.data.messages.slice(-100), seq: this.data.seq, conversation: this.conversation }) } catch (_) {} },
  clearChat() {
    if (this.data.sending) return
    wx.showModal({ title: '清空会话', content: '清空本机记录并开始新会话，确定吗？', success: r => {
      if (!r.confirm || this.closed) return
      this.conversation = sessionId(); this.setData({ messages: [{ role: 'assistant', text: WELCOME, id: 'm1', status: 'done' }], seq: 1, input: '' }); this.saveSession()
    } })
  },
  send() {
    const text = this.data.input.trim(); if (!text || this.data.sending) return
    const generation = ++this.generation
    const alive = () => !this.closed && generation === this.generation
    const replyId = 'm' + (this.data.seq + 2)
    const history = this.data.messages.filter(m => m.role === 'user' || (m.status === 'done' && !m.canRetry)).map(m => ({ role: m.role, content: [{ type: 'text', text: m.text }] }))
    const first = history.findIndex(m => m.role === 'user'); const messages = (first < 0 ? [] : history.slice(first)).concat([{ role: 'user', content: [{ type: 'text', text }] }])
    this.setData({ messages: this.data.messages.concat([{ role: 'user', text, id: 'm' + (this.data.seq+1), status: 'done' }, { role: 'assistant', text: '', id: replyId, status: 'pending', canRetry: false }]), seq: this.data.seq+2, input: '', sending: true, firstToken: false })
    this.saveSession(); this._nearBottom = true; this.scrollToBottom(true)
    const update = patch => {
      if (!alive()) return
      const idx = this.data.messages.findIndex(m => m.id === replyId)
      if (idx < 0) return
      const keys = Object.keys(patch)
      if (keys.length === 1 && keys[0] === 'text') {
        // 流式只改文本：走路径更新，避免整个消息数组重传
        this.data.messages[idx].text = patch.text
        this.setData({ ['messages[' + idx + '].text']: patch.text })
      } else {
        this.setData({ ['messages[' + idx + ']']: { ...this.data.messages[idx], ...patch } })
      }
      this.scrollToBottom()
    }
    let responseText = '', completed = false, failed = false, status = 0, received = false
    const fail = tip => { failed = true; update({ text: (responseText ? clean(responseText) + '\n\n' : '') + tip, status: 'failed', canRetry: true }) }
    const decoder = new Utf8Decoder()
    const reader = new EventReader(event => {
      if (event.type === 'delta') responseText += event.text || ''
      if (event.type === 'replace' || event.type === 'done') responseText = event.text || ''
      if (event.type === 'done') completed = true
      if (event.type === 'error') { fail('回复未完成，请稍后重试。'); return }
      if (!failed) { update({ text: responseText }); if (responseText && alive()) this.setData({ firstToken: true }) }
    })
    this.task = wx.request({ url: app.globalData.agent.apiUrl, method: 'POST', enableChunked: true, dataType: 'text', timeout: 60000,
      data: { user_id: this.uid(), conversation_id: this.conversation, stream: true, stream_format: 'events', messages },
      success: res => {
        if (!alive()) return
        status = res.statusCode
        if (status !== 200) { fail(status === 429 ? '当前提问较多，请稍后重试。' : '问答服务暂时不可用，请稍后重试。'); return }
        try { if (!received && typeof res.data === 'string') reader.push(res.data, true); else reader.push('', true) }
        catch (_) { fail('回复读取失败，请稍后重试。'); return }
        if (!failed && completed && responseText) update({ text: clean(responseText), status: 'done', canRetry: false })
        else if (!failed) fail('回复生成中断，请稍后重试。')
      },
      fail: err => {
        if (!alive()) return
        const detail = err && err.errMsg || ''
        const tip = /timeout/i.test(detail) ? '回复等待超时，请稍后重试。' : /domain|url.?check|not in/i.test(detail) ? '问答连接配置尚未完成，请联系管理员。' : '暂时无法连接，请检查网络后重试。'
        // Keep only the category; no internal addresses or provider errors in visitor UI.
        console.warn('chat request failed', /timeout/i.test(detail) ? 'timeout' : /domain|url.?check|not in/i.test(detail) ? 'domain' : 'connection')
        fail(tip)
      },
      complete: () => { if (alive()) { this.setData({ sending: false }); this.task = null; this.saveSession() } }
    })
    if (this.task.onHeadersReceived) this.task.onHeadersReceived(r => { status = r.statusCode })
    if (this.task.onChunkReceived) this.task.onChunkReceived(r => {
      if (!alive() || failed || (status && status !== 200)) return
      received = true
      try { reader.push(decoder.push(r.data), false) } catch (_) { fail('回复读取失败，请稍后重试。') }
    })
  },
  retryMessage(e) {
    if (this.data.sending) return
    const i = this.data.messages.findIndex(m => m.id === e.currentTarget.dataset.id && m.canRetry)
    if (i < 1) return
    let user = i-1; while (user >= 0 && this.data.messages[user].role !== 'user') user--
    if (user < 0) return
    const text = this.data.messages[user].text
    this.setData({ messages: this.data.messages.slice(0,user), input: text }); this.send()
  },
  copyMessage(e) { const m = this.data.messages.find(m => m.id === e.currentTarget.dataset.id); if (m && m.text) wx.setClipboardData({ data: m.text }) },
  uid() { let id = wx.getStorageSync('sdh_uid'); if (!id) { id = 'u' + Date.now() + Math.floor(Math.random()*10000); wx.setStorageSync('sdh_uid',id) } return id },
  // 用户往上翻看历史时不再强制拉到底，回到接近底部才恢复自动跟随
  onScroll(e) {
    const d = e.detail || {}
    if (typeof d.scrollHeight !== 'number') return
    this._nearBottom = d.scrollHeight - d.scrollTop - d.viewHeight < 160
  },
  scrollToBottom(force) {
    if (!force && this._nearBottom === false) return
    clearTimeout(this._scrollTimer)
    this._scrollTimer = setTimeout(() => {
      const tick = (this._scrollTick || 0) + 1
      this._scrollTick = tick
      this.setData({ scrollTop: 1000000 + tick })
    }, 40)
  },
  onShareAppMessage() { return { title: '石董会 · AI问答', path: '/pages/chat/chat' } }
})
