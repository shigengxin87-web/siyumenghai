import json
import os
import unittest
from unittest.mock import patch

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

    def test_synthetic_a1_has_browser_cookie_shape(self):
        value = engine._synthetic_a1()
        self.assertEqual(len(value), 52)
        self.assertRegex(value, r"^[a-z0-9]+$")

    def test_cookie_header_is_split_into_cookie_jar(self):
        with engine.httpx.Client() as client:
            engine._apply_cookie_header(client, "a1=device-value; web_session=session-value")
            self.assertEqual(client.cookies.get("a1", domain=".xiaohongshu.com"), "device-value")
            self.assertEqual(client.cookies.get("web_session", domain=".xiaohongshu.com"), "session-value")

    def test_shortlink_rejects_external_redirect(self):
        class FakeResponse:
            status_code = 302
            headers = {"location": "https://example.com/internal"}
        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def get(self, _url): return FakeResponse()
        with patch.object(engine.httpx, "Client", return_value=FakeClient()):
            with self.assertRaisesRegex(engine.ParseError, "跳转异常"):
                engine.resolve_url("https://xhslink.cn/example")

    def test_shortlink_accepts_platform_redirect(self):
        target = "https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef?xsec_token=abc"
        class FakeResponse:
            status_code = 302
            headers = {"location": target}
        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def get(self, _url): return FakeResponse()
        with patch.object(engine.httpx, "Client", return_value=FakeClient()):
            self.assertEqual(engine.resolve_url("https://xhslink.cn/example"), target)

    def test_video_shape_from_stream_group(self):
        note_id = "67abcdef0123456789abcdef"
        post = engine.shape_note(
            "https://www.xiaohongshu.com/explore/" + note_id,
            note_id,
            {
                "noteId": note_id,
                "title": "测试视频",
                "imageList": [{"urlDefault": "https://sns-img-bd.xhscdn.com/spectrum/cover"}],
                "video": {"media": {"stream": {"EF4": [
                    {"videoBitrate": 2000, "masterUrl": "https://sns-video-bd.xhscdn.com/clip.mp4"}
                ]}}},
            },
        )
        self.assertEqual(post["type"], "video")
        self.assertEqual(post["images"], [])
        self.assertEqual(post["video"], "https://sns-video-bd.xhscdn.com/clip.mp4")

    def test_browser_fallback_shapes_requested_note(self):
        from types import SimpleNamespace
        note_id = "67abcdef0123456789abcdef"
        payload = {"noteId": note_id, "desc": "文章", "imageList": [
            {"urlDefault": "https://sns-img-bd.xhscdn.com/spectrum/testimage"}]}
        process = SimpleNamespace(returncode=0, stdout=json.dumps(payload))
        with patch.object(engine.subprocess, "run", return_value=process) as run:
            result = engine.parse_browser(f"https://www.xiaohongshu.com/explore/{note_id}")
        self.assertEqual(result["type"], "image")
        self.assertEqual(result["id"], note_id)
        self.assertEqual(len(result["images"]), 1)
        self.assertIn("timeout", run.call_args.kwargs)

    def test_browser_fallback_rejects_wrong_note(self):
        from types import SimpleNamespace
        process = SimpleNamespace(returncode=0, stdout=json.dumps({"noteId":"another"}))
        with patch.object(engine.subprocess, "run", return_value=process):
            with self.assertRaisesRegex(engine.ParseError, "标识不匹配"):
                engine.parse_browser("https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef")

    def test_falls_back_to_browser_after_page_refusal(self):
        requested = "https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef"
        expected = {"id": "67abcdef0123456789abcdef", "type": "image"}
        with patch.object(engine, "parse_page", side_effect=engine.ParseError("blocked")) as page:
            with patch.object(engine, "parse_browser", return_value=expected) as browser:
                self.assertEqual(engine.parse_work(requested), expected)
        page.assert_called_once()
        browser.assert_called_once()

    def test_parse_page_reuses_bootstrapped_client_and_closes_it(self):
        note_id = "67abcdef0123456789abcdef"
        state = {"note": {"noteDetailMap": {note_id: {"note": {"noteId": note_id, "title": "测试图文"}}}}}

        class Response:
            is_redirect = False
            text = f'<script>window.__INITIAL_STATE__={json.dumps(state, ensure_ascii=False)};</script>'

            @staticmethod
            def raise_for_status():
                return None

        class Client:
            closed = False

            @staticmethod
            def get(_url):
                return Response()

            def close(self):
                self.closed = True

        client = Client()
        with patch.object(engine, "_page_client", return_value=client):
            result = engine.parse_page(f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token=test")
        self.assertEqual(result["title"], "测试图文")
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
