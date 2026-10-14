# 小红书云端解析

此目录提供独立于 Mac 的小红书作品解析与下载服务。解析器和网关只监听 `127.0.0.1`，公开请求由 Nginx 转发至网关。媒体源地址通过 30 分钟临时票据隐藏。

支持作品分享链接和包含链接的分享文案，返回视频或图集、封面、作者和互动数据。主页搜索、关注、点赞、评论和发布仍由本地 `xhs-skill` 承担，不放入公开网站。

部署前创建 `/etc/siyumenghai-xhs/cloud.env`：

```text
XHS_API_KEY=随机长密钥
XHS_HOST=127.0.0.1
XHS_PORT=2038
XHS_ENGINE_URL=http://127.0.0.1:2038
XHS_GATEWAY_PORT=2039
```

可选的 `/etc/siyumenghai-xhs/cookie.txt` 仅保存一行 Cookie 请求头内容，权限必须为 `0640 root:siyumenghai-xhs`。不要提交到 Git。

Nginx HTTPS server 中加入：

```nginx
location /api/xhs/ {
    proxy_pass http://127.0.0.1:2039;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 90s;
    proxy_buffering off;
}
```

每次修改先备份配置，执行 `nginx -t`，确认通过后再 reload。
