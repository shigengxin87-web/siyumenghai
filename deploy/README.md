# 腾讯云发布与回滚

自动发布每 5 分钟检查 GitHub `main`。它只下载变化文件，优先使用 jsDelivr，失败后切换 GitHub Raw；所有文件先写入独立 release 并校验，完成后才原子切换 `current`。

手动发布：

```bash
sudo -u site-deploy /usr/bin/flock -w 10 /tmp/siyumenghai-sync.lock /home/site-deploy/bin/sync-siyumenghai.sh
```

一键回滚到上一个已验收版本：

```bash
sudo -u site-deploy /home/site-deploy/bin/rollback-siyumenghai.sh
```

当前版本与上一个版本：

```bash
readlink -f /var/www/releases/siyumenghai/current
readlink -f /var/www/releases/siyumenghai/previous
```

发布失败会删除 staging，且不会切换 `current`。可用 `SIYUMENGHAI_FAILPOINT=download_timeout|bad_release|after_download|before_switch` 做安全故障演练。
