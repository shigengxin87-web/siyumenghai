# 视频号保存到飞书

服务只监听 127.0.0.1:2033，需 Python 3 与 cryptography。与转写服务独立运行。
nginx 的 http 上下文引入 rate.conf，主站 server 上下文引入 nginx.conf。
使用附带 systemd 单元；状态目录由 systemd 创建，模式 0700。

每个浏览器持有独立随机凭证，服务器仅存其 SHA-256。Webhook 地址与校验凭证使用
Fernet 加密后写入 SQLite；密钥文件权限 0600。连接信息接口不返回这两个秘密。

飞书接收流程契约：收到 webhook 后按 source_id 查找「素材ID」，已有记录更新，
没有则新增；在写入成功后用 HTTP POST 请求 payload.callback_url，发送：

```json
{"request_id":"引用收到的 request_id","callback_token":"引用收到的 callback_token","source_id":"引用收到的 source_id","status":"saved","record_id":"引用写入成功的记录 ID"}
```

回执 ID 若为单元素数组也支持。所有字段须用飞书变量引用，不能把示例文字写死。
不要转发正文到其他地址，不要增加消息通知节点。接收流程应开启 Bearer 凭证校验。

同一浏览器、目标接收流程、视频链接与内容的连续保存复用确认结果；未确认的请求
阻止新版本抢先写入。普通重复点击不重复发送；60 秒后可手动重试同一 request_id，
接收流程必须仍按 source_id 查找后更新。Webhook HTTP 200 不等于写入确认。
回执是确认来源，服务器不轮询用户表格，不持有其飞书账号授权。

首版不提供双向同步、视频附件或跨设备连接同步。服务器只保存连接密文、内容摘要和
投递/回执状态，不持久化逐字稿全文。勿公开状态目录、密钥或接收地址。
