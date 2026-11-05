# 小程序源码唯一来源（SOURCE OF TRUTH）

最后更新：2026-11-05

## 唯一位置

```
本地：~/Documents/siyumenghai/miniprogram
远端：https://github.com/shigengxin87-web/siyumenghai  →  miniprogram/
```

开发、预览、上传，**只用这个目录**。

## 为什么之前会找不到

同一个 AppID（`wx8518a4f16ab72d70`）在本机存在过至少 6 份副本，分布在
`Downloads`、`Documents/Codex/*`、`Documents/code x/` 下。它们都是历史工作副本，
内容互不一致。2026-11-05 起统一到上面的位置，其余全部标记废弃。

微信**不提供**已发布小程序的源码下载，小程序后台只有版本记录和包大小，
拿不到文件。源码一旦丢了只能靠本地副本或 GitHub——这是必须上 Git 的唯一理由。

## 目录结构

本仓库同时托管网站和 deploy（后端部署脚本），体量较大，因此本地用
**稀疏检出**，只保留小程序相关文件：

```bash
git sparse-checkout list          # 确认当前只看哪些目录
git sparse-checkout add deploy    # 需要看后端脚本时再加
```

普通 `git clone` 整仓可能因为体积过大失败，这是正常现象，不是网络坏了。

## 发版流程（每次都要走）

1. 改代码
2. `git add` → `commit`（说明写清改了什么、为什么）
3. `git push origin main`
4. 微信开发者工具打开 `~/Documents/siyumenghai/miniprogram`，预览、真机验收
5. 上传 → 提交审核 → 发布
6. 在提交说明里记下**版本号 + 对应 commit hash**（例如 2.1.0 = 64b0224）

第 6 步是溯源的关键：只记版本号不记 commit，半年后就对不上源码了。

## 与后端的关系

小程序只调一个接口：`POST https://siyumenghai.cn/api/agent/chat`。

后端链路（不在此仓库的本地副本里，服务器上跑）：

```
nginx 443 → agent-proxy 127.0.0.1:2035 → WeKnora Lite 127.0.0.1:8081
```

后端源码同步在仓库 `deploy/agent-proxy/`，但**线上实际文件**是服务器上的
`/opt/siyumenghai-agent-proxy/server.js`。改后端必须两边同步，否则仓库里的不一定是线上跑的。

## 三个已踩过的坑

1. **AI 标识**：界面顶部 `.ai-notice` 常驻 + 每条回复 `.ai-label`，两处都要在。
   服务端不再追加标识文字（`config.weknora.aiNotice=false`），别两头都开，会重复。
2. **合法域名**：`request` 合法域名要包含 `https://siyumenghai.cn`，在微信公众平台配置，
   不是代码里配。
3. **上传目录选错**：开发者工具的项目路径一旦指向旧副本，改再多也传不上去。
   上传前先确认标题对不对（应该显示这个目录）。
