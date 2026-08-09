# 视频逐字稿服务

这是 `video-downloader-20260808-17.html` 使用的单机排队识别服务。网页只提交已经解析出的腾讯视频地址，服务用 FFmpeg 提取音频，再由 `faster-whisper` 的 `large-v3-turbo` INT8 模型在服务器本地识别；不调用按量付费的语音接口。

运行保护由 `server.py` 定义：单条最长 10 分钟、同一访客最多 2 个活动任务、全站同时只识别 1 条、队列最多 20 条、相同链接转写结果缓存 7 天。试运行期间不限制每人或全站每日条数；临时音频在任务结束后删除。

`GET /images?url=...` 只为腾讯视频号封面和头像提供即时转发，不写入服务器磁盘。该接口限制腾讯图片域名和 5MB 文件上限。

生产部署目录为 `/opt/siyumenghai-transcriber`，模型目录为 `/var/lib/siyumenghai-transcriber/models/large-v3-turbo`，systemd 服务名为 `siyumenghai-transcriber.service`，仅监听 `127.0.0.1:2026`，由 Nginx 的 `/api/transcripts/` 反向代理。

## 固定容量保护

`maintenance/` 中的 systemd timer 每 15 分钟删除过期任务、七天缓存和临时文件，并把 journal、Nginx 与 Chromium 缓存限制在固定范围。根分区可用空间低于 10 GiB 时会清理独立的 Chromium 缓存；低于 6 GiB 时，服务拒绝新的转写任务，但网站查询、下载、评论和正在运行的任务不受影响。

更新代码后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart siyumenghai-transcriber
curl -fsS http://127.0.0.1:2026/healthz
```
