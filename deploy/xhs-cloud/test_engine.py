import json
import os
import tempfile
import time
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

    def test_video_http_cdn_is_upgraded_to_https(self):
        note = {"video": {"media": {"stream": {"EF5": [
            {
                "videoBitrate": 3000,
                "backupUrls": ["http://sns-bak-v1.xhscdn.com/path/video.mp4?sign=abc"],
                "masterUrl": "http://sns-video-v6.xhscdn.com/path/video.mp4",
            }
        ]}}}}
        self.assertEqual(
            engine._video_url(note),
            "https://sns-bak-v1.xhscdn.com/path/video.mp4?sign=abc",
        )

    def test_audio_and_compatible_video_preferred_over_silent_high_bitrate(self):
        note = {"video": {"media": {"stream": {
            "EF4": [{"audioCodec": "aac", "videoBitrate": 350, "height": 960, "masterUrl": "https://sns-video-bd.xhscdn.com/sound.mp4"}],
            "EF5": [{"videoBitrate": 500, "height": 1440, "masterUrl": "https://sns-video-bd.xhscdn.com/silent.mp4"}]
        }}}}
        self.assertEqual(engine._video_url(note), "https://sns-video-bd.xhscdn.com/sound.mp4")

    def test_native_picture_and_audio_preferred_to_watermarked_web_mp4(self):
        native = {"audio_stream": {"AAC": [{"audio_codec": "aac", "audio_bitrate": 192000,
                  "audio_duration": 161448, "backup_urls": ["http://sns-bak-v1.xhscdn.com/audio.m4a"]}]}}
        note = {"video": {"mediaV2": json.dumps(native), "media": {"stream": {
            "EF4": [{"format": "mp4", "audioCodec": "aac", "height": 720,
                     "masterUrl": "https://sns-video-v6.xhscdn.com/watermarked.mp4"}],
            "EF5": [{"format": "fmp4", "height": 1080, "width": 1920, "duration": 161433,
                     "masterUrl": "https://sns-video-v6.xhscdn.com/picture.m4s"}]
        }}}}
        assets = engine._video_assets(note)
        self.assertEqual(assets["video"], "https://sns-video-v6.xhscdn.com/picture.m4s")
        self.assertEqual(assets["audio"], "https://sns-bak-v1.xhscdn.com/audio.m4a")
        self.assertTrue(assets["video_requires_mux"])
        self.assertEqual(assets["video_codec"], "hevc")
        self.assertEqual(assets["video_height"], 1080)
        native["audio_stream"]["AAC"][0]["audio_duration"] = 10000
        note["video"]["mediaV2"] = json.dumps(native)
        self.assertFalse(engine._video_assets(note)["video_requires_mux"])
        note["video"]["mediaV2"] = "not json"
        self.assertEqual(engine._video_assets(note)["video"], "https://sns-video-v6.xhscdn.com/watermarked.mp4")

    def test_video_external_cdn_is_rejected(self):
        note = {"video": {"media": {"stream": {"EF5": [
            {"videoBitrate": 3000, "backupUrls": ["http://127.0.0.1/secret"], "masterUrl": "https://evil.example.com/file.mp4"}
        ]}}}}
        self.assertEqual(engine._video_url(note), "")

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

    def test_browser_fast_path_skips_http_when_successful(self):
        requested = "https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef"
        expected = {"id": "67abcdef0123456789abcdef", "type": "image"}
        with patch.object(engine, "parse_page", side_effect=engine.ParseError("blocked")) as page:
            with patch.object(engine, "parse_browser", return_value=expected) as browser:
                self.assertEqual(engine.parse_work(requested), expected)
        page.assert_not_called()
        browser.assert_called_once()

    def test_http_fallback_runs_when_browser_fails(self):
        requested = "https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef"
        expected = {"id": "67abcdef0123456789abcdef", "type": "image"}
        with patch.object(engine, "parse_browser", side_effect=engine.ParseError("blocked")) as browser:
            with patch.object(engine, "parse_page", return_value=expected) as page:
                self.assertEqual(engine.parse_work(requested, refresh=True), expected)
        browser.assert_called_once()
        page.assert_called_once()

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


class ParseCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = engine.CACHE_DB
        self._old_ttl = engine.CACHE_TTL
        engine.CACHE_DB = os.path.join(self._tmp.name, "parse_cache.db")
        engine.CACHE_TTL = 7 * 24 * 3600
        self.note_id = "67abcdef0123456789abcdef"
        self.url = f"https://www.xiaohongshu.com/explore/{self.note_id}?xsec_token=old"

    def tearDown(self):
        engine.CACHE_DB = self._old_db
        engine.CACHE_TTL = self._old_ttl
        self._tmp.cleanup()

    def test_cache_hit_skips_live_parsers(self):
        engine.cache_store(self.note_id, self.url, {"id": self.note_id, "title": "缓存视频"})
        with patch.object(engine, "resolve_url", return_value=self.url):
            with patch.object(engine, "parse_page", side_effect=AssertionError("page called")):
                with patch.object(engine, "parse_browser", side_effect=AssertionError("browser called")):
                    with patch.object(engine, "parse_ytdlp", side_effect=AssertionError("ytdlp called")):
                        result = engine.parse_work("https://xhslink.cn/o/test")
        self.assertTrue(result["cached"])
        self.assertEqual(result["title"], "缓存视频")
        # Freshly resolved URL (new xsec_token) replaces the stored one.
        self.assertEqual(result["web_url"], self.url)

    def test_cache_miss_parses_once_then_serves_from_cache(self):
        fresh = {"id": self.note_id, "type": "image", "title": "新解析"}
        share_text = "复制打开小红书 https://xhslink.cn/o/test。"
        with patch.object(engine, "resolve_url", return_value=self.url):
            with patch.object(engine, "parse_page", return_value=fresh) as page:
                first = engine.parse_work(share_text)
                self.assertEqual(first["title"], "新解析")
                self.assertNotIn("cached", first)
                second = engine.parse_work(share_text)
        self.assertEqual(page.call_count, 1)
        self.assertTrue(second["cached"])
        self.assertEqual(second["title"], "新解析")

    def test_legacy_video_cache_does_not_keep_watermarked_selection(self):
        engine.cache_store(self.note_id, self.url, {"id": self.note_id, "video": "https://sns-video-v6.xhscdn.com/old.mp4"})
        with engine._cache_connect() as db:
            row = db.execute("SELECT data FROM xhs_parse_records WHERE note_id = ?", (self.note_id,)).fetchone()
            data = json.loads(row[0]); data["_cache_schema"] = 2
            db.execute("UPDATE xhs_parse_records SET data = ? WHERE note_id = ?", (json.dumps(data), self.note_id))
        self.assertIsNone(engine.cache_lookup(self.note_id))

    def test_refresh_bypasses_existing_metadata(self):
        engine.cache_store(self.note_id, self.url, {"id": self.note_id, "title": "老数据"})
        with patch.object(engine, "resolve_url", return_value=self.url):
            with patch.object(engine, "parse_browser", return_value={"id": self.note_id, "title": "新数据"}) as browser:
                result = engine.parse_work(self.url, refresh=True)
        browser.assert_called_once()
        self.assertEqual(result["title"], "新数据")

    def test_expired_cache_entry_is_discarded(self):
        engine.cache_store(self.note_id, self.url, {"id": self.note_id, "title": "老数据"})
        with engine._cache_connect() as db:
            db.execute(
                "UPDATE xhs_parse_records SET expire_at = ? WHERE note_id = ?",
                (time.time() - 10, self.note_id),
            )
        self.assertIsNone(engine.cache_lookup(self.note_id))

    def test_broken_cache_path_does_not_break_parse(self):
        engine.CACHE_DB = "/nonexistent-root/siyumenghai-xhs/parse_cache.db"
        fresh = {"id": self.note_id, "title": "降级成功"}
        with patch.object(engine, "resolve_url", return_value=self.url):
            with patch.object(engine, "parse_page", return_value=fresh):
                result = engine.parse_work("复制打开小红书 https://xhslink.cn/o/test。")
        self.assertEqual(result["title"], "降级成功")

    def test_zero_ttl_disables_cache(self):
        engine.CACHE_TTL = 0
        self.assertIsNone(engine.cache_lookup(self.note_id))
        engine.cache_store(self.note_id, self.url, {"id": self.note_id})
        self.assertIsNone(engine.cache_lookup(self.note_id))

    def test_shape_note_includes_duration_when_present(self):
        note_id = "67abcdef0123456789abcdef"
        post = engine.shape_note(
            "https://www.xiaohongshu.com/explore/" + note_id,
            note_id,
            {
                "noteId": note_id,
                "title": "时长作品",
                "video": {"capa": {"duration": "52"}, "media": {"stream": {"EF4": [
                    {"masterUrl": "https://sns-video-bd.xhscdn.com/clip.mp4"}
                ]}}},
            },
        )
        self.assertEqual(post["duration"], "52")


