# 视频文案保存飞书

独立服务绑定 `127.0.0.1:2033`，由本站 `/api/feishu-sync/` 反代。直接调用飞书 API，不依赖付费自动化。

每位使用者提供专用企业自建应用 App ID、App Secret 和含 `table=tbl…` 的 Feishu `/base/` 链接。应用发布后，需要作为文档应用加入目标 Base。最小应用身份权限：`base:field:read`、`base:record:retrieve`、`base:record:read`、`base:record:create`、`base:record:update`。

目标数据表包含六个文本字段：标题、作者、原视频链接、逐字稿、素材ID、更新时间。配置阶段验证凭证、字段和查询权限，首次保存验证写入权限。

浏览器随机生成 256-bit 连接凭证，服务端仅存其 SHA-256。应用密钥用独立 Fernet key 加密，绝不返回浏览器。状态目录和 key 分别 0700/0600。SQLite 仅持久化连接、来源哈希、内容哈希和任务状态，不保存逐字稿正文。正文仅在用户点击保存后通过固定 `open.feishu.cn` 官方 API 发送。禁重定向，避免密钥泄漏或 SSRF。

按目标表和视频来源哈希检索已有记录，新增或更新后重新读取记录核对全部字段。确认完成才返回 confirmed 和记录链接。相同表写入串行执行；重复素材ID拒绝写入。新增使用 UUIDv4 client_token，网络中断保留同一任务供手动重试，先查询再写入，避免重复创建。不确定状态不自动反复写入。服务重启将 sending 转为 awaiting。待确认旧版本必须核对完成后再保存新版本。

接口：GET healthz/connection/deliveries/:id；POST connection/save。除 healthz 外都需要 Authorization Bearer 浏览器连接凭证。服务不依赖 CLI 用户登录态。

Python 3 + `cryptography`。部署 `server.py` 和 systemd 单元，加载 nginx snippet 与限流区后执行 nginx -t 并 reload；修改前保留备份。状态目录由 systemd StateDirectory 创建。发布前完成模拟服务故障测试、浏览器交互测试和专用私有 Base 的实际新增/更新/读回测试。
