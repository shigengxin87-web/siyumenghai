# 公众号文章监控工作流教程：可复刻执行版

> 这份教程记录的是一套已经跑通的本地自动化工作流：自动监控指定公众号，发现更新后推送到飞书提醒群，同时把文章信息写入飞书多维表格，并把文章原文沉淀到 Obsidian。
> 
> 这不是一个纯云端插件，也不是让 AI 临时去网页搜索。它更像一个本地内容雷达：用 WeRSS 稳定获取公众号文章，用本地脚本去重和分发，用飞书负责提醒和表格化管理，用 Obsidian 负责长期沉淀。

## 最短理解

数据流是：

```text
公众号文章
  -> WeRSS
  -> 本地监控脚本
  -> 飞书群提醒
  -> 飞书多维表格
  -> Obsidian Markdown 文件
```

一次运行会做这些事：

1. 刷新 WeRSS 中指定公众号的文章。
2. 读取公众号对应的 Atom feed 或 WeRSS SQLite 数据库。
3. 用本地 SQLite 数据库判断哪些文章是新文章。
4. 为新文章生成一个简短的核心思想摘要。
5. 用飞书群机器人 Webhook 发提醒。进阶用户也可以改成飞书自建应用私信。
6. 把文章信息写入对应的飞书多维表格。
7. 把文章正文或文章元数据写入 Obsidian。
8. 记录日志，失败时发异常提醒。
9. 如果 WeRSS 授权过期，要主动发飞书提醒重新扫码。

建议频率：每 6 小时运行一次。这样能降低微信侧限制、登录态失效和无意义请求的风险。

## 直接丢给 Codex / WorkBuddy 的提示词

把下面这段完整复制给你的本地 Agent。把中括号里的内容换成自己的信息。

```text
我想在本机搭建一个公众号文章监控工作流。

目标：
1. 监控这些微信公众号：[公众号名称 1]、[公众号名称 2]、[公众号名称 3]
2. 每 6 小时自动检查一次是否有新文章
3. 有新文章时，发到我的飞书提醒群
4. 把新文章写入飞书多维表格
5. 把文章保存到我的 Obsidian 仓库
6. 失败时不要静默失败，要写日志并发飞书异常提醒

我的环境信息：
- 操作系统：[macOS / Linux / Windows]
- Obsidian vault 路径：[例如 /Users/xxx/Documents/ObsidianVault]
- 飞书多维表格链接：[填你的多维表格链接]
- 飞书群机器人 Webhook 地址：[填 Webhook 地址；小白优先用这个]
- 飞书自建应用 app_id：[如果要写入多维表格，填 app_id]
- 飞书自建应用 app_secret：[如果要写入多维表格，填 app_secret]
- 希望每个公众号一个 table：[是 / 否]

请你直接在本机实现，不要只给我建议。

执行要求：
1. 先检查本机是否已有 WeRSS、Python、Node、Docker、飞书 CLI 或相关工具，优先复用已有工具。
2. 安装或启动 WeRSS，并指导我完成微信扫码登录。
3. 在 WeRSS 里添加指定公众号，拿到每个公众号的 MP_WXS_xxx ID。
4. 创建或检查飞书多维表格字段。
5. 写一个本地配置文件，不要把密钥写进公开仓库。
6. 写或复用一个监控脚本，实现：
   - 获取公众号最新文章
   - 本地 SQLite 去重
   - 飞书群机器人提醒
   - 飞书多维表格写入
   - Obsidian Markdown 写入
   - WeRSS 授权过期提醒
   - 错误日志和异常提醒
7. 先手动运行一次，确认没有报错。
8. 再配置后台定时任务，每 6 小时运行一次。
9. 最后给我一份验收报告，包括：
   - WeRSS 是否可访问
   - 已监控的公众号和 MP_WXS ID
   - 飞书是否收到测试提醒
   - 多维表格是否新增测试记录
   - Obsidian 是否生成 Markdown 文件
   - 定时任务是否已启用
   - 日志文件路径

注意：
- 不要把 app_secret、token、cookie、Webhook 地址、open_id 等敏感信息输出到公开文档。
- 如果某个公众号无法被 WeRSS 添加，请明确告诉我失败原因，并给出替代方案。
- 不要承诺 100% 稳定抓取。这个方案依赖 WeRSS 和微信登录态。
```

