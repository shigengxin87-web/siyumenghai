import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("export_daily_chat.py")
SPEC = importlib.util.spec_from_file_location("export_daily_chat", MODULE_PATH)
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)


class ExportDailyChatTests(unittest.TestCase):
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
