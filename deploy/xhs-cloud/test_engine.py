import json
import os
import unittest

os.environ.setdefault("XHS_API_KEY", "test-key")

import engine


class EngineTests(unittest.TestCase):
    def test_extracts_share_url_without_trailing_punctuation(self):
        value = engine.extract_url("复制打开小红书 https://xhslink.com/a1B2c3。")
        self.assertEqual(value, "https://xhslink.com/a1B2c3")

    def test_rejects_non_xhs_url(self):
        with self.assertRaises(engine.ParseError):
            engine.extract_url("https://example.com/explore/abc")

    def test_note_id_requires_work_route(self):
        self.assertEqual(engine.note_id_from_url("https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef?xsec_token=x"), "67abcdef0123456789abcdef")
        self.assertEqual(engine.note_id_from_url("https://www.xiaohongshu.com/user/profile/abc"), "")

    def test_initial_state_normalizes_undefined_outside_strings(self):
        payload = {"note": {"noteDetailMap": {}}}
        document = f'<script>window.__INITIAL_STATE__={json.dumps(payload)[:-1]},"x":undefined}};</script>'
        state = engine.load_initial_state(document)
        self.assertIsNone(state["x"])

    def test_image_token_removes_ephemeral_prefix(self):
        url = "https://sns-img-bd.xhscdn.com/202610131234/0123456789abcdef0123456789abcdef/spectrum/1040g0k0abc!nd_dft_wlteh_webp_3"
        self.assertEqual(engine._image_url(url), "https://sns-img-bd.xhscdn.com/spectrum/1040g0k0abc")


if __name__ == "__main__":
    unittest.main()