## 人需要提前准备什么

在把任务交给 Agent 之前，最好先准备这些信息。

### 1. 公众号名单

准备你想监控的公众号名称，建议先从 1-3 个开始。

示例：

```text
润宇创业笔记
梁粉几碗
大圣AI超级个体
```

注意：这里要用公众号准确名称。名字不准确会影响 WeRSS 添加和后续匹配。

### 2. 飞书多维表格

建议每个公众号一个 table。这样后面 review、筛选、归档会更清楚。

每个 table 建议包含这些字段：

| 字段名 | 类型 | 用途 |
|-|-|-|
| 记录 | 文本 | 主字段，通常写文章标题 |
| 账号名 | 文本 | 公众号名称 |
| 更新日期时间 | 日期时间 | 文章发布时间或抓取时间 |
| 更新的内容标题 | 文本 | 文章标题 |
| 核心思想 | 文本 | 自动生成的简短摘要 |
| 链接 | URL / 超链接 | 原文链接 |
| 状态 | 单选 | 例如：待审核、已读、已拆解 |
| 来源 | 单选 / 文本 | 例如：公众号 |

如果你不想每个公众号一个 table，也可以用一个总表，然后用 `账号名` 字段筛选。但可维护性会差一点。

### 3. 飞书提醒方式

小白优先用飞书群机器人 Webhook，不要一上来折腾 `open_id`。

操作步骤：

1. 在飞书里新建一个群，例如「公众号监控提醒」。
2. 点击群右上角设置。
3. 找到「群机器人」或「机器人」。
4. 添加「自定义机器人」。
5. 复制机器人 Webhook 地址。
6. 把这个地址交给 Codex / WorkBuddy。

你需要准备：

```text
飞书群机器人 Webhook 地址
```

这个方案的好处是：不需要查 `open_id`，不需要先搞懂飞书用户 ID，也不用确认应用能不能给个人发私信。

### 4. 飞书自建应用

如果只做群提醒，飞书自定义机器人就够了。

如果还要写入飞书多维表格，就需要飞书自建应用。它主要用来写表格，不建议让小白一开始用它做个人私信提醒。

至少需要准备：

```text
app_id
app_secret
多维表格 app_token
每个 table 的 table_id
```

常见权限包括：

- 多维表格记录读写权限。
- 如果你坚持用自建应用发个人私信，才需要额外准备接收人的 `open_id` 或群聊 `chat_id`，并确认应用有发送消息权限。

不同飞书租户的后台界面可能略有不同，具体权限名称以飞书开放平台当前显示为准。

### 5. Obsidian 仓库路径

准备本地 Obsidian vault 的绝对路径。

示例：

```text
/Users/xxx/Documents/ObsidianVault
```

建议写入目录：

```text
30-素材/公众号文章/公众号监控/
```

最终结构建议是：

```text
30-素材/公众号文章/公众号监控/
├── 公众号监控｜总索引.md
├── 公众号A/
│   ├── 公众号A｜原文索引.md
│   ├── 2026-07-01 文章标题.md
│   └── ...
├── 公众号B/
│   ├── 公众号B｜原文索引.md
│   └── ...
└── 公众号C/
    ├── 公众号C｜原文索引.md
    └── ...
```

## 推荐技术架构

这套方案建议拆成 5 层。

