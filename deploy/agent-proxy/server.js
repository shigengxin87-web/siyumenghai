const http = require('http')
const crypto = require('crypto')
const fs = require('fs')

const CONFIG_PATH = process.env.AGENT_CONFIG_PATH || '/opt/siyumenghai-agent-proxy/config.json'
const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'))
const { appkey, upstream } = config

// ADP v2 要求会话 ID 为 32-64 位 [a-zA-Z0-9_-]；同一 user 必须恒定，保证上下文连续
function conversationId(userId) {
  return crypto.createHash('sha256').update('sdh:' + userId).digest('hex') // 64 位 hex
}

function requestId() {
  // 48 位：uuid(去横线 32) + 随机 hex(16)
  return crypto.randomUUID().replace(/-/g, '') + crypto.randomBytes(8).toString('hex')
}

async function handler(req, res) {
  if (req.method !== 'POST') {
    res.writeHead(405, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ error: { message: 'method not allowed' } }))
    return
  }

  let body = ''
  req.on('data', (c) => {
    body += c
    if (body.length > 256 * 1024) req.destroy()
  })

  req.on('end', async () => {
    let payload
    try {
      payload = JSON.parse(body)
    } catch (e) {
      return bad(res, 'invalid json')
    }

    let messages = Array.isArray(payload.messages) ? payload.messages : []
    if (!messages.length) return bad(res, 'empty messages')

    // 取最后一条 user 消息的文本（ADP 按 ConversationId 服务端维护上下文，只发当前问题）
    let userText = ''
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i]
      if (m && m.role === 'user') {
        if (Array.isArray(m.content)) {
          userText = m.content
            .filter((x) => x && x.type === 'text')
            .map((x) => x.text || '')
            .join('')
        } else if (typeof m.content === 'string') {
          userText = m.content
        }
        if (userText.trim()) break
      }
    }
    if (!userText.trim()) return bad(res, 'no user message text')

    const userId = String(payload.user_id || 'anonymous').slice(0, 64)

    const upBody = JSON.stringify({
      RequestId: requestId(),
      ConversationId: conversationId(userId + (typeof payload.conversation_id === 'string' && /^[a-zA-Z0-9_-]{1,64}$/.test(payload.conversation_id) ? ':' + payload.conversation_id : '')),
      AppKey: appkey,
      UserId: userId,
      Contents: [{ Type: 'text', Text: userText }],
      Incremental: true,
      Stream: 'enable'
    })

    // 流式模式：小程序发 stream:true 时，逐段把 ADP 的 reply 文本推回，避免整段聚合导致的 30s+ 等待与超时
    if (payload.stream) {
      return streamChat(upBody, res, payload.stream_format === 'events')
    }

    let r
    try {
      r = await fetch(upstream, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: upBody, signal: AbortSignal.timeout(55000)
      })
    } catch (e) {
      res.writeHead(502, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: { message: 'upstream unavailable' } }))
      return
    }

    let raw
    try { raw = await r.text() } catch (_) {
      res.writeHead(502, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: { message: '服务暂时不可用' } })); return
    }

    if (r.status !== 200) {
      res.writeHead(r.status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
      res.end(raw)
      return
    }

    // 聚合 ADP SSE 流中的回复文本（只收集 reply 消息，跳过 thought）
    const { text, error } = aggregateSse(raw)
    if (error) {
      res.writeHead(502, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: { message: error } }))
      return
    }
    if (!text) {
      res.writeHead(502, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: { message: 'empty reply from upstream' } }))
      return
    }

    // 清洗 Markdown 语法符号（保留换行与数字序号），小程序端直接展示纯文本
    const content = cleanMarkdown(text)

    // 以 OpenAI 兼容结构回给小程序，前端无需改动
    res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
    res.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content } }] }))
  })
}

