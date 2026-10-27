# 石董会 Dify 开源自建 · 部署与配置手册

## 架构（一句话）

```
小程序（已有，零改动）
   ↓  HTTPS
Nginx（已有，/api/agent/chat）
   ↓  http://127.0.0.1:2035
agent-proxy（已有，已改对接 Dify）
   ↓  http://127.0.0.1:8080（内网）
Dify 开源版（本次新建）
   ↓  你的 API Key
DeepSeek / 智谱 / Kimi（你自己买）
```

**设计原则**：Dify 只监听本机 `127.0.0.1:8080`，公网访问不到。所以不用域名、不用 SSL、不用备案，也不存在被扫描或 `/install` 被抢注的风险。所有对外暴露的只有石董会原本就在跑的 Nginx（80/443）。

---

## 一、部署 Dify（类目通过后执行，约 15 分钟）

SSH 进腾讯云服务器，执行：

```bash
cd /opt
# 把本仓库的脚本传到服务器后执行（或在服务器上 clone 本仓库取脚本）
sudo bash /path/to/setup-dify.sh
```

脚本会：克隆 Dify 开源版 → 随机化所有默认口令 → 端口锁死 127.0.0.1:8080 → 启动。

> 首次拉取十几个 Docker 镜像，耗时 5–15 分钟。脚本跑完会打印访问方式。

---

## 二、首次配置 Dify 控制台（照着点）

Dify 只监听本机，所以**用 SSH 隧道从你自己的电脑访问**：

```bash
# 你本机终端执行（不是服务器）
ssh -L 8080:127.0.0.1:8080 你的服务器用户@服务器IP
```

然后浏览器打开 `http://127.0.0.1:8080/install`，注册管理员。

之后按顺序：

1. **接模型**：右上角头像 → 设置 → 模型供应商 → 添加你买的模型
   - 对话模型：`DeepSeek`（推荐，便宜）+ 可再挂 `智谱 GLM` / `Kimi` 做备选
   - **必须再配一个 Embedding 模型**（否则知识库检索用不了）。对话模型 ≠ Embedding 模型，DeepSeek 没有 embedding。国内可用：**智谱 GLM embedding** 或 **MiniMax embedding**
2. **建知识库**：左侧「知识库」→ 创建 → 上传文档（切分规范见 `deploy/agent-proxy/KNOWLEDGE-PROMPT.md`）
3. **建应用**：左侧「工作室」→ 创建应用 → 选「聊天助手」→ 在「上下文」里关联上面建好的知识库
4. **写提示词**：在应用的「提示词」框粘贴 `KNOWLEDGE-PROMPT.md` 里的模板
5. **取 Key**：应用 → 左侧「访问 API」→ 复制 API Key（以 `app-` 开头）

> 提示词改完**必须点「发布」**，否则不生效。

---

## 三、接回石董会

> 服务器上跑的 agent-proxy 还是旧版（对接 ADP）。先把新版（对接 Dify）换上去，再改配置、重启。

**1. 更新 server.js 到服务器**

若服务器用自动发布系统（从 GitHub `main` 拉取），`git push` 后自动更新，可跳过。否则手动传：

```bash
scp deploy/agent-proxy/server.js 你的服务器用户@服务器IP:/opt/siyumenghai-agent-proxy/server.js
```

**2. 改配置**

编辑 `/opt/siyumenghai-agent-proxy/config.json`：

```json
{
  "difyBaseUrl": "http://127.0.0.1:8080",
  "difyApiKey": "app-你刚复制的那串"
}
```

**3. 重启代理**（改动才能生效）

```bash
sudo systemctl restart siyumenghai-agent-proxy
sudo systemctl status  siyumenghai-agent-proxy
```

---

## 四、真机验证

手机打开「石董会」→ 底部「AI问答」→ 问一句（建议问知识库里有的内容）。确认：
- 打字机效果正常（逐字出现，不是一次性吐出）
- 回答确实来自你的知识库（可故意问一个只有知识库里才有的细节）
- 复制 / 重试按钮可用

---

## 五、故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 一直转圈或报「服务暂时不可用」 | Dify 没启动 / API Key 错 | `docker ps` 看容器；核对 config 的 difyApiKey |
| 答非所问、像通用模型 | Embedding 没配 / 文档没入库 | 检查知识库是否已「嵌入完成」；确认应用已关联知识库 |
| 流式变成一次性出现 | Nginx 缓冲（一般已规避） | agent-proxy 已设 `X-Accel-Buffering: no`，若仍异常检查 Nginx 配置 |
| 回答里出现 `**`、`#` 等符号 | 上游未清洗（已处理） | 正常不会出现，若出现重启 agent-proxy |
| token 消耗暴涨 | Key 可能泄露 | 去 Dify 吊销旧 Key，重新生成并替换 config |

---

## 六、成本（对比 ADP 188 元/月）

| 项 | 费用 |
|---|---|
| Dify 开源版 | 0（自己服务器跑） |
| 服务器 | 已有，0 新增 |
| 模型 API（DeepSeek 等） | 按 token 计，社群日均百问约 20–50 元/月 |
| **合计** | **仅模型费，约 20–50 元/月** |

---

## 七、日常维护

- 每周扫一遍 Dify「日志与标注」，把答得差的问题补进知识库
- 新课 / 新文章发布后 24h 内入库
- 看 Dify 后台 token 消耗，异常暴涨先吊销 Key
