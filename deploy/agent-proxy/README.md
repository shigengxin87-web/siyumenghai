# 石董会 AI 问答代理（Dify 版）

服务器上跑的一段小程序，负责把用户的问题转给 AI，再把回答转回给小程序。
监听 `127.0.0.1:2035`，由 Nginx 把 `/api/agent/chat` 转过来。

## 这次改了什么

原来是转给腾讯云 ADP（每月至少 188 元），现在改成转给自建的 Dify，
Dify 背后接你自己买的模型 API（DeepSeek / Kimi / 智谱都可以）。

**小程序一个字都没改。** 对外输出格式和以前完全一样，所以：
- 用户手机上不需要更新版本
- 不需要重新提审
- 现有的流式打字机、复制、重试、会话记录全部照常工作

## 配置文件

`/opt/siyumenghai-agent-proxy/config.json`，改成这样：

```json
{
  "difyBaseUrl": "http://127.0.0.1:8080",
  "difyApiKey": "app-你在Dify里生成的那串"
}
```

> 端口是 **8080** 不是 80：石董会主站 Nginx 已经占了 80，Dify 走内网 8080，只监听本机（`127.0.0.1`），公网访问不到，所以不用配域名、不用 SSL。

也可以用环境变量代替，优先级更高：

```bash
export DIFY_BASE_URL=http://127.0.0.1:8080
export DIFY_API_KEY=app-xxxxx
```

> `difyApiKey` 只留服务器，不要写进小程序端。小程序能被反编译。

## 部署步骤

```bash
cd 到本目录
node --check server.js                    # 语法检查
cp server.js /opt/siyumenghai-agent-proxy/server.js
sudo systemctl restart siyumenghai-agent-proxy
sudo systemctl status siyumenghai-agent-proxy
```

Nginx 不需要动，端口和路径都没变。

## 测试

```bash
node --test dify.test.js      # 12 项，用假上游，不花钱
node --test ../miniprogram/tests/*.test.js   # 小程序侧集成测试
```

`server.adp-backup.js` 是改造前的原文件，留作回退用。
`server.test.adp-legacy.js` 是只适用于旧 ADP 协议的测试，已归档不再跑。

## 保持对外兼容的三个要点

改造最容易踩坑的地方，记下来防止以后改坏：

1. **流式必须是 NDJSON 逐行 JSON**，每行一个事件：`delta`（增量）/ `replace`（全文替换）/
   `done`（完成）/ `error`（失败）。结尾必须是 `done`，否则前端判定"回复未完成"。
2. **`X-Accel-Buffering: no` 不能去掉**，否则 Nginx 会缓冲响应，打字机效果变成一次性吐出。
3. **回答里的 Markdown 符号要清洗掉**（`#`、`**`、`` ` ``、列表符号），小程序是按纯文本展示的。

另外两个安全相关：
- 模型的**思考过程**（agent_thought）必须丢掉，不能直接透给用户
- 上游报错的原始信息不能透传，只能给通用提示

## 日常维护

- 看 Dify 后台的 token 消耗，异常暴涨说明 Key 泄露了，去吊销重建
- 提示词改完要在 Dify 里点「发布」，不发布不生效
- 每周扫一遍 Dify「日志与标注」，把答得差的问题补进知识库
