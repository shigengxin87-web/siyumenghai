# 思域梦海抖音云端部署验收｜2026-10-13

结论：已正式切换为腾讯云独立解析与下载，运行链路不依赖 Mac。保留原访问码与页面。采用 DouK 参数生成模块 + curl-cffi 的轻量 Python 后端及既有 Node 下载网关，未部署完整 DTK 五容器。

线上入口：https://siyumenghai.cn/member-view/douyin-downloader.html
健康入口：https://siyumenghai.cn/api/douyin/health
源码提交：b9c9047037faf7ed123eed2e7081b791869a9276（GitHub main）
代码目录：deploy/douyin-cloud。原站点工作区保持未修改。

## 核心验收证据

1. 停止 Mac 本地网关、反向 SSH 隧道与 colima-douyin 虚拟机；禁用项目专属 gateway / tunnel / colima / ac-awake 四项 launchd 自启。Mac :2033 与云端 :22033 监听均消失。
2. 此后重启两个云端服务，清空进程缓存。公网健康从 verified=false / last_success=null 开始；随后两个真实视频及一条真实图集冷解析均 HTTP200，健康状态转为 verified=true。
3. 视频7694206162778017058：公网MP4 Range206，1024字节，完整文件长度256556160字节。视频7685216705279513690：公网MP4 Range206；完整下载15210178字节，与Content-Length相同；ffprobe确认MP4、80.92秒，ffmpeg成功解码第10秒画面。
4. 真实图集7616399587141737704：返回2张图片，公网下载分别421856、345194字节，均为image/webp。封面image/jpeg成功。
5. 云端直接向上游发起10次独立请求，覆盖3条真实作品，10/10成功；不是缓存重复请求。请求最小间隔3秒。
6. 公网作者资料HTTP200、评论5条HTTP200；同一作者连续两页各5条作品，游标推进、两页无重复；真实合集HTTP200、7条作品、has_more=false。
7. 原生Chrome网页提交真实短链接，显示“成功1/1条”及真实作品卡片、“下载无水印视频”入口。浏览器CDP连接出现超时，最终通过原生辅助功能完成网页验收。未据此宣称控制台错误为0。
8. 视频号公网真实样本https://weixin.qq.com/sph/AKlMnWudWP 返回HTTP200、code=0、有效data。视频号Nginx location与切换前备份逐字相同；未修改视频号页面与源码。
9. 原网关8项契约检查通过，新云后端6项测试通过；Node语法、Python编译、shell语法、git diff检查通过。云端engine.py / gateway.mjs SHA256与Git源码一致。

## 部署与运行

- 云端源码及运行时：/opt/siyumenghai-douyin-cloud。
- systemd：siyumenghai-douyin-engine、siyumenghai-douyin-gateway，均active/enabled，Restart=on-failure。已真实重启并重新解析。
- 后端:2036、网关:2037，只监听127.0.0.1；Nginx /api/douyin/已切换到:2037。
- 两个进程启动后合计约60MB，下载验收后约80MB；内存总上限480MB，分别限制CPU。无浏览器、数据库或Docker驻留，下载流式传输，不在云端落盘。
- 专用非登录用户、系统目录只读、禁止提权。凭据在/etc/siyumenghai-douyin，目录0750、文件0640，未进入Git或前端；原访问码保持有效。
- 解析上游403/429暂停5分钟，不自动重试；缓存最多100条、5分钟；Nginx解析限流30次/分钟，媒体流及健康检查不计入。
- 未购买或升级服务器，未停止其他生产服务。

## 保护与回滚

x-download原config/app.yaml仍保持未提交修改，未覆盖；原网站工作区干净，发布从独立副本完成。Mac原DTK数据、工程和launchd文件保留。切换前Nginx完整备份：/etc/nginx/siyumenghai-main.before-cloud-douyin-20261013。

回滚旧Mac链路前须先恢复Mac四项launchd并启动Colima，确认云端22033可达，再恢复Nginx备份、nginx -t通过后reload；不要在Mac已关闭时直接恢复旧路由。

## 实际边界

已完成“不依赖Mac、云端自启动、停止Mac服务后的真实解析和下载”验收。尚未运行满连续24小时或完成1–7天浸泡测试，因此不声称24小时零故障SLA。Cookie过期、抖音平台变更或风控仍可能造成失败，需要安全刷新凭据或维护后端。当前不提供自动Mac回退，不伪造成功数据。单文件下载保留512MB限制。

## 证据文件

- 抖音云端验收证据.json：公网冷启动、完整下载、图集与视频号回归。
- 抖音云端独立上游10次验收.json：直接上游10次请求。
- cloud-douyin-full-video.mp4：公网完整下载样本。
- 云端视频解码验收.jpg：下载样本解码画面。
- 抖音云端网页验收.png：真实网页结果卡片。
