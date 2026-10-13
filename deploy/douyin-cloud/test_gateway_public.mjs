import test from 'node:test';
import assert from 'node:assert/strict';

process.env.DTK_API_KEY = 'internal-test-key';
process.env.DTK_URL = 'http://127.0.0.1:1';

const { server } = await import('./gateway.mjs');

test('public parse endpoint does not require an access code', async t => {
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  t.after(() => new Promise(resolve => server.close(resolve)));

  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/api/douyin/parse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: 'https://v.douyin.com/test/' }),
  });
  const body = await response.json();

  assert.notEqual(response.status, 401);
  assert.equal(response.status, 502);
  assert.equal(body.error, '暂时无法连接解析服务');
});
