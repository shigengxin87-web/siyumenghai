import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("export_daily_chat.py")
SPEC = importlib.util.spec_from_file_location("export_daily_chat", MODULE_PATH)
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)


class ExportDailyChatTests(unittest.TestCase):
    def test_sticker_is_omitted(self):
        raw = {"messages": [{"time": "2026-09-16 18:45:07", "sender": "石更新", "type": "表情", "content": "[表情]"}]}
        payload, report = EXPORTER.convert(raw, "2026-09-16", "石更新", {})
        self.assertEqual([], payload["messages"])
        self.assertEqual(0, report["displayedCount"])
        self.assertEqual(1, report["omittedStickerCount"])

    def test_system_xml_is_reduced_to_safe_text(self):
        xml = '<sysmsg type="revokemsg"><revokemsg><content>"群友" 撤回了一条消息</content></revokemsg></sysmsg>'
        self.assertEqual('"群友" 撤回了一条消息', EXPORTER.parse_system(xml))

    def test_local_file_path_is_removed(self):
        title, _, _ = EXPORTER.parse_link("[文件] 工具.zip\n/Users/example/private/tool.zip")
        self.assertEqual("工具.zip", title)

    def test_attached_file_gets_public_download_link(self):
        raw = {"messages": [{"time": "2026-09-10 18:04:35", "sender": "石更新", "type": "链接/文件", "content": "[文件] 工具.zip\n/Users/private/tool.zip"}]}
        media = {"2026-09-10 18:04:35": {"kind": "file", "url": "./assets/chat/2026-09-10/tool.zip", "label": "下载文件"}}
        payload, _ = EXPORTER.convert(raw, "2026-09-10", "石更新", {}, media)
        self.assertEqual("下载文件", payload["messages"][0]["links"][0]["label"])
        self.assertNotIn("/Users/", payload["messages"][0]["text"])

    def test_unsupported_wechat_channel_is_explained(self):
        raw = {"messages": [{"time": "2026-09-16 21:22:16", "sender": "石更新", "type": "链接/文件", "content": "[文件] 当前微信版本不支持展示该内容，请升级至最新版本。"}]}
        payload, _ = EXPORTER.convert(raw, "2026-09-16", "石更新", {})
        self.assertEqual("link", payload["messages"][0]["type"])
        self.assertIn("视频号", payload["messages"][0]["text"])
        self.assertIn("无法同步或跳转", payload["messages"][0]["text"])

    def test_redacts_common_sensitive_values(self):
        source = "手机 13812345678，身份证 110101199001011234，银行卡 6222021234567890"
        cleaned, changed = EXPORTER.redact(source)
        self.assertTrue(changed)
        self.assertNotIn("13812345678", cleaned)
        self.assertNotIn("110101199001011234", cleaned)
        self.assertNotIn("6222021234567890", cleaned)

    def test_rejects_unsafe_link_protocol(self):
        xml = "<msg><appmsg><title>测试</title><url>javascript:alert(1)</url></appmsg></msg>"
        title, _, links = EXPORTER.parse_link(xml)
        self.assertEqual("测试", title)
        self.assertEqual([], links)

    def test_detects_binary_garbage(self):
        self.assertTrue(EXPORTER.is_unreadable("\ufffd\ufffd\x01\x02\ufffd\ufffd"))
        self.assertFalse(EXPORTER.is_unreadable("这是一条可以正常阅读的文字消息"))

    def test_converts_owner_to_right_without_private_ids(self):
        raw = {"messages": [{
            "time": "2026-09-16 08:00:00",
            "sender": "石更新",
            "sender_username": "private-id",
            "type": "文本",
            "content": "早上好",
        }]}
        payload, report = EXPORTER.convert(raw, "2026-09-16", "石更新", {})
        self.assertEqual("right", payload["messages"][0]["side"])
        self.assertNotIn("sender_username", payload["messages"][0])
        self.assertEqual(1, report["displayedCount"])

    def test_includes_only_site_media_urls(self):
        raw = {"messages": [{
            "time": "2026-09-16 18:44:30", "sender": "石更新", "type": "图片", "content": "[图片]"
        }]}
        media = {"2026-09-16 18:44:30": {"url": "./assets/chat/2026-09-16/image.jpg", "alt": "群聊图片"}}
        payload, report = EXPORTER.convert(raw, "2026-09-16", "石更新", {}, media)
        self.assertEqual("./assets/chat/2026-09-16/image.jpg", payload["messages"][0]["media"]["url"])
        self.assertEqual(0, report["missingMediaCount"])

    def test_keeps_plain_file_title(self):
        title, description, links = EXPORTER.parse_link("[文件] 相互影响，一同成长.pdf")
        self.assertEqual("相互影响，一同成长.pdf", title)
        self.assertEqual("", description)
        self.assertEqual([], links)


if __name__ == "__main__":
    unittest.main()
