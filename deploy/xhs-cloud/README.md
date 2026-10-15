# 小红书云端作品收集

独立云端服务，不依赖 Mac。Python 解析器和 Node 媒体网关只监听 loopback，Nginx 提供 HTTPS 入口。不得公开 DevTools、Cookie 或 API 密钥。

## 2026-10-15 v2

- 解析队列与媒体队列独立；同作品/同媒体的并发请求合并。
- 云端浏览器按目标作品状态轮询，无固定 5 秒等待；失败后再尝试 HTTP 页面。`XHS_PARSE_PRIMARY=http` 可切回 HTTP 优先；默认不再使用与页面同源的 yt-dlp 兜底，显式 `XHS_YTDLP_FALLBACK=1` 才启用。
- 选视频时优先带音轨、兼容的 AVC 版本，避免最高码率的视频只有画面没有声音。
- 元数据默认缓存 6 小时；旧缓存结构自动失效。`POST /api/xhs/parse` 支持 `refresh:true`。
- 媒体使用持久化资源记录，7 天有效；服务重启不会让已发放资源立即失效。上游媒体不可用时重新解析刷新。
- 原文件按需缓存到磁盘；同一资源不会重复拉取。缩略图由 Pillow 生成，前端首屏只展示封面和最多 4 张缩略图。
- 视频预览优先由平台媒体节点直接交付，失败自动切换同源 Range 转发。64MiB 以内的视频下载在浏览器支持时直接读取媒体节点，显示字节进度，12 秒内未完成则回退本站文件下载；避免本站出口成为小视频下载瓶颈。完整文件仍保留到缓存，备用下载支持本地 Range。
- 图集打包 ZIP；单图、视频可单独下载。准备任务有逐文件/字节进度，失败可重试，已完成任务可跨网关重启恢复。
- 前端支持两条并行解析、作品信息/CSV 导出、旧历史记录迁移、图集键盘浏览、手机布局。

## 安装

创建 `/etc/siyumenghai-xhs/cloud.env`（不提交到 Git）：

```text
XHS_API_KEY=随机长密钥
XHS_HOST=127.0.0.1
XHS_PORT=2038
XHS_ENGINE_URL=http://127.0.0.1:2038
XHS_GATEWAY_PORT=2039
```

可选环境变量：

```text
XHS_CACHE_TTL_SECONDS=21600
XHS_MEDIA_CACHE_DIR=/var/lib/siyumenghai-xhs-media
XHS_MEDIA_CACHE_BYTES=1610612736
```

Cookie 单独放 `/etc/siyumenghai-xhs/cookie.txt`，权限 `0640 root:siyumenghai-xhs`。需 Google Chrome 及 Node >=22。运行 `install.sh`，升级后需重启 engine/gateway，已存在的 service 不会因 `enable --now` 自动重新加载新代码。

媒体目录须由服务用户写入，网关 unit 的 `ReadWritePaths` 与自定义目录保持一致。默认缓存预算约 1.5GiB，每 10 分钟及准备任务完成后清理，原文件与缓存保留最多 7 天；单文件、单个 ZIP 上限 512MiB。并发传输可能有暂时超额，需监控磁盘空间。待处理任务有界，当前处理中的任务在重启时可重新提交，已完成任务文件默认可下载 24 小时。

## Nginx

媒体、下载文件与 GET 任务状态不能计入提交解析的速率限制。生产配置需同时更新 map 与 location：

```nginx
map $uri $xhs_cloud_limit_key {
    default $binary_remote_addr;
    ~^/api/xhs/media/ "";
    ~^/api/xhs/jobs/ "";
    ~^/api/xhs/files/ "";
    /api/xhs/health "";
}
limit_req_zone $xhs_cloud_limit_key zone=xhs_cloud_api:1m rate=60r/m;
location ^~ /api/xhs/ {
    limit_req zone=xhs_cloud_api burst=24 nodelay;
    limit_req_status 429;
    client_max_body_size 16k;
    proxy_pass http://127.0.0.1:2039;
    proxy_http_version 1.1;
    proxy_read_timeout 90s;
    proxy_buffering off;
    # Cache-Control 由网关设置，勿统一覆盖为 no-store。
}
```

配置更新前备份，`nginx -t` 通过后 reload；不改其他平台路由。

## 接口

- `POST /api/xhs/parse`：`{url, refresh?}`，返回真实作品或博主列表、同源媒体地址、耗时。
- `GET /api/xhs/media/{id}?thumb=1`：小尺寸预览；不带 thumb 返回原文件；支持 Range。
- `POST /api/xhs/jobs`：`{media:["/api/xhs/media/..."]}`，返回准备任务。多文件仅允许同作品图片。
- `GET /api/xhs/jobs/{id}`：`preparing/ready/failed`，包含 done/total、当前文件 bytes、download。
- `GET /api/xhs/files/{id}`：准备完成的原文件或 ZIP，attachment、支持 Range。

移动端文件分享仅在浏览器支持时提供，文件读取后再次点击由用户唤起系统分享。不承诺任何浏览器都能直接写入手机相册。

## 验证

```sh
XHS_API_KEY=test-key uv run --with httpx==0.28.1 --with lxml==6.1.1 --with yt-dlp==2026.8.19 python -m unittest discover -s deploy/xhs-cloud -p test_engine.py
XHS_API_KEY=test-key XHS_MEDIA_CACHE_DIR=/tmp/xhs-unit-media node --test deploy/xhs-cloud/test_gateway.mjs
node --test deploy/xhs-cloud/test_media.mjs
```

自动化回归覆盖队列不丢请求、同文件去重、持久化资源、13 图同时请求、Range、ZIP CRC 和逐文件内容、下载任务。上线仍需真实作品、完整带声音视频、图集实际下载、播放/拖动、手机宽度与公网内容 hash 验收。少量样本不等于长期平台可用性保证。

## 2026-10-15 原画视频与独立音轨

对平台提供的自适应画面与 AAC 音轨，优先选清晰度最高的画面及匹配音轨。已用真实作品验证此来源不带 WEB_259 版本的“小红书＋作者”角标。匹配时长差须在 2 秒以内；缺少或不匹配音轨时保留原有完整视频路径，不输出静音文件。

网关使用 FFmpeg `-c copy` 合并画面和声音，保持源画质；HEVC 标记 `hvc1`，MP4 faststart 便于播放。不使用画面涂抹或 AI 修补，也不移除作者原片内嵌内容。不能据此承诺所有作品原始画面都没有作者自己的水印。

合并有独立的单任务队列、超时、文件大小上限，复用已下载输入和最终文件。缓存身份同时包含画面与音轨，视频元数据结构升级，旧的带角标来源不会继续作为新解析结果。合并资源不提供裸画面的 direct 下载或重定向，避免下载再次丢声音；使用同源缓存文件，完整传输受本站带宽影响，不能套用此前单文件 CDN 直接下载的 1—2 秒成绩。

安装需系统 FFmpeg（可用 `XHS_FFMPEG_BIN` 指定路径）。合并失败明确报错、允许重试，不静默回退为带角标版本。资源接口和原生小程序的 `proxy=1` 保存契约保持兼容。