| 模块 | 作用 |
|-|-|
| WeRSS | 登录微信环境，订阅公众号，生成 feed 或本地文章库 |
| 本地监控脚本 | 定时检查新文章、去重、生成摘要、分发 |
| SQLite | 保存已处理文章，避免重复提醒 |
| 飞书 | 群提醒 + 多维表格沉淀 |
| Obsidian | 本地 Markdown 长期保存 |

最关键的原则：不要让 AI 每次临时搜网页。监控任务要有稳定数据源、状态数据库、日志和失败提醒。

## Agent 实施步骤

下面这部分是给 Codex / WorkBuddy 执行用的。

### 第一步：检查本机环境

Agent 先检查这些命令是否存在：

```bash
python3 --version
node --version
docker --version
curl --version
sqlite3 --version
```

如果在 macOS 上，还要检查：

```bash
launchctl print gui/$(id -u) >/dev/null
```

如果用户已经安装过 WeRSS 或已有监控项目，优先复用，不要重复安装。

### 第二步：安装或启动 WeRSS

如果本机没有 WeRSS，最短路径可以用 Docker：

```bash
mkdir -p ~/.local/share/we-mp-rss/data

docker run -d \
  --name we-mp-rss \
  -p 8001:8001 \
  -v ~/.local/share/we-mp-rss/data:/app/data \
  ghcr.io/rachelos/we-mp-rss:latest
```

然后打开：

```text
http://127.0.0.1:8001
```

完成初始化和微信扫码登录。

如果不用 Docker，也可以按 WeRSS 项目自己的 Python 方式部署。关键不是部署方式，而是要拿到：

```text
本地访问地址：http://127.0.0.1:8001
本地数据库路径：例如 ~/.local/share/we-mp-rss/data/db.db
公众号 ID：MP_WXS_xxx
```

### 第三步：添加公众号并获取 MP ID

在 WeRSS 后台添加需要监控的公众号。

添加成功后，为每个公众号记录：

```text
公众号名称
MP_WXS_xxx
feed URL
```

feed URL 通常类似：

```text
http://127.0.0.1:8001/feed/MP_WXS_xxxxxxxxxx.atom
```

如果某个公众号无法添加，要停下来说明原因。不要用模糊搜索结果假装成功。

### 第四步：创建配置文件

建议把配置放在用户本地私有目录，不要放进公开仓库。

示例路径：

```text
~/.local/share/wechat-monitor/config.json
```

配置模板：

```json
{
  "poll_interval_seconds": 21600,
  "notify_existing_on_first_run": false,
  "failure_notice_cooldown_seconds": 1800,
  "database_path": "/ABSOLUTE/PATH/wechat_article_monitor.db",
  "log_path": "/ABSOLUTE/PATH/wechat_article_monitor.log",
  "sources": [
    {
      "account_name": "公众号名称",
      "feed_url": "http://127.0.0.1:8001/feed/MP_WXS_xxx.atom",
      "werss_mp_id": "MP_WXS_xxx",
      "werss_db_path": "/ABSOLUTE/PATH/we-mp-rss/data/db.db",
      "bitable_table_id": "tblxxxx",
      "bitable_primary_title_field": "记录",
      "backfill_limit": 10,
      "exact_account_match": true
    }
  ],
  "feishu": {
    "delivery_method": "webhook",
    "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx",
    "webhook_secret": "",
    "bitable": {
      "enabled": true,
      "app_id": "cli_xxx",
      "app_secret": "YOUR_APP_SECRET",
      "app_token": "bascn_xxx",
      "table_id": "tblxxxx",
      "field_map": {
        "account": "账号名",
        "published_at": "更新日期时间",
        "title": "更新的内容标题",
        "core_idea": "核心思想",
        "link": "链接",
        "status": "状态",
        "source": "来源"
      },
      "status_value": "待审核",
      "source_value": "公众号"
    }
  },
  "summary": {
    "mode": "heuristic",
    "max_chars": 120
  },
  "obsidian": {
    "enabled": true,
    "vault_path": "/ABSOLUTE/PATH/ObsidianVault",
    "folder": "30-素材/公众号文章/公众号监控"
  }
}
```

