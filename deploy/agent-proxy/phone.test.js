/**
 * 手机号授权后端测试
 * 用本地假微信接口（token + getuserphonenumber）验证 /api/phone 关键路径，
 * 不触碰真实 AppSecret、不联网。运行：node --test phone.test.js
 */
const { test, before, after } = require('node:test')
const assert = require('node:assert/strict')
const http = require('http'), fs = require('fs'), os = require('os'), path = require('path')

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'sdh-phone-test-'))
const PHONES = path.join(temp, 'phones.json')

// 假微信：/cgi-bin/token 与 /wxa/business/getuserphonenumber
let wxBehavior = () => ({ phone: '13800138000' })
const fakeWx = http.createServer((req, res) => {
  let body = ''
  req.on('data', (c) => (body += c))
  req.on('end', () => {
    const r = wxBehavior()
    res.writeHead(200, { 'Content-Type': 'application/json' })
    if (r.errcode !== undefined) {
      res.end(JSON.stringify({ errcode: r.errcode, errmsg: r.errmsg || '' }))
    } else if (req.url.includes('/cgi-bin/token')) {
      res.end(JSON.stringify({ access_token: 'test-token-123', expires_in: 7200 }))
    } else if (req.url.includes('/wxa/business/getuserphonenumber')) {
      res.end(JSON.stringify({ errcode: 0, phone_info: { purePhoneNumber: r.phone || '13800138000' } }))
    } else {
      res.end('{}')
    }
  })
})

let S = null
let proxy = null

before(async () => {
  await new Promise((r) => fakeWx.listen(0, '127.0.0.1', r))
  const port = fakeWx.address().port
  process.env.WX_API_BASE = `http://127.0.0.1:${port}`
  process.env.WX_APPSECRET = 'test-secret'
  process.env.PHONES_PATH = PHONES
  // 确保本测试拿到的模块实例使用上面的环境变量（避免被其他测试先加载时缓存覆盖）
  delete require.cache[require.resolve('./server')]
  S = require('./server')
  proxy = http.createServer(S.handler)
  await new Promise((r) => proxy.listen(0, '127.0.0.1', r))
})

after(() => {
  fakeWx.close()
  if (proxy) proxy.close()
  fs.rmSync(temp, { recursive: true, force: true })
})

async function postPhone(payload) {
  const port = proxy.address().port
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(payload)
    const req = http.request(
      { hostname: '127.0.0.1', port, method: 'POST', path: '/api/phone', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } },
      (res) => {
        let text = ''
        res.setEncoding('utf8')
        res.on('data', (c) => (text += c))
        res.on('end', () => resolve({ status: res.statusCode, json: text ? JSON.parse(text) : null }))
      }
    )
    req.on('error', reject)
    req.end(body)
  })
}

test('maskPhone 正确脱敏：中间四位打码', () => {
  assert.equal(S.maskPhone('13800138000'), '138****8000')
  assert.equal(S.maskPhone(''), '')
  assert.equal(S.maskPhone('12345'), '12345')
})

test('缺少 code 返回 400', async () => {
  const r = await postPhone({ user_id: 'u1' })
  assert.equal(r.status, 400)
  assert.equal(r.json.error.message, 'missing code')
})

test('GET 方法返回 405', async () => {
  const port = proxy.address().port
  const r = await new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, method: 'GET', path: '/api/phone' }, (res) => {
      res.resume()
      res.on('end', () => resolve({ status: res.statusCode }))
    })
    req.on('error', reject)
    req.end()
  })
  assert.equal(r.status, 405)
})

test('有效 code 返回脱敏手机号并落盘真实号码', async () => {
  wxBehavior = () => ({ phone: '13912345678' })
  const r = await postPhone({ user_id: 'u-ok', code: 'valid-code' })
  assert.equal(r.status, 200)
  assert.equal(r.json.ok, true)
  assert.equal(r.json.phoneMasked, '139****5678')
  const stored = JSON.parse(fs.readFileSync(PHONES, 'utf8'))
  assert.equal(stored['u-ok'].phone, '13912345678', '真实号码只落服务端')
})

test('微信返回 errcode 时返回 502 且不落盘', async () => {
  wxBehavior = () => ({ errcode: 40001 })
  const r = await postPhone({ user_id: 'u-err', code: 'bad-code' })
  assert.equal(r.status, 502)
  const stored = JSON.parse(fs.readFileSync(PHONES, 'utf8'))
  assert.equal(stored['u-err'], undefined, '失败不应写入号码')
})
