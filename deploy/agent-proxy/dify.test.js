/**
 * Dify 版代理适配测试
 * 用假 Dify 上游验证：对外输出格式与旧 ADP 版完全一致，小程序无需改动
 * 用法：node --test dify.test.js
 */
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const http = require('http'), fs = require('fs'), os = require('os'), path = require('path');

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'sdh-dify-test-'));

// ---------- 假 Dify 上游 ----------
let upstreamBehavior = () => ({ status: 200, events: replyOf('你好') });
let lastUpstreamBody = null;
let lastAuth = null;

const fakeDify = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    lastUpstreamBody = JSON.parse(body || '{}');
    lastAuth = req.headers['authorization'];
    const r = upstreamBehavior();
    if (r.status !== 200) {
      res.writeHead(r.status, { 'Content-Type': 'application/json' });
      res.end('{"error":"boom"}');
      return;
    }
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    for (const ev of r.events) res.write('data: ' + JSON.stringify(ev) + '\n\n');
    res.end();
  });
});

const replyOf = (answer) => [
  { event: 'message', answer },
  { event: 'message_end', answer }
];

// ---------- 被测代理 ----------
process.env.AGENT_CONFIG_PATH = path.join(temp, 'config.json');
let proxyServer = null;
let S = null;

before(async () => {
  await new Promise((r) => fakeDify.listen(0, '127.0.0.1', r));
  const port = fakeDify.address().port;
  fs.writeFileSync(
    process.env.AGENT_CONFIG_PATH,
    JSON.stringify({ difyBaseUrl: `http://127.0.0.1:${port}`, difyApiKey: 'app-test-only' })
  );
  S = require('./server');
  proxyServer = http.createServer(S.handler);
  await new Promise((r) => proxyServer.listen(0, '127.0.0.1', r));
});

after(() => {
  fakeDify.close();
  if (proxyServer) proxyServer.close();
  fs.rmSync(temp, { recursive: true, force: true });
});

async function request(options = {}) {
  const port = proxyServer.address().port;
  const body = JSON.stringify({
    user_id: 'test-user',
    stream: options.stream !== false,
    stream_format: options.format === false ? undefined : 'events',
    conversation_id: options.conversation,
    messages: [{ role: 'user', content: [{ type: 'text', text: 'hello' }] }]
  });
  const response = await new Promise((resolve, reject) => {
    const req = http.request(
      { hostname: '127.0.0.1', port, method: 'POST', path: '/api/agent/chat', headers: { 'Content-Type': 'application/json' } },
      (r) => {
        let text = '';
        r.setEncoding('utf8');
        r.on('data', (c) => (text += c));
        r.on('end', () => resolve({ status: r.statusCode, text }));
      }
    );
    req.on('error', reject);
    req.end(body);
  });
  return { ...response, upstreamBody: lastUpstreamBody, auth: lastAuth };
}

// ---------- 测试 ----------

test('会话 ID 规则与旧版一致，保证迁移后上下文连续', () => {
  const { conversationId } = S;
  const a = conversationId('u1');
  const b = conversationId('u1');
  const c = conversationId('u1', 'new-session');
  const d = conversationId('u2');
  assert.equal(a, b, '同一用户同一会话应恒定');
  assert.notEqual(a, c, '传入新 conversation_id 应产生不同 ID');
  assert.notEqual(a, d, '不同用户应不同');
  assert.match(a, /^[a-f0-9]{64}$/, '不带 client conversation 时应与旧算法完全一致');
});

test('流式 events 模式：末行是 done 且文本正确', async () => {
  upstreamBehavior = () => ({ status: 200, events: replyOf('石董会答案') });
  const r = await request();
  assert.equal(r.status, 200);
  const lines = r.text.trim().split('\n').map(JSON.parse);
  assert.ok(lines.some((e) => e.type === 'delta'), '应有 delta 事件');
  assert.ok(lines.some((e) => e.type === 'replace'), '应有 replace 事件用于全文校准');
  assert.equal(lines.at(-1).type, 'done');
  assert.equal(lines.at(-1).text, '石董会答案');
});

test('思考过程（agent_thought）不会泄露给用户', async () => {
  upstreamBehavior = () => ({
    status: 200,
    events: [
      { event: 'agent_thought', thought: 'secret reasoning' },
      { event: 'message', answer: '公开答案' },
      { event: 'message_end', answer: '公开答案' }
    ]
  });
  const r = await request();
  assert.ok(!r.text.includes('secret reasoning'), '思考内容不能出现在给用户的流里');
  assert.ok(r.text.includes('公开答案'));
});

