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



## 2026-10-14 云端浏览器解析回退与验收

现有云端引擎先尝试 HTTP 页面状态读取；如网页返回空状态或跳转登录，则在同一台腾讯云服务器上通过 loopback Chrome DevTools（127.0.0.1:9223）读取目标公开笔记。Chrome 由 `siyumenghai-xhs-browser.service` 自启动与重启；不得把 DevTools 端口开放公网。只有对应目标笔记的最小必要作品字段返回给引擎，不输出整个用户浏览器状态或 Cookie。浏览器 Profile 存储在 /var/lib/siyumenghai-xhs-browser/profile。原有 Cookie 文件仍只能由受限服务用户读取。服务限流策略保持不变。

安装时包含 browser_parser.mjs、独立 Chrome systemd unit、Python 引擎及 Node 网关；升级前备份已有运行文件，停服变更后立即验证 /api/xhs/health 并使用真实分享链接测 /api/xhs/parse 与 /api/xhs/media/...。若登录状态失效或平台不允许访问，返回失败，不伪造作品。图文和视频分别使用有效样本验收。

2026-10-14 已上线验收记录：用户提供的 https://xhslink.cn/o/8363BYYnLwB 是图文笔记，不是视频，云端成功返回 6 张图片；6 张图片的在线媒体代理均通过 HTTP 206 Range 测试。iPhone 390px 视口线上粘贴解析、预览图片和界面无脚本报错测试通过。视频作品仍需要单独的有效分享链接完成完整 MP4 验收，不能将图文测试当作视频测试。