说明：

- `feed_url` 用来读最新文章列表。
- `werss_db_path` + `werss_mp_id` 可用于导出完整正文 HTML。
- `database_path` 是监控脚本自己的去重数据库。
- `notify_existing_on_first_run` 建议保持 `false`，第一次运行只建档，不把历史文章全推送出来。
- `backfill_limit` 控制每次最多读取多少篇，建议 10-20。

### 第五步：实现监控脚本

脚本至少要实现这些函数：

| 能力 | 要求 |
|-|-|
| 读取来源 | 优先读稳定 feed；必要时读 WeRSS SQLite |
| 去重 | 用本地 SQLite，按公众号 + guid / link / 标题时间去重 |
| 摘要 | 没有大模型也可以先用文章 description 截断生成 |
| 飞书提醒 | 新文章和异常都要提醒 |
| 多维表格写入 | 字段名要和配置映射一致 |
| Obsidian 写入 | 每个公众号单独文件夹 |
| WeRSS 授权监控 | 刷新后检查 `Invalid Session`、`授权过期`、`登录已经失效` 等日志 |
| 日志 | 写入本地 log 文件 |

文章提醒格式建议：

```text
公众号更新提醒
账号名：xxx
更新时间：2026-07-01 10:00:00
标题：xxx
核心思想：xxx
链接：xxx
```

异常提醒格式建议：

```text
公众号监控异常
问题：xxx 抓取失败
详情：xxx
时间：2026-07-01 10:00:00
```

WeRSS 授权过期提醒建议单独处理。因为 WeRSS 刷新接口有时会返回成功，但后台线程实际报 `Invalid Session`，如果只看 HTTP 状态码会误判为正常。

提醒格式建议：

```text
公众号监控异常
问题：WeRSS 微信授权已过期
详情：依赖 WeRSS 的公众号无法刷新新文章，请重新扫码授权。
影响：所有 WeRSS 来源公众号可能停止更新；本地微信卡片来源不受影响。
处理：打开 http://127.0.0.1:8001 后进入微信授权/扫码登录。
时间：2026-07-01 10:00:00
```

实现要点：

- 每次刷新 WeRSS 前，记录 `werss.out.log` 和 `werss.err.log` 的当前文件大小。
- 刷新后只扫描本次新增日志，不要扫全量旧日志。
- 匹配这些关键词：`Invalid Session`、`授权过期`、`登录已经失效`、`账号过期`、`请重新扫码登录`。
- 命中后通过现有飞书提醒通道发异常提醒。
- 加一个冷却文件，例如 `werss-auth-expired.last_notice`，30 分钟内不要重复刷屏。
- 这条提醒只说明数据源授权失效，不代表监控脚本本身坏了。

### 第六步：Obsidian 写入策略

有两种写法，建议明确区分。

第一种：监控脚本直接写文章卡片。

适合先跑通，内容包括：

- 公众号名称
- 文章标题
- 发布时间
- 原文链接
- 核心思想
- 摘要

第二种：从 WeRSS SQLite 导出完整正文 HTML。

适合需要完整原文沉淀，内容包括：

- 正文 HTML
- 原始 HTML 折叠块
- 原文链接
- 公众号信息
- 单号索引
- 总索引

如果教程或交付目标写了“保存完整正文”，Agent 必须实现第二种，不能只保存链接和摘要。

### 第七步：手动测试一次

先不要直接开后台定时。先手动运行：

```bash
python3 /PATH/TO/monitor.py --config ~/.local/share/wechat-monitor/config.json --once
```

检查日志：

```bash
tail -n 100 /ABSOLUTE/PATH/wechat_article_monitor.log
```

预期看到类似：