async function streamChat(upBody, res, events = false) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 55000)
  res.on('close', () => controller.abort())
  const emit = event => { if (!res.destroyed && !res.writableEnded) res.write(events ? JSON.stringify(event) + '\n' : event.type === 'delta' ? event.text : event.type === 'error' ? '\n（回复未完成，请重试）' : '') }
  try {
    const response = await fetch(upstream, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: upBody, signal: controller.signal })
    if (response.status !== 200) {
      if (!res.destroyed) { res.writeHead(response.status === 429 ? 429 : 502, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: { message: '服务暂时不可用' } })) }
      await response.body?.cancel(); return
    }
    res.writeHead(200, { 'Content-Type': events ? 'application/x-ndjson; charset=utf-8' : 'text/plain; charset=utf-8', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' })
    const decoder = new TextDecoder('utf-8'), replies = new Map()
    let buffer = '', complete = false, failed = false
    const all = () => Array.from(replies.values()).join('')
    const handle = line => {
      if (!line.trim().startsWith('data:')) return
      let event; try { event = JSON.parse(line.trim().slice(5).trim()) } catch (_) { return }
      const message = event.Message, id = event.MessageId || message?.MessageId
      if (event.Type === 'error' || event.Error || (event.Type === 'response.completed' && event.Response?.Status === 'failed')) { failed = true; return }
      if (event.Type === 'message.added' && message?.Type === 'reply') replies.set(id, '')
      if ((event.Type === 'text.delta' || event.Type === 'text.replace') && replies.has(id)) {
        const text = event.Text || ''
        replies.set(id, event.Type === 'text.delta' ? replies.get(id) + text : text)
        emit(event.Type === 'text.delta' ? { type: 'delta', text } : { type: 'replace', text: all() })
      }
      if (event.Type === 'message.done' && message?.Type === 'reply') {
        if (message.Status === 'failed') { failed = true; return }
        const text = (message.Contents || []).filter(c => c.Type === 'text').map(c => c.Text || '').join('')
        if (text) { replies.set(id, text); if (events) emit({ type: 'replace', text: all() }) }
        complete = true
      }
    }
    for await (const chunk of response.body) {
      buffer += decoder.decode(chunk, { stream: true })
      const lines = buffer.split('\n'); buffer = lines.pop()
      for (const line of lines) handle(line)
    }
    buffer += decoder.decode(); if (buffer.trim()) handle(buffer)
    if (failed || !complete || !all()) emit({ type: 'error' })
    else if (events) emit({ type: 'done', text: all() })
    res.end()
  } catch (_) {
    if (!res.destroyed && !res.writableEnded) {
      if (!res.headersSent) { res.writeHead(502, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: { message: '服务暂时不可用' } })) }
      else { emit({ type: 'error' }); res.end() }
    }
  } finally { clearTimeout(timer) }
}

function cleanMarkdown(text) {
  return text
    .split('\n')
    .map((line) => {
      let l = line
      l = l.replace(/^#{1,6}\s*/, '') // 标题 ###
      l = l.replace(/^>\s?/, '') // 引用 >
      l = l.replace(/^\s*[-*+]\s+/, '') // 无序列表 - * +
      l = l.replace(/\*\*/g, '') // 加粗 **
      l = l.replace(/\*/g, '') // 斜体/残留星号
      l = l.replace(/`/g, '') // 行内代码 `
      return l.replace(/\s+$/, '')
    })
    .join('\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function aggregateSse(raw) {
  const replyIds = new Set()
  const texts = new Map() // MessageId -> 累积文本
  let error = ''
  for (const line of raw.split('\n')) {
    const t = line.trim()
    if (!t.startsWith('data:')) continue
    const data = t.slice(5).trim()
    if (!data) continue
    let ev
    try {
      ev = JSON.parse(data)
    } catch (e) {
      continue
    }
    const type = ev.Type || ''
    if (type === 'message.added' && ev.Message && ev.Message.Type === 'reply') {
      // message.added 的 MessageId 在 Message 内部
      const mid = ev.Message.MessageId
      replyIds.add(mid)
      if (!texts.has(mid)) texts.set(mid, '')
    } else if (type === 'message.done' && ev.Message && ev.Message.Type === 'reply') {
      // 兜底：done 事件带完整文本时直接采用
      const mid = ev.Message.MessageId
      if (Array.isArray(ev.Message.Contents)) {
        const full = ev.Message.Contents.filter((c) => c && c.Type === 'text').map((c) => c.Text || '').join('')
        if (full) texts.set(mid, full)
      }
    } else if (type === 'text.delta' && replyIds.has(ev.MessageId)) {
      texts.set(ev.MessageId, (texts.get(ev.MessageId) || '') + (ev.Text || ''))
    } else if (type === 'text.replace' && replyIds.has(ev.MessageId)) {
      texts.set(ev.MessageId, ev.Text || '')
    } else if (type === 'error' || (ev.Error && ev.Error.Message)) {
      error = (ev.Error && (ev.Error.Message || ev.Error.message)) || 'upstream error'
    }
  }
  return { text: Array.from(texts.values()).join(''), error }
}

function bad(res, msg) {
  res.writeHead(400, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify({ error: { message: msg } }))
}

if (require.main === module) http.createServer(handler).listen(Number(process.env.PORT || 2035), '127.0.0.1', () => {
  console.log('siyumenghai agent-proxy (ADP) listening on 127.0.0.1:2035')
})

module.exports = { handler, aggregateSse, cleanMarkdown };
