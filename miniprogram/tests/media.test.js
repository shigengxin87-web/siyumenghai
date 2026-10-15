const { test } = require('node:test');
const assert = require('node:assert/strict');
const { normalize, detect, sameOrigin } = require('../utils/media-api');
const { AlbumSaver } = require('../utils/album-saver');
const later = fn => queueMicrotask(fn);
function mock(options = {}) {
  const log = { downloads: [], writes: [], removed: [], permissions: 0 };
  const api = {
    requirePrivacyAuthorize(o) { later(() => options.privacyDenied ? o.fail({}) : o.success({})); },
    getSetting(o) { later(() => o.success({ authSetting: { 'scope.writePhotosAlbum': options.granted } })); },
    authorize(o) { log.permissions++; later(() => options.deny ? o.fail({}) : o.success({})); },
    getFileSystemManager() { return { unlink(o) { log.removed.push(o.filePath); } }; },
    downloadFile(o) {
      log.downloads.push(o.url); let aborted = false;
      const task = { abort() { aborted = true; o.fail({}); }, onProgressUpdate(fn) { later(() => fn({ progress: 37, totalBytesWritten: 37, totalBytesExpectedToWrite: 100 })); } };
      later(() => {
        if (options.onDownload) options.onDownload(task);
        if (aborted) return;
        if (options.downloadFail) o.fail({});
        else o.success({ statusCode: options.http || 200, tempFilePath: '/tmp/' + log.downloads.length });
      }); return task;
    },
    saveVideoToPhotosAlbum(o) { log.writes.push('video'); later(() => options.saveFail ? o.fail({ errMsg: 'album error' }) : o.success({})); },
    saveImageToPhotosAlbum(o) { log.writes.push('image'); later(() => options.saveFail ? o.fail({ errMsg: 'album error' }) : o.success({})); }
  };
  return { api, log };
}
const image = { key: 'i', kind: 'image', url: 'https://siyumenghai.cn/api/xhs/media/a?proxy=1', state: 'idle' };
function saver(options = {}) {
  const { api, log } = mock(options), updates = [], current = {};
  const instance = new AlbumSaver(api, (k, p) => { updates.push([k, p]); Object.assign(current, p); });
  return { instance, log, updates, current };
}
test('three contracts normalize and xhs avoids external redirect', () => {
  assert.match(normalize('xhs', { title: 't', video: '/api/xhs/media/a' }).items[0].url, /proxy=1$/);
  assert.equal(normalize('douyin', { images: ['/api/douyin/media/a', '/api/douyin/media/b'] }).items.length, 2);
  for (const payload of [{ data: { feedInfo: { videoUrl: 'https://video.qq.com/v.mp4' } } }, { data: { errCode: 0, data: { feedInfo: { h264VideoInfo: { videoUrl: 'https://video.qq.com/v.mp4' } } } } }]) {
    assert.match(normalize('channels', payload).items[0].url, /\/api\/transcripts\/media\?url=/);
  }
  assert.throws(() => sameOrigin('https://evil.test/a'));
  assert.throws(() => sameOrigin('//evil.test/a'));
  assert.throws(() => normalize('xhs', { kind: 'author' }));
  assert.throws(() => normalize('channels', { code: -1, msg: 'error' }));
});
test('detect platform from share text', () => {
  assert.equal(detect('分享 https://v.douyin.com/abc/', 'channels'), 'douyin');
  assert.equal(detect('https://xhslink.com/a', 'channels'), 'xhs');
  assert.equal(detect('https://weixin.qq.com/sph/a', 'xhs'), 'channels');
  assert.equal(detect('https://douyin.com.evil/a', 'channels'), 'channels');
});
test('permission denial blocks transfer, recovery permits retry', async () => {
  const denied = saver({ granted: false });
  await assert.rejects(denied.instance.run([image]), e => e.permission === true);
  assert.equal(denied.log.downloads.length, 0);
  const recovered = saver({ granted: true }); await recovered.instance.run([image]);
  assert.equal(recovered.current.state, 'saved');
});
test('first permission denial and privacy denial never download', async () => {
  for (const options of [{ deny: true }, { privacyDenied: true }]) {
    const s = saver(options); await assert.rejects(s.instance.run([image])); assert.equal(s.log.downloads.length, 0);
  }
});
test('progress is actual, image and video save success clean temporary files', async () => {
  const s = saver({ granted: true }); const r = await s.instance.run([image, { ...image, key: 'v', kind: 'video' }]);
  assert.equal(r.saved, 2); assert.deepEqual(s.log.writes, ['image', 'video']);
  assert.equal(s.log.removed.length, 2); assert.ok(s.updates.some(([, p]) => p.progress === 37));
});
test('failed save is never marked saved; retries omit already saved items', async () => {
  const s = saver({ granted: true, saveFail: true }); const r = await s.instance.run([image]);
  assert.equal(r.failed, 1); assert.equal(s.current.state, 'failed'); assert.equal(s.log.removed.length, 1);
  const good = saver({ granted: true }); await good.instance.run([{ ...image, state: 'saved' }, { ...image, key: 'retry', state: 'failed' }]);
  assert.equal(good.log.downloads.length, 1);
});
test('duplicate save calls share one active run', async () => {
  const s = saver({ granted: true }); await Promise.all([s.instance.run([image]), s.instance.run([image])]); assert.equal(s.log.downloads.length, 1);
});
test('cancel aborts transfer and skips remaining queue', async () => {
  let s; s = saver({ granted: true, onDownload: () => s.instance.cancel() });
  const r = await s.instance.run([image, { ...image, key: '2' }]);
  assert.equal(r.cancelled, true); assert.equal(s.log.writes.length, 0); assert.equal(s.log.downloads.length, 1);
});
test('HTTP failure and network failure never write album', async () => {
  for (const options of [{ http: 410 }, { downloadFail: true }]) {
    const s = saver({ granted: true, ...options }); const r = await s.instance.run([image]); assert.equal(r.failed, 1); assert.equal(s.log.writes.length, 0);
  }
});
test('partial batch failure continues and records per item result', async () => {
  const { api, log } = mock({ granted: true }); let count = 0; const results = {};
  api.saveImageToPhotosAlbum = o => later(() => ++count === 1 ? o.fail({}) : o.success({}));
  const s = new AlbumSaver(api, (key, patch) => { results[key] = { ...results[key], ...patch }; });
  const r = await s.run([image, { ...image, key: '2' }]);
  assert.equal(r.saved, 1); assert.equal(r.failed, 1); assert.equal(results.i.state, 'failed'); assert.equal(results['2'].state, 'saved'); assert.equal(log.removed.length, 2);
});