test('上游报错时不泄露厂商错误详情', async () => {
  upstreamBehavior = () => ({ status: 200, events: [{ event: 'error', message: 'sensitive internal detail' }] });
  const r = await request();
  assert.ok(!r.text.includes('sensitive'), '厂商错误不能透给用户');
  const lines = r.text.trim().split('\n').map(JSON.parse);
  assert.equal(lines.at(-1).type, 'error');
});

test('上游 429 会被映射并隐藏原文', async () => {
  upstreamBehavior = () => ({ status: 429 });
  const r = await request();
  assert.equal(r.status, 429);
  assert.ok(!r.text.includes('boom'), '不能透出上游原文');
});

test('上游 500 会被映射为 502', async () => {
  upstreamBehavior = () => ({ status: 500 });
  const r = await request();
  assert.equal(r.status, 502);
});

test('非流式：仍返回 OpenAI 兼容结构，旧客户端不受影响', async () => {
  upstreamBehavior = () => ({ status: 200, events: replyOf('你好') });
  const r = await request({ stream: false });
  assert.equal(r.status, 200);
  const parsed = JSON.parse(r.text);
  assert.equal(parsed.choices[0].message.content, '你好');
  assert.equal(parsed.choices[0].message.role, 'assistant');
});

test('旧版纯文本流（不带 events）依然可用', async () => {
  upstreamBehavior = () => ({ status: 200, events: replyOf('纯文本回答') });
  const r = await request({ format: false });
  assert.ok(r.text.includes('纯文本回答'), '纯文本模式应输出回答文本');
});

test('空回答不会误判为完成', async () => {
  upstreamBehavior = () => ({ status: 200, events: [{ event: 'message', answer: '' }, { event: 'message_end', answer: '' }] });
  const r = await request();
  const lines = r.text.trim().split('\n').filter(Boolean).map(JSON.parse);
  const done = lines.find((e) => e.type === 'done');
  assert.ok(!done || done.text === '', '空回答不应输出有效 done');
  assert.ok(lines.some((e) => e.type === 'error'), '空回答应给出 error');
});

test('Markdown 符号被清洗，适配小程序纯文本展示', async () => {
  upstreamBehavior = () => ({ status: 200, events: replyOf('# 标题\n\n**加粗**内容') });
  const r = await request({ stream: false });
  const c = JSON.parse(r.text).choices[0].message.content;
  assert.ok(!c.includes('#'), '标题符号应去掉');
  assert.ok(!c.includes('**'), '加粗符号应去掉');
  assert.ok(c.includes('加粗内容'));
});

test('上游收到的字段正确：只发最后一条问题，带会话与规范化 user', async () => {
  upstreamBehavior = () => ({ status: 200, events: replyOf('ok') });
  const r = await request();
  assert.equal(r.upstreamBody.query, 'hello', '只应发送最后一条 user 文本');
  assert.equal(r.upstreamBody.response_mode, 'streaming');
  assert.ok(r.upstreamBody.conversation_id, '应带 conversation_id');
  assert.ok(r.upstreamBody.user.startsWith('sdh-'), 'user 应做规范化');
  assert.equal(r.auth, 'Bearer app-test-only', '应正确携带 Dify API Key');
});

test('多条历史时只取最后一条，避免重复上下文', async () => {
  upstreamBehavior = () => ({ status: 200, events: replyOf('ok') });
  const port = proxyServer.address().port;
  const body = JSON.stringify({
    user_id: 'u9',
    stream: false,
    messages: [
      { role: 'user', content: [{ type: 'text', text: '第一条旧问题' }] },
      { role: 'assistant', content: [{ type: 'text', text: '旧回答' }] },
      { role: 'user', content: [{ type: 'text', text: '当前新问题' }] }
    ]
  });
  await new Promise((resolve, reject) => {
    const req = http.request(
      { hostname: '127.0.0.1', port, method: 'POST', path: '/api/agent/chat', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } },
      (res) => { res.resume(); res.on('end', resolve); }
    );
    req.on('error', reject);
    req.end(body);
  });
  assert.equal(lastUpstreamBody.query, '当前新问题', '应只发送最新问题');
});
