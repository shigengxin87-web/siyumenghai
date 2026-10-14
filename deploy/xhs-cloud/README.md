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

可选缓存配置（默认已开启，无需填写）：

```text
# SQLite 缓存位置，默认 /var/lib/siyumenghai-xhs-engine/parse_cache.db
# XHS_CACHE_DB=/var/lib/siyumenghai-xhs-engine/parse_cache.db
# 缓存有效期秒数，默认 7 天；设为 0 关闭缓存
# XHS_CACHE_TTL_SECONDS=604800
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

## 解析缓存与历史记录

引擎按 note_id 缓存解析结果（SQLite，表 `xhs_parse_records`）：短链解析出 note_id 后先查缓存，命中直接返回，不再触发 HTTP / 浏览器 / yt-dlp 三级解析，重复解析目标 <500ms；未命中才走原有回退链路并在成功后写回。缓存记录里的 web_url 每次刷新为最新 resolve 地址（xsec_token 保持新鲜），媒体地址仍由网关按请求现签 30 分钟临时票据，因此 7 天 TTL 内票据层永不过期。缓存读写全部 best-effort，DB 不可写时自动降级为实时解析，不影响线上可用性。

用户侧历史记录保存在浏览器 localStorage（最近 30 条，含封面/标题/作者/类型/时间），"再次查询"命中服务端缓存后秒回，可直接播放或保存。视频作品卡片主按钮为"保存视频"，次按钮为"预览播放"；缓存命中时卡片展示"秒开缓存"徽章。

升级时需确保 `/var/lib/siyumenghai-xhs-engine` 存在且属主为 siyumenghai-xhs（install.sh 已自动创建，systemd unit 已加 `ReadWritePaths`）。回滚时停服、换回旧 engine.py、重启即可，缓存 DB 可保留不影响旧版运行。

## 博主主页作品列表

`/parse` 自动识别输入链接：resolve 后路径为 `/user/profile/{id}` 时走博主分支，返回 `kind=author` 结构（博主昵称 + 最新最多 30 条作品的封面/标题/类型），前端渲染作品网格，用户点任意一条再走单条解析下载。HTTP 直读失败时由 `browser_author.mjs` 通过 loopback Chrome 打开博主 profile 页提取笔记列表。博主结果进程内缓存 10 分钟（`AUTHOR_TTL`），重复粘贴同一博主链接秒回。不做服务端定时轮询/推送，保持与抖音云端同款"手动拉最新"模式。
