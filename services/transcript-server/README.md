# 视频逐字稿服务

这是 `video-downloader-20260808-17.html` 使用的单机排队识别服务。网页只提交已经解析出的腾讯视频地址，服务用 FFmpeg 提取音频，再由 `faster-whisper` 的 `large-v3-turbo` INT8 模型在服务器本地识别；不调用按量付费的语音接口。

运行保护由 `server.py` 定义：单条最长 10 分钟、同一访客最多 2 个活动任务、全站同时只识别 1 条、队列最多 20 条、相同链接转写结果缓存 7 天。试运行期间不限制每人或全站每日条数；临时音频在任务结束后删除。

生产部署目录为 `/opt/siyumenghai-transcriber`，模型目录为 `/var/lib/siyumenghai-transcriber/models/large-v3-turbo`，systemd 服务名为 `siyumenghai-transcriber.service`，仅监听 `127.0.0.1:2026`，由 Nginx 的 `/api/transcripts/` 反向代理。

更新代码后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart siyumenghai-transcriber
curl -fsS http://127.0.0.1:2026/healthz
```
