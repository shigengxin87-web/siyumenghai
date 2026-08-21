# 腾讯逐字稿独立服务

这是与正式转写服务完全隔离的测试实现。仅监听 `127.0.0.1:2032`，任务与缓存写入
`/var/lib/siyumenghai-transcript-tencent-test`，凭证文件为
`/etc/siyumenghai-transcript-tencent-test.csv`，不得提交到 Git。

默认限制单条视频不超过 10 分钟，不设到期时间或累计计费时长上限。服务只接收
视频号分享链接，后台自行解析视频并异步生成逐字稿；服务重启后会恢复未完成任务。
