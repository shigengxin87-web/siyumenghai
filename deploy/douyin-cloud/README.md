# 抖音轻量云端后端

2026-10-13 正式部署于已有腾讯云，沿用 `/api/douyin/*`。独立 Python 解析进程 + Node 下载代理，不使用 Mac、Docker、Redis、数据库或浏览器驻留。公网页面无需访问码，视频号路由保持原样。

- `engine.py`：使用固定 DouK 源码的参数生成模块与 curl-cffi，兼容原 DTK 数据契约；公开作品、作者、评论、分页、合集。
- `gateway.mjs`：提供公开解析入口，并保留随机下载票据、CDN 域名/DNS 校验、Range 流式代理、512MB 上限、并发上限和分页保护。健康状态实际查询云后端。
- 合集入口接受电脑端 `/collection/` 网址、手机端 `/share/mix/detail/` 分享链接、合集中的任意作品链接，以及高级用户使用的数字合集 ID；普通用户无需手工查 ID。
- 上游：[JoeanAmier/TikTokDownloader](https://github.com/JoeanAmier/TikTokDownloader)，固定 commit `473c90ff70c663cfb69310fff2b8d5192f200661`，GPL-3.0。依赖安装到 `vendor/src`，许可证一并保存。未修改上游源码。
- 已发现 x-download 当前适配器使用已移除的 `ABogus` 导出和旧参数对象，不能直接适配上述上游。此后端直接使用上游 `DouYinParams`，保留原 x-download 工作区及未提交配置。

## 运行位置

源码与独立依赖：`/opt/siyumenghai-douyin-cloud`。两个 systemd 服务使用非登录专用用户 `siyumenghai-douyin`，保护系统目录、禁止提权、限制 CPU/内存，仅监听 `127.0.0.1:2036`（内部解析）和 `:2037`（公网网关）。Nginx 仅将 `/api/douyin/` 转到 `:2037`。

凭据只在 `/etc/siyumenghai-douyin/cloud.env` 与 `cookies.yaml`，root 所有、专用组可读、0640；目录0750。Cookie 不进入 Git、日志、前端或报告。解析不自动重试，单进程上游最小间隔3秒；HTTP403/429触发5分钟暂停；缓存最多100条、5分钟。Nginx 限制解析请求30次/分钟，视频流和健康检查不占用此预算。

安装复现：在此目录以root运行 `NODE_BIN=<现有Node22+路径> ./install.sh`；先在上述私密目录安全配置随机内部 `DTK_API_KEY`、`DTK_URL=http://127.0.0.1:2036`、`PORT=2037`、`DOUYIN_COOKIE_FILE`。公网请求由Nginx限流与网关并发上限保护，内部解析接口仍必须使用 `DTK_API_KEY`。不复用原DTK管理员密钥。依赖固定在 `requirements.lock`。正式运行无需联网下载代码或依赖。

## 验收

Mac网关、SSH隧道与独立Colima虚拟机停止，4项项目专属launchd自启禁用，随后重启两个云进程清空缓存。公网冷解析真实作品、MP4 Range、完整视频下载、封面与视频号回归均有独立证据。10次直接上游请求跨3个真实作品全部成功，不计缓存成功次数。

这证明云端独立运行，不能证明永不触发平台限制或Cookie永不过期。过期时需安全刷新Cookie；不退回Mac、不伪造成功。图集与合集等详细覆盖以本次验收报告为准。健康 `verified` 表示本进程曾成功取得上游数据，不代表持续可用SLA。

## 回滚

Nginx 原配置在 `/etc/nginx/siyumenghai-main.before-cloud-douyin-20261013`，旧Mac工程和数据保留。恢复旧链路前必须先在Mac恢复这4项launchd、启动Colima，并确认云端`:22033`真实可达；再恢复Nginx备份，`nginx -t`通过后reload。否则恢复旧路由会导致服务中断。两个新服务可单独停止，不触及视频号或其他生产业务。

## 验证命令

`python -m unittest discover -s . -p test_engine.py`（需安装测试依赖httpx）；`node --check gateway.mjs`。日志不启用uvicorn access log，也不记录签名URL、Cookie或请求Authorization。
