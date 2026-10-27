# 石董会 AI 问答：ADP → Dify 迁移包

> 目标：把原腾讯云 ADP 上的「运营实战顾问」智能体，完整搬迁到你自己服务器上的开源 Dify，
> 知识库 = 本地这 128 个脱敏案例，提示词/约束/欢迎语沿用原 ADP 配置（已导出，见本目录）。
> 小程序端零改动、零重新提审——只换后端供货商。

---

## 本目录包含什么

| 文件 | 用途 |
|---|---|
| `cases/` | **128 个案例的干净备份**（源：`DoubaoWork/.../_agent_kb/articles`），上传 Dify 用这个 |
| `kb_metadata.csv` | 128 案例的元数据（case_id / platform / topic / title），用于 Dify 知识库打标签、方便过滤检索 |
| `build_metadata.py` | 从文件名重新解析元数据的脚本（源目录变了可重跑） |
| `SYSTEM_PROMPT.md` | **直接粘贴进 Dify「提示词」框**的系统提示词（含 `{{#context#}}` 占位符） |
| `WELCOME_EXAMPLES.md` | 欢迎语 + 5 条示例问题，分别粘贴进 Dify 对应配置 |
| `README.md` | 本文件：从安装到上线的完整 runbook |

> 原 ADP 的两份源提示词（系统提示词完整版、平台版）也在本地：
> `DoubaoWork/chats/2026-09-17/new-chat/运营研究社128案例知识库_系统提示词.md`
> `DoubaoWork/chats/2026-09-17/new-chat/平台版提示词_运营实战顾问.md`
> 本包的 `SYSTEM_PROMPT.md` 已据此改写为 Dify 格式，约束一字未改。

---

## 前置条件（一次性的）

1. 你的腾讯云服务器上已用 `../setup-dify.sh` 装好 Dify（端口锁 `127.0.0.1:8080`）。
2. 服务器上 `agent-proxy` 已改好对接 Dify（提交 `db51d52` + 格式修复 `883ad4e` 已包含）。
3. 你已购买好模型 API Key：一个**对话模型**（DeepSeek / 智谱 / Kimi 任选）+ 一个 **Embedding 模型**（知识库检索必需，智谱或 Minimax 都行）。

> 若 Dify 还没装，先跑 `cd deploy/dify && sudo bash setup-dify.sh`，等 5–15 分钟拉完镜像。

---

## 迁移步骤（按顺序）

### 第 1 步：进 Dify 控制台

Dify 只监听本机 8080，公网看不到。在**你本机**建一条 SSH 隧道：

```bash
ssh -N -L 8080:127.0.0.1:8080 你的服务器用户@服务器IP
```

然后浏览器开 `http://127.0.0.1:8080` → 第一次会跳 `/install` 注册管理员（**慢了会被别人抢注**，装完立刻注册）。
之后每次从 `http://127.0.0.1:8080` 登录。

### 第 2 步：接模型

左上角头像 → **设置 → 模型供应商**：
- 添加对话模型（如 DeepSeek，填 API Key）
- 添加 Embedding 模型（如智谱 `embedding-3`，**知识库必需**，否则建库时报错）

### 第 3 步：建知识库并上传 128 案例

1. 顶部 **知识库 → 创建知识库 → 导入已有文本**。
2. 把本目录 `cases/` 里的 128 个 `.md` 全部拖进去（macOS 可直接从 Finder 拖入浏览器上传窗口）。
3. 分段设置：**每个文档作为一个分段**（案例本身 1–5 万字，按文档切分最稳），检索方式选「语义检索」或「混合检索」。
4. 索引完成后，**批量打元数据**（用 `kb_metadata.csv` 的 case_id / platform / topic）：
   - 在知识库「元数据」里先建字段：`case_id`(文本)、`platform`(文本)、`topic`(文本)。
   - 点「批量编辑元数据」，按 CSV 把每个文档的 case_id / platform / topic 填进去（platform 用于按平台过滤检索，top_k 建议 5–8）。

> 上传后建议先搜几个关键词（如"私域 复购""小红书 起号"）看召回质量，确认案例能被正确检索到。

### 第 4 步：建聊天助手并粘贴提示词

1. 工作室 → **创建应用 → 聊天助手**，命名「运营实战顾问」。
2. 提示词编辑框：**整段复制 `SYSTEM_PROMPT.md` 的内容粘贴进去**（保留 `{{#context#}}`）。
3. 下方「上下文」→ 添加第 3 步建好的知识库。
4. 模型选第 2 步接的对话模型；温度建议 0.3–0.5（太低死板、太高易编造）。
5. 开场白 / 示例问题：复制 `WELCOME_EXAMPLES.md` 的内容填进对应框。
6. **右上角「发布」**（Dify 改了提示词不点发布不生效——这是最常见的坑）。

### 第 5 步：拿 API Key

应用内 → **访问 API → API 密钥 → 生成密钥**，复制那串 `app-xxxx`。

### 第 6 步：接回石董会（服务器上操作）

编辑 `/opt/siyumenghai-agent-proxy/config.json`：

```json
{
  "difyBaseUrl": "http://127.0.0.1:8080",
  "difyApiKey": "app-你刚复制的那串"
}
```

重启代理（改动才生效）：

```bash
sudo systemctl restart siyumenghai-agent-proxy
sudo systemctl status  siyumenghai-agent-proxy   # 确认 active (running)
```

> Nginx 不用动，路径 `/api/agent/chat` 和端口都没变。

### 第 7 步：真机验证

手机打开石董会 → AI 问答 tab → 问一句（如"小红书本地口腔诊所怎么获客？"）。
预期：从 Dify 知识库召回案例、带 `（案例#XXX）` 引用、格式干净（之前的换行/MD 符号问题已修）。

---

## 回滚方案（Dify 出问题时）

`agent-proxy` 保留了 ADP 原版 `server.adp-backup.js`。若需退回 ADP：
1. 把 `server.js` 换回 `server.adp-backup.js` 内容；
2. `config.json` 改回 ADP 的配置；
3. `sudo systemctl restart siyumenghai-agent-proxy`。

---

## 常见坑

- **Dify 不发布 = 改了白改**：每次改提示词/知识库后必须点「发布」。
- **Embedding 模型漏接 = 知识库建不了**：第 2 步务必先加 Embedding 模型。
- **`/install` 被抢注**：装完 Dify 第一件事就是注册管理员，别拖。
- **SSH 隧道断了 = 控制台打不开**：隧道窗口别关，重连即可。
- **小程序没反应**：先 `curl http://127.0.0.1:2035/health` 看代理活着没，再看 config 的 Key 对不对。
