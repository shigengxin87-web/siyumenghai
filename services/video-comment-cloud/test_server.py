import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class CommentServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["COMMENT_CLOUD_DATA_DIR"] = cls.temp.name
        os.environ["COMMENT_CLOUD_KEY_FILE"] = str(Path(cls.temp.name) / "key")
        module_path = Path(__file__).with_name("server.py")
        spec = importlib.util.spec_from_file_location("comment_server_test", module_path)
        cls.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.server)

    @classmethod
    def tearDownClass(cls):
        cls.server.EXECUTOR.shutdown(wait=True)
        cls.temp.cleanup()

    def setUp(self):
        self.server.JOBS.clear()
        self.server.restore_jobs()

    def test_share_url_validation(self):
        self.assertEqual(
            self.server.valid_share_url("https://weixin.qq.com/sph/AV847UN3k9?x=1"),
            "https://weixin.qq.com/sph/AV847UN3k9",
        )
        with self.assertRaises(self.server.PublicError):
            self.server.valid_share_url("https://example.com/sph/AV847UN3k9")

    def test_complete_job_and_cache(self):
        responses = [
            {"object_id": "123456"},
            {
                "comment_list": [
                    {
                        "comment_id": "c1",
                        "content": "说得很对",
                        "nickname": "访客甲",
                        "like_count": 3,
                        "create_time": 1767517201,
                        "ip_region_info": {"region_text": "广东"},
                        "reply_list": [{"comment_id": "r1", "content": "谢谢", "nickname": "作者"}],
                    }
                ],
                "down_continue": False,
                "last_buffer": "",
            },
        ]

        def fake_request(_path, _body):
            return responses.pop(0)

        job_id = "job-one"
        share_url = "https://weixin.qq.com/sph/AV847UN3k9"
        self.server.JOBS[job_id] = {
            "id": job_id, "share_url": share_url, "status": "queued", "stage": "等待处理",
            "created_at": self.server.now_iso(), "updated_at": self.server.now_iso(), "finished_at": "",
            "elapsed_seconds": 0, "comment_count": 0, "reply_count": 0, "comments": [], "error": "",
            "cache_hit": False, "pipeline_version": self.server.PIPELINE_VERSION,
        }
        with patch.object(self.server, "provider_request", side_effect=fake_request):
            self.server.process(job_id)
        result = self.server.JOBS[job_id]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["comment_count"], 1)
        self.assertEqual(result["reply_count"], 1)
        self.assertEqual(result["comments"][0]["content"], "说得很对")
        self.assertEqual(result["comments"][0]["ipRegionInfo"]["regionText"], "广东")

        cached = self.server.load_cache(share_url)
        self.assertEqual(cached["comment_count"], 1)

    def test_provider_failure_keeps_safe_message(self):
        job_id = "job-fail"
        self.server.JOBS[job_id] = {
            "id": job_id, "share_url": "https://weixin.qq.com/sph/FAIL", "status": "queued",
            "stage": "等待处理", "created_at": self.server.now_iso(), "updated_at": self.server.now_iso(),
            "finished_at": "", "elapsed_seconds": 0, "comment_count": 0, "reply_count": 0,
            "comments": [], "error": "", "cache_hit": False, "pipeline_version": self.server.PIPELINE_VERSION,
        }
        with patch.object(self.server, "provider_request", side_effect=RuntimeError("secret diagnostic")):
            self.server.process(job_id)
        self.assertEqual(self.server.JOBS[job_id]["status"], "failed")
        self.assertNotIn("secret", self.server.JOBS[job_id]["error"])


if __name__ == "__main__":
    unittest.main()
