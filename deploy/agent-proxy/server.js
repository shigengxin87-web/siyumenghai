const http = require('http')
const https = require('https')
const crypto = require('crypto')
const fs = require('fs')
const { URL } = require('url')

// 石董会 AI 问答代理 —— Dify 版
// 对外输出格式与旧 ADP 版完全一致，小程序端无需任何改动

const CONFIG_PATH = process.env.AGENT_CONFIG_PATH || '/opt/siyumenghai-agent-proxy/config.json'
const config = readConfig(CONFIG_PATH)

function readConfig(p) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')) } catch (e) { return {} }
}

// Dify 地址与密钥：优先环境变量，其次 config.json，兼容原有部署习惯
const DIFY_BASE = (process.env.DIFY_BASE_URL || config.difyBaseUrl || config.upstream || 'http://127.0.0.1:8080').replace(/\/+$/, '')
const DIFY_KEY = process.env.DIFY_API_KEY || config.difyApiKey || config.appkey || ''
const PORT = Number(process.env.PORT || 2035)
const UPSTREAM_TIMEOUT = Number(process.env.UPSTREAM_TIMEOUT || 55000)

// ---- 会话 ID：沿用旧算法，保证迁移前后同一用户的会话连续 ----
function conversationId(userId, clientConversation) {
  const base = crypto.createHash('sha256').update('sdh:' + userId).digest('hex')
  if (typeof clientConversation === 'string' && /^[a-zA-Z0-9_-]{1,64}$/.test(clientConversation)) {
    return base.slice(0, 31) + '-' + clientConversation.slice(0, 32)
  }
  return base
}

// Dify 的 user 标识要求稳定且不含冒号，做一次规范化
function difyUser(userId) {
  return 'sdh-' + crypto.createHash('sha1').update(String(userId)).digest('hex').slice(0, 32)
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

    const messages = Array.isArray(payload.messages) ? payload.messages : []
    if (!messages.length) return bad(res, 'empty messages')

    // 与旧版一致：只取最后一条非空 user 文本。Dify 按 conversation_id 服务端维护上下文
    let userText = ''
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i]
      if (m && m.role === 'user') {
        if (Array.isArray(m.content)) {
          userText = m.content.filter((x) => x && x.type === 'text').map((x) => x.text || '').join('')
        } else if (typeof m.content === 'string') {
          userText = m.content
        }
        if (userText.trim()) break
      }
    }
    if (!userText.trim()) return bad(res, 'no user message text')

    const userId = String(payload.user_id || 'anonymous').slice(0, 64)
    const convId = conversationId(userId, payload.conversation_id)

    const upBody = JSON.stringify({
      inputs: {},
      query: userText.trim(),
      response_mode: 'streaming',
      conversation_id: convId,
      user: difyUser(userId)
    })

    try {
      if (payload.stream) {
        return await streamChat(upBody, res, payload.stream_format === 'events')
      }
      return await blockingChat(upBody, res)
    } catch (e) {
      if (!res.headersSent) {
        res.writeHead(502, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ error: { message: '服务暂时不可用' } }))
      } else if (!res.writableEnded) {
        res.end()
      }
    }
  })
}

// ---------- 非流式：返回 OpenAI 兼容结构，兼容旧客户端 ----------
async function blockingChat(upBody, res) {
  let raw
  try {
    raw = await postDify('/v1/chat-messages', upBody, false)
  } catch (e) {
    res.writeHead(502, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ error: { message: '服务暂时不可用' } }))
    return
  }

  if (raw.status !== 200) {
    res.writeHead(mapStatus(raw.status), { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
    res.end(JSON.stringify({ error: { message: '服务暂时不可用' } }))
    return
  }

  const answer = collectSseAnswer(raw.text)
  if (!answer) {
    res.writeHead(502, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ error: { message: 'empty reply from upstream' } }))
    return
  }

  const content = cleanMarkdown(answer)
  res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
  res.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content } }] }))
}

// ---------- 流式：NDJSON 逐行事件，格式与旧版完全一致 ----------
async function streamChat(upBody, res, events = false) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT)
  res.on('close', () => controller.abort())

  const emit = (event) => {
    if (res.destroyed || res.writableEnded) return
    res.write(events ? JSON.stringify(event) + '\n' : event.type === 'delta' ? event.text : event.type === 'error' ? '\n（回复未完成，请重试）' : '')
  }

  let headSent = false
  let sawEnd = false
  let finalAnswer = ''
  let errored = false

  try {
    const iterator = streamDify('/v1/chat-messages', upBody, controller.signal)

    // 首个 chunk 之前不发 header，便于错误时返回 502 JSON
    for await (const piece of iterator) {
      if (!headSent) {
        if (piece.__head && piece.status !== 200) {
          res.writeHead(mapStatus(piece.status), { 'Content-Type': 'application/json' })
          res.end(JSON.stringify({ error: { message: '服务暂时不可用' } }))
          return
        }
        headSent = true
        res.writeHead(200, {
          'Content-Type': events ? 'application/x-ndjson; charset=utf-8' : 'text/plain; charset=utf-8',
          'Cache-Control': 'no-store',
          'X-Accel-Buffering': 'no'
        })
      }

      const chunk = piece.text
      if (chunk) {
        for (const line of chunk.split('\n')) {
          const s = line.trim()
          if (!s.startsWith('data:')) continue
          const jsonStr = s.slice(5).trim()
          if (!jsonStr) continue
          let ev
          try { ev = JSON.parse(jsonStr) } catch (_) { continue }

          // 只处理 assistant 正式回答，丢弃 agent_thought / 思考过程
          if (ev.event === 'message' || ev.event === 'agent_message') {
            const t = ev.answer || ''
            if (t) emit({ type: 'delta', text: t })
          } else if (ev.event === 'message_end') {
            sawEnd = true
            const usage = (ev.metadata || {}).usage
            // 结束时用全文覆盖一次，修正流式拼接可能产生的偏差
            finalAnswer = typeof ev.answer === 'string' ? ev.answer : finalAnswer
            if (finalAnswer) emit({ type: 'replace', text: finalAnswer })
            if (usage) console.log('tokens', JSON.stringify(usage))
          } else if (ev.event === 'error') {
            errored = true
          }
        }
      }

      if (piece.__done) break
    }
  } catch (e) {
    errored = true
  } finally {
    clearTimeout(timer)
  }

  if (res.destroyed || res.writableEnded) return

  // 只有「正常结束」且「拿到非空回答」才算成功
  if (!errored && sawEnd && finalAnswer.trim()) {
    emit({ type: 'done', text: finalAnswer })
  } else {
    emit({ type: 'error' })
  }
  if (!res.writableEnded) res.end()
}

