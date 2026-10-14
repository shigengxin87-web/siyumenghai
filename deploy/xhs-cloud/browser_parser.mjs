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

// The browser page is asynchronous. Wait for the specific note instead of
// dumping the entire logged-in account's reactive state or recommendation feed.
const expression = [
  '(async () => {',
  '  const until = Date.now() + 16000;',
  '  while (Date.now() < until) {',
  '    const id = location.pathname.split("/").filter(Boolean).at(-1) || "";',
  '    const wrapper = window.__INITIAL_STATE__?.note?.noteDetailMap?.[id];',
  '    const note = wrapper?.note;',
  '    if (/^[0-9a-f]{20,32}$/i.test(id) && note && String(note.noteId).toLowerCase() === id.toLowerCase()) {',
  '      return JSON.stringify({',
  '        noteId: String(note.noteId), title: String(note.title || "").slice(0,500),',
  '        desc: String(note.desc || "").slice(0,20000),',
  '        user: {nickname: String(note.user?.nickname || "")},',
  '        time: note.time || null,',
  '        interactInfo: {likedCount:note.interactInfo?.likedCount, collectedCount:note.interactInfo?.collectedCount, commentCount:note.interactInfo?.commentCount, shareCount:note.interactInfo?.shareCount},',
  '        imageList: (note.imageList || []).slice(0,100).map(image => ({urlDefault:image.urlDefault, urlPre:image.urlPre, url:image.url})),',
  '        video: note.video || null',
  '      });',
  '    }',
  '    await new Promise(resolve => setTimeout(resolve,400));',
  '  }',
  '  return null;',
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
  if (parsed.protocol !== 'https:' || !['xiaohongshu.com','www.xiaohongshu.com'].includes(parsed.hostname) || parsed.username || parsed.password || (parsed.port && parsed.port !== '443')) throw new Error('Invalid note URL');
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
    await new Promise(resolve => setTimeout(resolve,5000));
    const result = await cdp.send('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true}, sessionId);
    const value = result.result?.value;
    if (!value || value === 'null') throw new Error('Note unavailable in browser session');
    JSON.parse(value);
    process.stdout.write(value);
  } finally {
    if (targetId) await cdp.send('Target.closeTarget', {targetId}).catch(() => {});
    cdp.close();
  }
}
main().catch(() => {
  process.stderr.write('Browser note extraction unsuccessful\n');
  process.exitCode = 1;
});
