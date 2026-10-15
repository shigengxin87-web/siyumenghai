# 石董会｜唯一小程序发布源码

AppID：wx8518a4f16ab72d70。四栏：首页、技巧、AI问答、讨论。

用户确认 Downloads/miniprogram-enterprise 是正式 2.0.1 的来源。2026-10-16 已将其与 WorkBuddy 后续改动合并到本目录，替换 GitHub 上旧的“成长朋友圈”界面。多个本地目录是同一 AppID 的历史开发副本，不是多个小程序。

GitHub main 的 miniprogram/ 是版本源；本机 /Users/murphys/Downloads/miniprogram-enterprise 是唯一开发者工具发布目录，与版本源保持一致。其余 xhs-release/miniprogram 及旧项目只作恢复依据，不再从它们预览或上传。本轮预览版本标识 2.1.0，不改变线上版本，未完成真机验收前不提交审核。

保留四栏与石董会现有风格。包括三平台原生保存、近期解析复用、相册权限恢复、收藏与搜索、AI 会话保存和流式回复；补齐日报正文及名录头像。技巧内容从真实社群日报提取，不使用示例条目作为新版本默认内容。

运行 node tools/build-miniprogram-content.cjs（仓库根目录）可从网站日报生成 member-view/miniprogram-content.json 与本机离线数据。服务器静态发布后，同结构的技巧及讨论目录可更新，不需要修改页面代码。当前内容日期以生成结果为准。

验证：node --test miniprogram/tests/*.test.js deploy/agent-proxy/server.test.js。
云端问答：deploy/agent-proxy/server.js；敏感配置只留服务器 /opt/siyumenghai-agent-proxy/config.json，不进 Git。

发布前确认微信公众平台 request / downloadFile 合法域名包含 https://siyumenghai.cn，隐私保护指引声明相册写入用途。urlCheck 保持 true。微信扫码、真机声音/拖动/相册落地与域名验证需单独验收，CLI 编译成功不能代替。
