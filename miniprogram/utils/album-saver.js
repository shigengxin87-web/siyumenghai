function call(api, name, options) {
  return new Promise((resolve, reject) => api[name]({ ...options, success: resolve, fail: reject }));
}
class AlbumSaver {
  constructor(api, update) { this.api = api; this.update = update; this.running = false; this.stopped = false; this.task = null; }
  async permission() {
    if (this.api.requirePrivacyAuthorize) {
      try { await call(this.api, 'requirePrivacyAuthorize', {}); }
      catch (_) { throw new Error('请先同意隐私保护指引，再点击保存'); }
    }
    const setting = await call(this.api, 'getSetting', {});
    const granted = setting.authSetting['scope.writePhotosAlbum'];
    if (granted === false) { const e = new Error('相册权限已关闭，请点击“相册权限设置”恢复后重试'); e.permission = true; throw e; }
    if (!granted) {
      try { await call(this.api, 'authorize', { scope: 'scope.writePhotosAlbum' }); }
      catch (_) { const e = new Error('未获得相册权限，请点击“相册权限设置”恢复后重试'); e.permission = true; throw e; }
    }
  }
  cancel() { this.stopped = true; if (this.task) this.task.abort(); }
  cleanup(path) { if (path) this.api.getFileSystemManager().unlink({ filePath: path, fail() {} }); }
  async download(item) {
    return new Promise((resolve, reject) => {
      this.task = this.api.downloadFile({ url: item.url, timeout: 120000,
        success: r => { if (this.stopped) { this.cleanup(r.tempFilePath); reject(new Error('已取消')); }
          else if (r.statusCode !== 200) { this.cleanup(r.tempFilePath); reject(new Error(r.statusCode === 410 ? '链接已过期，请重新解析' : `下载失败 (${r.statusCode})`)); }
          else resolve(r.tempFilePath); }, fail: () => reject(new Error(this.stopped ? '已取消' : '下载失败，请检查网络或重新解析')) });
      this.task.onProgressUpdate(p => { if (!this.stopped) this.update(item.key, { state: 'downloading', progress: p.progress, bytes: p.totalBytesWritten, totalBytes: p.totalBytesExpectedToWrite }); });
    });
  }
  async run(items) {
    if (this.running) return;
    this.running = true; this.stopped = false;
    const selected = items.filter(i => i.state !== 'saved');
    let saved = 0, failed = 0;
    try {
      await this.permission();
      if (this.stopped) return { saved, failed, cancelled: true };
      selected.forEach(i => this.update(i.key, { state: 'queued', error: '' }));
      for (const item of selected) {
        if (this.stopped) break;
        let path;
        try {
          this.update(item.key, { state: 'downloading', progress: 0, error: '' });
          path = await this.download(item);
          if (this.stopped) break;
          this.update(item.key, { state: 'saving', progress: 100 });
          // Album success is the only source of a saved state. An in-flight
          // system album write cannot be aborted; finish it before stopping.
          await call(this.api, item.kind === 'video' ? 'saveVideoToPhotosAlbum' : 'saveImageToPhotosAlbum', { filePath: path });
          saved++; this.update(item.key, { state: 'saved', error: '' });
        } catch (e) {
          if (!this.stopped) { failed++; this.update(item.key, { state: 'failed', error: e.message || e.errMsg || '相册保存失败，请检查相册权限后重试' }); }
        } finally { this.task = null; this.cleanup(path); }
      }
      if (this.stopped) selected.forEach(i => this.update(i.key, { cancelPending: true }));
      return { saved, failed, cancelled: this.stopped };
    } finally { this.running = false; }
  }
}
module.exports = { AlbumSaver };
