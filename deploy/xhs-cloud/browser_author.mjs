import fs from 'node:fs/promises';

const endpoint = process.env.XHS_CDP_ENDPOINT || 'http://127.0.0.1:9223';
const cookieFile = process.env.XHS_COOKIE_FILE || '/etc/siyumenghai-xhs/cookie.txt';

class CDP {
  constructor(url) {
    this.nextId = 1;
    this.pending = new Map();
    this.socket = new WebSocket(url);
    this.socket.addEventListener('message', event => {
      const message = JSON.parse(String(event.data));
      if (!message.id) return;
      const waiter = this.pending.get(message.id);
      if (!waiter) return;
      this.pending.delete(message.id);
      if (message.error) waiter.reject(new Error('Browser operation failed'));
      else waiter.resolve(message.result || {});
    });
  }
  async open() {
    if (this.socket.readyState === WebSocket.OPEN) return;
    await new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, { once:true });
      this.socket.addEventListener('error', () => reject(new Error('Cannot connect to local browser')), { once:true });
    });
  }
  send(method, params = {}, sessionId) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {resolve, reject});
      this.socket.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
    });
  }
  close() { this.socket.close(); }
}

function parseCookies(value) {
  return value.split(';').map(part => part.trim()).filter(Boolean).flatMap(part => {
    const index = part.indexOf('=');
    if (index < 1) return [];
    return [{ name:part.slice(0,index), value:part.slice(index + 1), domain:'.xiaohongshu.com', path:'/', secure:true }];
  });
}

// Wait for the profile page to render its note list, then walk the whole
// __INITIAL_STATE__ and collect note-like entries. The profile page is SPA and
// may lazy-load; poll until we have notes or time out.
const expression = [
  '(async () => {',
  '  const until = Date.now() + 20000;',
  '  let found = {};',
  '  while (Date.now() < until) {',
  '    const state = window.__INITIAL_STATE__ || {};',
  '    const walk = node => {',
  '      if (!node) return;',
  '      if (Array.isArray(node)) { for (const item of node) walk(item); return; }',
  '      if (typeof node !== "object") return;',
  '      const id = String(node.noteId || "");',
  '      if (/^[0-9a-f]{20,32}$/i.test(id) && (node.cover || node.imageList || node.video)) {',
  '        found[id.toLowerCase()] = {',
  '          noteId: id,',
  '          displayTitle: String(node.displayTitle || node.title || "").slice(0,200),',
  '          type: node.type ? String(node.type) : (node.video ? "video" : "normal"),',
  '          time: node.time || node.lastUpdateTime || null,',
  '          cover: node.cover || null,',
  '          imageList: node.imageList || null,',
  '          video: node.video ? {} : null,',
  '        };',
  '      }',
  '      for (const key of Object.keys(node)) walk(node[key]);',
  '    };',
  '    walk(state);',
  '    if (Object.keys(found).length >= 6) break;',
  '    await new Promise(r => setTimeout(r, 500));',
  '  }',
  '  const notes = Object.values(found).slice(0, 30);',
  '  if (!notes.length) return null;',
  '  let nickname = "";',
  '  const user = state.user || {};',
  '  nickname = user.nickname || user.userPageData?.user?.nickname || "";',
  '  return JSON.stringify({ notes, user: { nickname: String(nickname || "") } });',
  '})()'
].join(' ');

async function main() {
  const input = JSON.parse(await new Promise(resolve => {
    let value = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => {
      value += chunk;
      if (value.length > 16384) process.stdin.destroy(new Error('Request too long'));
    });
    process.stdin.on('end', () => resolve(value));
  }));
  const parsed = new URL(input.url);
  if (parsed.protocol !== 'https:' || !['xiaohongshu.com','www.xiaohongshu.com'].includes(parsed.hostname) || !/^\/user\/profile\//.test(parsed.pathname)) {
    throw new Error('Invalid author profile URL');
  }
  const version = await (await fetch(endpoint + '/json/version', {signal: AbortSignal.timeout(5000)})).json();
  const cdp = new CDP(version.webSocketDebuggerUrl);
  await cdp.open();
  let targetId;
  try {
    ({targetId} = await cdp.send('Target.createTarget', {url:'about:blank'}));
    const {sessionId} = await cdp.send('Target.attachToTarget', {targetId, flatten:true});
    await cdp.send('Network.enable', {}, sessionId);
    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Network.setCookies', {cookies:parseCookies(await fs.readFile(cookieFile, 'utf8'))}, sessionId);
    await cdp.send('Page.navigate', {url:input.url}, sessionId);
    await new Promise(resolve => setTimeout(resolve, 6000));
    const result = await cdp.send('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true}, sessionId);
    const value = result.result?.value;
    if (!value || value === 'null') throw new Error('Author notes unavailable in browser session');
    JSON.parse(value);
    process.stdout.write(value);
  } finally {
    if (targetId) await cdp.send('Target.closeTarget', {targetId}).catch(() => {});
    cdp.close();
  }
}
main().catch(() => {
  process.stderr.write('Browser author extraction unsuccessful\n');
  process.exitCode = 1;
});