class AuthorTests(unittest.TestCase):
    def test_extract_user_id_from_profile_url(self):
        self.assertEqual(
            engine.user_id_from_url("https://www.xiaohongshu.com/user/profile/5f1a2b3c4d5e6f7a8b9c0d1e?xsec_token=x"),
            "5f1a2b3c4d5e6f7a8b9c0d1e",
        )
        self.assertEqual(engine.user_id_from_url("https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef"), "")

    def test_shape_author_walks_initial_state(self):
        note_id = "67abcdef0123456789abcdef"
        state = {
            "user": {"nickname": "海边日记"},
            "note": {"userNotes": [
                {"noteId": note_id, "displayTitle": "日落", "cover": {"urlDefault": "https://sns-img-bd.xhscdn.com/spectrum/cover"}},
                {"noteId": note_id.upper(), "displayTitle": "重复应去重", "cover": {"urlDefault": "https://sns-img-bd.xhscdn.com/spectrum/dup"}},
            ]},
        }
        result = engine.shape_author("user123", "https://www.xiaohongshu.com/user/profile/user123", state)
        self.assertEqual(result["kind"], "author")
        self.assertEqual(result["author"]["nickname"], "海边日记")
        self.assertEqual(len(result["notes"]), 1)
        self.assertEqual(result["notes"][0]["id"], note_id)
        self.assertEqual(result["notes"][0]["title"], "日落")
        self.assertTrue(result["notes"][0]["cover"].startswith("https://sns-img-bd.xhscdn.com/"))

    def test_parse_work_routes_profile_url_to_author(self):
        url = "https://www.xiaohongshu.com/user/profile/user123"
        expected = {"kind": "author", "author": {"nickname": "博主"}}
        with patch.object(engine, "resolve_url", return_value=url):
            with patch.object(engine, "parse_work_author", return_value=expected) as author:
                with patch.object(engine, "parse_page", side_effect=AssertionError("note path called")):
                    result = engine.parse_work("https://xhslink.cn/o/author")
        author.assert_called_once()
        self.assertEqual(result, expected)

    def test_parse_work_keeps_note_path_for_explore_url(self):
        url = "https://www.xiaohongshu.com/explore/67abcdef0123456789abcdef"
        fresh = {"id": "67abcdef0123456789abcdef", "title": "单条"}
        with patch.object(engine, "resolve_url", return_value=url):
            with patch.object(engine, "parse_work_author", side_effect=AssertionError("author path called")):
                with patch.object(engine, "cache_lookup", return_value=None):
                    with patch.object(engine, "parse_page", return_value=fresh) as page:
                        result = engine.parse_work("https://xhslink.cn/o/note")
        self.assertEqual(page.call_count, 1)
        self.assertEqual(result["title"], "单条")


if __name__ == "__main__":
    unittest.main()
