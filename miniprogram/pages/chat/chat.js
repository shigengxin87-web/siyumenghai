const app = getApp()
const { Utf8Decoder, EventReader } = require('../../utils/chat-stream')
const KEY = 'sdh_chat_messages'
const WELCOME = '你好，我是更新哥的运营实战顾问。\n\n获客、产品、转化、交付、经营、团队……你的运营问题，直接问我，我会从实战案例库里给你找答案。'
const sessionId = () => 's' + Date.now().toString(36) + Math.random().toString(36).slice(2)
function clean(text) { return text.replace(/^#{1,6}\s*/gm, '').replace(/^>\s?/gm, '').replace(/\*\*/g, '').replace(/`/g, '').trim() }
Page({
  data: { messages: [], input: '', sending: false, firstToken: false, scrollInto: '', seq: 0 },
  onLoad() { this.closed = false; this.generation = 0; this.loadSession() },
  onUnload() { this.closed = true; this.generation++; if (this.task) this.task.abort(); this.saveSession() },
  onInput(e) { this.setData({ input: e.detail.value }) },
  loadSession() {
    let stored; try { stored = wx.getStorageSync(KEY) } catch (_) {}
    this.conversation = stored && stored.conversation || sessionId()
    const messages = stored && Array.isArray(stored.messages) ? stored.messages.filter(m => m && typeof m.text === 'string').slice(-100).map(m => {
      const failed = m.status === 'pending' || m.status === 'failed' || m.canRetry === true
      return { ...m, status: failed ? 'failed' : 'done', canRetry: m.role === 'assistant' && failed, text: m.text || (failed ? '上次回复未完成，请重试。' : '') }
    }) : []
    this.setData({ messages: messages.length ? messages : [{ role: 'assistant', text: WELCOME, id: 'm1', status: 'done' }], seq: Math.max(Number(stored && stored.seq) || 0, 1) })
    this.scrollToBottom()
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
    this.saveSession(); this.scrollToBottom()
    const update = patch => {
      if (!alive()) return
      this.setData({ messages: this.data.messages.map(m => m.id === replyId ? { ...m, ...patch } : m) })
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
  scrollToBottom() { if (this.data.messages.length) this.setData({ scrollInto: 'msg-' + (this.data.messages.length-1) }) },
  onShareAppMessage() { return { title: '石董会 · AI问答', path: '/pages/chat/chat' } }
})