```text
公众号名称 checked via feed:http://127.0.0.1:8001/feed/MP_WXS_xxx.atom, 0 new rows
```

如果第一次运行是 `0 new rows` 不一定代表失败。因为第一次通常是建立去重基线，不推送历史文章。

### 第八步：验证飞书写入

Agent 需要确认：

- 飞书提醒群能收到测试消息。
- 多维表格能新增一条测试记录。
- 链接字段是可点击的。
- 日期字段格式正确。
- 如果每个公众号一个 table，要确认每个公众号写入自己的 `table_id`。

常见问题：

| 问题 | 可能原因 |
|-|-|
| 收不到飞书消息 | Webhook 地址错、自定义机器人被移除、机器人安全设置不匹配 |
| 多维表格写入失败 | app_token 错、table_id 错、字段名不一致、应用没有表格权限 |
| 日期字段报错 | 飞书日期字段需要毫秒时间戳 |
| 链接字段报错 | 字段类型不是 URL / 超链接 |

### 第九步：验证 Obsidian 写入

检查目标目录是否生成文件：

```bash
find "/ABSOLUTE/PATH/ObsidianVault/30-素材/公众号文章/公众号监控" -maxdepth 3 -type f | head
```

最低验收标准：

```text
公众号监控｜总索引.md
公众号名称/公众号名称｜原文索引.md
公众号名称/2026-xx-xx 文章标题.md
```

如果 macOS 后台任务没有权限写 Obsidian 目录，需要给终端、Python、Codex 或 WorkBuddy 完整磁盘访问权限。

### 第十步：配置后台定时任务

macOS 推荐用 LaunchAgent。

先写运行脚本：

```bash
mkdir -p ~/.local/bin ~/.local/var/log ~/.local/share/wechat-monitor
```

示例 `~/.local/bin/run-wechat-article-monitor`：

```bash
#!/bin/zsh
set -e

python3 /PATH/TO/monitor.py \
  --config "$HOME/.local/share/wechat-monitor/config.json" \
  --once

python3 /PATH/TO/export_obsidian_articles.py \
  --config "$HOME/.local/share/wechat-monitor/config.json" \
  --werss-db "$HOME/.local/share/we-mp-rss/data/db.db" \
  --out-dir "/ABSOLUTE/PATH/ObsidianVault/30-素材/公众号文章/公众号监控" \
  >/dev/null || true
```

如果使用 WeRSS，运行脚本还应在刷新后检查授权状态。最低要求是：一旦新增日志里出现 `Invalid Session` 或 `授权过期`，立刻发飞书异常提醒，提示用户重新扫码。否则用户会误以为“只是这几个公众号没更新”，实际是 WeRSS 数据源已经断了。

加执行权限：

```bash
chmod +x ~/.local/bin/run-wechat-article-monitor
```

LaunchAgent 示例 `~/Library/LaunchAgents/local.wechat-article-monitor.plist`：

```xml

  Label
  local.wechat-article-monitor
  ProgramArguments
  
    /Users/YOUR_NAME/.local/bin/run-wechat-article-monitor
  
  StartInterval
  21600
  RunAtLoad
  
  StandardOutPath
  /Users/YOUR_NAME/.local/var/log/wechat-article-monitor.out.log
  StandardErrorPath
  /Users/YOUR_NAME/.local/var/log/wechat-article-monitor.err.log

```

加载：

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.wechat-article-monitor.plist
launchctl enable gui/$(id -u)/local.wechat-article-monitor
launchctl kickstart -k gui/$(id -u)/local.wechat-article-monitor
```

检查：

```bash
launchctl print gui/$(id -u)/local.wechat-article-monitor
tail -n 100 ~/.local/var/log/wechat-article-monitor.err.log
```

WeRSS 本身也需要常驻。如果 WeRSS 不是 Docker 常驻运行，也要单独配置一个常驻任务。

## 最终验收清单

交付时，Agent 必须给出这些结果：

```text
1. WeRSS 地址：
2. WeRSS 是否已登录：
3. 已添加公众号：
   - 公众号 A：MP_WXS_xxx
   - 公众号 B：MP_WXS_xxx
