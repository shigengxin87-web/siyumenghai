# 石董会 AI 问答 —— 自研轻量 RAG 服务（方案 D）

替代 Dify/ADP 的零成本后端。对外暴露 **Dify 兼容的 `/v1/chat-messages` 接口**，
复用已改造好的 agent-proxy（Dify 版），小程序前端零改动。

## 为什么是它
- **零外部向量库依赖**：jieba 中文分词 + 本地 BM25 召回 128 个实战案例，不依赖任何 Embedding 付费服务、不依赖插件市场。
- **只付模型费**：对话走 DeepSeek（api.deepseek.com），每月几块到几十块，无平台费。
- **轻量**：纯 Python，内存占用百 MB 级，4G 服务器毫无压力。
- **与 Dify 协议一致**：agent-proxy 无需改动，前端无需改动。

## 组成
- `app.py`：FastAPI 服务，BM25 召回 + DeepSeek 流式，输出 Dify 风格 SSE。
- `cases/` + `kb_metadata.csv` + `SYSTEM_PROMPT.md`：知识库与提示词（来自迁移包）。
- `siyumenghai-rag-lite.service`：systemd 单元，监听 `127.0.0.1:8080`。

## 部署（在服务器）
```bash
# 1. 建目录并放入代码/知识库
sudo mkdir -p /opt/siyumenghai-rag-lite
sudo cp -r app.py cases kb_metadata.csv SYSTEM_PROMPT.md /opt/siyumenghai-rag-lite/
sudo cp siyumenghai-rag-lite.service /etc/systemd/system/

# 2. 安装依赖
sudo pip3 install -r requirements.txt   # 或 python3 -m pip install ...

# 3. 写 env（含 DeepSeek Key 与服务 token），权限 600
sudo cp env.example /opt/siyumenghai-rag-lite/env
sudo vi /opt/siyumenghai-rag-lite/env    # 填入真实 DEEPSEEK_API_KEY
sudo chmod 600 /opt/siyumenghai-rag-lite/env

# 4. 启动
sudo systemctl daemon-reload
sudo systemctl enable --now siyumenghai-rag-lite

# 5. 健康检查
curl -s http://127.0.0.1:8080/health
```

## 切换 agent-proxy 到本服务（前端零改）
agent-proxy 已是 Dify 版，只需把 `config.json` 的 `upstream`/`difyBaseUrl` 指向本服务：
```json
{
  "difyBaseUrl": "http://127.0.0.1:8080",
  "difyApiKey": "sdh-rag-lite-2026"
}
```
```bash
sudo systemctl restart siyumenghai-agent-proxy
```

## 回滚到 ADP
保留原 ADP `config.json` 备份（`config.json.bak-adp`），还原后重启 agent-proxy 即可。
本服务独立于 ADP 运行，回滚不影响任何其它生产服务。

## 验证
```bash
curl -N -X POST http://127.0.0.1:8080/v1/chat-messages \
  -H "Authorization: Bearer sdh-rag-lite-2026" \
  -H "Content-Type: application/json" \
  -d '{"query":"小红书怎么做引流","response_mode":"streaming","conversation_id":"test1","user":"u1"}'
```
应看到 `event:message` 增量流与结尾 `event:message_end`。

---

## 管理后台（自研，替代 Dify/Coze 控制台）

访问：`https://siyumenghai.cn/ai-admin/`（密码登录，独立部署，无平台费）

| 能力 | 说明 |
|---|---|
| 概览 | 文档数 / 切片数 / 模型 / 服务状态 |
| 知识库 | 列表、上传（md/txt/pdf/docx 自动转文本）、在线编辑、删除 |
| 提示词 / 人设 | 在线编辑 `SYSTEM_PROMPT.md`，保存即热更新 |
| 测试问答 | 页内直接提问，验证改动效果 |
| 模型设置 | 模型名 / 温度 / 最大长度 / 召回条数（保存后重启生效） |
| 运行日志 | 最近 150 行服务日志 |

### 架构
- `admin.py`：FastAPI 管理台，监听 `127.0.0.1:8090`，由 systemd 托管
- `siyumenghai-rag-admin.service`：管理台服务单元
- nginx `location /ai-admin/` 反代到 8090，走 HTTPS
- 热更新：管理台写文件后调用 rag-lite 的 `POST /internal/reload`（无需重启进程）

### 部署
```bash
sudo bash deploy_admin.sh          # 装依赖 + 写配置 + 起服务
sudo python3 patch_nginx_admin.py  # 挂 /ai-admin/（幂等）
sudo nginx -t && sudo systemctl reload nginx
```

### 安全
- 管理台只监听 127.0.0.1，公网仅经 nginx HTTPS 暴露
- 密码登录（`ADMIN_PASSWORD` 存于 `/opt/siyumenghai-rag-lite/env`，600 权限）
- 会话 Cookie `HttpOnly + SameSite=Lax`，HTTPS 下自动 `Secure`
- 文件操作限制在 `cases/` 目录内，防目录穿越