// ---------- 底层请求：用 Node 内置 https/http，避免依赖 fetch 版本差异 ----------
function postDify(pathname, body, wantStream) {
  return new Promise((resolve, reject) => {
    if (wantStream) return reject(new Error('use streamDify for streaming'))
    const url = new URL(DIFY_BASE + pathname)
    const lib = url.protocol === 'https:' ? https : http
    const req = lib.request(
      {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: 'POST',
        headers: {
          Authorization: `Bearer ${DIFY_KEY}`,
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body)
        },
        timeout: UPSTREAM_TIMEOUT
      },
      (r) => {
        let text = ''
        r.setEncoding('utf8')
        r.on('data', (c) => (text += c))
        r.on('end', () => resolve({ status: r.statusCode, text }))
      }
    )
    req.on('timeout', () => req.destroy(new Error('upstream timeout')))
    req.on('error', reject)
    req.write(body)
    req.end()
  })
}

// 流式：以 async generator 吐出文本片段，首个 yield 一定是 __head（等待响应头到达后再交出）
async function* streamDify(pathname, body, signal) {
  const url = new URL(DIFY_BASE + pathname)
  const lib = url.protocol === 'https:' ? https : http

  const queue = []            // 已到达的数据块
  let notify = null           // 唤醒 generator 的回调
  let head = null             // 响应头
  let ended = false           // 响应结束
  let error = null            // 失败原因

  const wake = () => { if (notify) { const n = notify; notify = null; n() } }

  const req = lib.request(
    {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      method: 'POST',
      headers: {
        Authorization: `Bearer ${DIFY_KEY}`,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      },
      timeout: UPSTREAM_TIMEOUT
    },
    (r) => {
      head = { status: r.statusCode }
      r.setEncoding('utf8')
      r.on('data', (c) => { queue.push(c); wake() })
      r.on('end', () => { ended = true; wake() })
      r.on('error', (e) => { error = e; ended = true; wake() })
    }
  )

  if (signal) {
    const onAbort = () => { try { req.destroy(new Error('aborted')) } catch (_) {} }
    if (signal.aborted) onAbort()
    else signal.addEventListener('abort', onAbort, { once: true })
  }

  req.on('timeout', () => req.destroy(new Error('upstream timeout')))
  req.on('error', (e) => { error = e; ended = true; wake() })

  req.write(body)
  req.end()

  // 等响应头，拿到状态码再往下走
  while (!head && !error && !ended) {
    await new Promise((r) => { notify = r })
  }
  if (error) throw error
  yield { __head: true, status: head ? head.status : 0 }

  // 逐个交出数据块
  while (queue.length || !ended) {
    if (!queue.length) {
      if (error) throw error
      await new Promise((r) => { notify = r })
      continue
    }
    yield { text: queue.shift() }
  }
  if (error) throw error
  yield { __done: true }
}

// ---------- 工具 ----------
function collectSseAnswer(raw) {
  let answer = ''
  let ended = false
  for (const line of raw.split('\n')) {
    const t = line.trim()
    if (!t.startsWith('data:')) continue
    const jsonStr = t.slice(5).trim()
    if (!jsonStr) continue
    try {
      const ev = JSON.parse(jsonStr)
      if (ev.event === 'message' || ev.event === 'agent_message') answer += ev.answer || ''
      else if (ev.event === 'message_end') { if (typeof ev.answer === 'string' && ev.answer) answer = ev.answer; ended = true }
      else if (ev.event === 'error') return ''
    } catch (_) { continue }
  }
  return ended ? cleanMarkdown(answer) : cleanMarkdown(answer)
}

function mapStatus(status) {
  return status === 429 ? 429 : status >= 500 ? 502 : 502
}

function cleanMarkdown(text) {
  return text
    .split('\n')
    .map((line) => {
      let l = line
      l = l.replace(/^#{1,6}\s*/, '')
      l = l.replace(/^>\s?/, '')
      l = l.replace(/^\s*[-*+]\s+/, '')
      l = l.replace(/\*\*/g, '')
      l = l.replace(/\*/g, '')
      l = l.replace(/`/g, '')
      return l.replace(/\s+$/, '')
    })
    .join('\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function bad(res, msg) {
  res.writeHead(400, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify({ error: { message: msg } }))
}

if (require.main === module) {
  http.createServer(handler).listen(PORT, '127.0.0.1', () => {
    console.log(`石董会 AI 问答代理（Dify 版）监听 127.0.0.1:${PORT}`)
    console.log(`  上游 Dify : ${DIFY_BASE}`)
    console.log(`  API Key   : ${DIFY_KEY ? '已配置' : '未配置'}`)
    if (!DIFY_KEY) console.warn('  [警告] 未配置 Dify API Key，所有回答都会失败')
  })
}

module.exports = { handler, cleanMarkdown, collectSseAnswer, conversationId }
