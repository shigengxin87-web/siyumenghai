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
