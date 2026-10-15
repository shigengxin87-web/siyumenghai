# 石董会 ADP 问答代理

监听127.0.0.1:2035，Nginx转发/api/agent/chat。配置文件仍保留生产服务器路径，不提交AppKey。
旧客户端stream:false保持JSON；旧stream:true保持纯文本。新客户端stream_format:events接收逐行JSON delta/replace/done/error，按MessageId仅处理reply，支持替换、done全文与末行无换行，阻止thought文本混入。
conversation_id可选，用于用户主动开始新会话；不传则保留旧会话ID算法。清空仅清本机记录并开启新会话，不声称删除腾讯云历史。
流式请求55秒内结束；客户端60秒。客户端断开时取消上游。响应X-Accel-Buffering:no关闭Nginx响应缓冲。
部署前保存旧server.js，node --check后重启siyumenghai-agent-proxy.service，验证旧JSON与新事件流。运行server.test.js使用本机假上游，不消耗云端额度。
