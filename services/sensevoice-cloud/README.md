# SenseVoice 云端逐字稿服务

这是正式页面 `/api/transcripts-cloud/` 使用的云端排队服务源码。服务保留
SenseVoice 原始识别稿，在校正阶段把硬字幕 OCR 作为辅助证据交给 DeepSeek，
最终页面只展示一份校正后的完整逐字稿。

运行约束：单条视频最长 10 分钟；任务、缓存和临时文件使用独立数据目录；
DeepSeek 密钥只由 systemd 的环境文件提供。硬字幕 OCR 失败时仍继续完成 ASR，
不会因为画面识别失败而丢失逐字稿。

部署文件：

- `server.py` → `/opt/siyumenghai-sensevoice-cloud-test/server.py`
- `deepseek_correction.py` → `/opt/siyumenghai-sensevoice-cloud-test/deepseek_correction.py`
- `../transcript-server/ocr_worker.py` → `/opt/siyumenghai-sensevoice-cloud-test/ocr_worker.py`

更新后先执行 `python3 -m py_compile`，再重启
`siyumenghai-sensevoice-cloud-test.service`，最后检查本机健康接口和正式公网接口。