4. 配置文件路径：
5. 去重数据库路径：
6. 日志文件路径：
7. 飞书提醒测试结果：
8. 多维表格写入测试结果：
9. Obsidian 写入目录：
10. WeRSS 授权过期提醒是否已配置：
11. 后台定时任务状态：
12. 下次预计运行时间：
13. 当前仍存在的限制或风险：
```

只有这些都确认了，才算真正跑通。

## 这套方案的边界

这套方案适合文章监控和内容沉淀，但有边界：

- 它依赖 WeRSS 的微信登录态。
- WeRSS 失效、登录过期、微信风控时会影响抓取。
- 必须给 WeRSS 授权过期加提醒，否则最容易出现“部分公众号几天没更新才发现”的情况。
- 不是所有公众号都能稳定添加。
- 如果文章被删除，已经写入 Obsidian 的历史文件不会自动删除。
- 图片通常仍引用公众号原图链接，不一定全部本地化。
- 如果只保存 feed 摘要，不等于保存了完整正文；要完整正文必须从 WeRSS 数据库导出。
- 飞书字段名、字段类型、权限配置必须和脚本匹配。

这些边界不是缺陷，而是为了优先保证稳定、可维护、低成本。

## 安全注意事项

不要把下面这些信息发到公开网页、GitHub 或公开教程截图里：

- 飞书 `app_secret`
- 飞书 `tenant_access_token`
- 多维表格 `app_token`
- 表格 `table_id`
- 个人 `open_id`
- WeRSS 登录密码
- 微信 cookie 或登录态数据
- Obsidian 私有路径中包含隐私的部分

分享教程时，用占位符替代：

```text
YOUR_APP_ID
YOUR_APP_SECRET
YOUR_APP_TOKEN
YOUR_TABLE_ID
YOUR_OPEN_ID
YOUR_OBSIDIAN_VAULT_PATH
```

## 最后一句话

这套工作流的价值不是“抓公众号文章”，而是把值得关注的内容源变成一个稳定进入飞书和 Obsidian 的入口。

一旦跑通，你后面要做的就不是每天手动翻公众号，而是在飞书里筛选、在 Obsidian 里沉淀、再交给 Agent 做拆解、改写和复盘。

---

![图片展示的是知识付费营销专家石更新的个人二维码。上方有其头像及“石更新”“北京 海淀”的字样。中间是一个黑色的二维码，下方配有“扫一扫上面的二维码图案，加我为朋友”的文字。该图片位于文档结尾处，是作者石更新的联系方式展示，方便读者扫描二维码添加其为好友，获取更多关于公众号文章监控工作流等知识付费内容。](https://feishu.cn/file/LxbybJS30oTQaLxTYm2cSyDonng)

![图片是一个二维码，中间嵌有一张人物照片，照片中人物穿着深色外套，双手交叉放在腿上。二维码周围有黑色边框。该图片位于文档结尾处，与文档内容紧密相关，可能是作者石更新的个人二维码，读者可通过扫描此二维码获取其详细介绍，了解其作为知识付费营销专家的相关信息。](https://feishu.cn/file/KFffbkUpCo0pOExQjzAcWIRHnO8)

![图片展示了一个视频号二维码，上方有“更新私域笔记”的文字及一张人物头像。中间是黑色线条构成的二维码，底部有“扫一扫二维码，关注我的视频号”的提示。该图片位于文档结尾处，是作者石更新的视频号二维码，供读者扫码关注，与文档中介绍作者及鼓励关注的内容相呼应，方便读者获取更多知识付费相关资讯。](https://feishu.cn/file/F5oIbAfpeo7stwx1MrncHTtNnlg)

点击查看我的详细介绍
