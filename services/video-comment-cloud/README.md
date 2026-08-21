# 视频评论云端任务服务

独立端口 `2033`，只接收 `https://weixin.qq.com/sph/` 分享链接。浏览器不会连接或控制用户的微信。

## 接口

- `POST /jobs`：`{"share_url":"https://weixin.qq.com/sph/..."}`
- `GET /jobs/{id}`
- `GET /healthz`

## 安全配置

将服务端 API key 单独写入 `/etc/siyumenghai-video-comment-cloud.key`，权限必须是 `0600`。密钥不得进入 Git、网页、任务文件或日志。

任务与缓存仅保存在 `/var/lib/siyumenghai-video-comment-cloud`，权限 `0700`。相同分享链接默认缓存 7 天，既提升速度，也避免重复计费。每日成功上游调用默认上限 100 次，可通过环境变量下调。

## 验证

```bash
python3 -m unittest -v test_server.py
python3 server.py
curl -sS http://127.0.0.1:2033/healthz
```
