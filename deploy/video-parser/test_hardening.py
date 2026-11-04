#!/usr/bin/env python3
"""Regression tests for parser recovery and notification hardening."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock
import importlib.util as importlib_util
import sys


ROOT = Path(__file__).resolve().parents[2]

for optional_dependency in ("requests", "websocket", "yaml"):
    if importlib_util.find_spec(optional_dependency) is None:
        sys.modules[optional_dependency] = mock.Mock()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


healthcheck = load_module("video_parser_healthcheck", Path(__file__).with_name("healthcheck.py"))
refresh = load_module("yuanbao_refresh", Path(__file__).with_name("refresh_yuanbao_cookie.py"))
monitor = load_module("site_monitor", ROOT / "deploy/monitor/monitor_site.py")


class RefreshTests(unittest.TestCase):
    def test_existing_page_is_reused(self):
        page = {"type": "page", "url": refresh.YUANBAO_URL}
        with mock.patch.object(refresh, "yuanbao_page", return_value=page), mock.patch.object(
            refresh.requests, "put"
        ) as put:
            self.assertEqual(refresh.ensure_yuanbao_page(), (page, False))
            put.assert_not_called()

    def test_missing_page_is_created(self):
        page = {"type": "page", "url": refresh.YUANBAO_URL}
        response = mock.Mock()
        response.raise_for_status.return_value = None
        with mock.patch.object(refresh, "yuanbao_page", side_effect=[None, page]), mock.patch.object(
            refresh.requests, "put", return_value=response
        ) as put:
            self.assertEqual(refresh.ensure_yuanbao_page(), (page, True))
            put.assert_called_once()


class HealthcheckTests(unittest.TestCase):
    def test_second_canary_can_keep_service_healthy(self):
        def probe_one(_url, index):
            if index == 1:
                raise healthcheck.ProbeFailure("first canary unavailable")
            return {"canary": index, "has_video_url": True}

        with mock.patch.object(healthcheck, "probe_one", side_effect=probe_one):
            self.assertEqual(healthcheck.probe()["canary"], 2)

    def test_recovery_clears_systemd_start_limit_before_restart(self):
        completed = [mock.Mock(returncode=0), mock.Mock(returncode=0)]
        with mock.patch.object(healthcheck.subprocess, "run", side_effect=completed) as run:
            self.assertEqual(healthcheck.restart_service(), (0, 0))
        self.assertEqual(
            run.call_args_list,
            [
                mock.call(
                    ["systemctl", "reset-failed", healthcheck.SERVICE], check=False, timeout=15
                ),
                mock.call(["systemctl", "restart", healthcheck.SERVICE], check=False, timeout=45),
            ],
        )


class MonitorTests(unittest.TestCase):
    def test_webhook_requires_business_success_and_avoids_cli(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":0}'
        with mock.patch.dict(monitor.os.environ, {"SIYUMENGHAI_FEISHU_WEBHOOK": "https://example.com/secret"}), mock.patch.object(
            monitor.urllib.request, "urlopen", return_value=response
        ), mock.patch.object(monitor, "resolve_recipient") as resolve:
            self.assertTrue(monitor.notify("webhook", "test", "key")["ok"])
            resolve.assert_not_called()

    def test_webhook_transport_error_hides_secret(self):
        with mock.patch.dict(monitor.os.environ, {"SIYUMENGHAI_FEISHU_WEBHOOK": "https://example.com/secret"}), mock.patch.object(
            monitor.urllib.request, "urlopen", side_effect=RuntimeError("https://example.com/secret")
        ):
            with self.assertRaisesRegex(RuntimeError, "^Webhook transport failed: RuntimeError$"):
                monitor.notify("webhook", "test", "key")

    def test_webhook_business_rejection_is_failure(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":19022}'
        with mock.patch.dict(monitor.os.environ, {"SIYUMENGHAI_FEISHU_WEBHOOK": "https://example.com/secret"}), mock.patch.object(
            monitor.urllib.request, "urlopen", return_value=response
        ):
            with self.assertRaisesRegex(RuntimeError, "Webhook rejected: code=19022"):
                monitor.notify("webhook", "test", "key")

    def args(self, state_file: Path):
        return SimpleNamespace(
            state_file=state_file,
            check_local_comments=False,
            recipient_id="recipient",
            no_notify=False,
        )

    def test_notification_failure_is_saved_and_does_not_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text(json.dumps({"consecutive_failures": 1, "alerted": False}), encoding="utf-8")
            with mock.patch.object(monitor, "check_public", return_value=(["parser down"], {})), mock.patch.object(
                monitor, "notify", side_effect=RuntimeError("node unavailable")
            ):
                self.assertEqual(monitor.run(self.args(state_file)), 1)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertFalse(state["alerted"])
            self.assertIn("node unavailable", state["notification_error"])

    def test_self_recipient_uses_current_verified_identity(self):
        payload = {
            "verified": True,
            "identities": {"user": {"status": "ready", "openId": "current-open-id"}},
        }
        completed = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
        with mock.patch.object(monitor.subprocess, "run", return_value=completed):
            self.assertEqual(monitor.resolve_recipient("self"), "current-open-id")

    def test_recovery_notice_requests_manual_test(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text(json.dumps({"consecutive_failures": 3, "alerted": True}), encoding="utf-8")
            messages: list[str] = []

            def notify(_recipient, message, _key):
                messages.append(message)
                return {"ok": True}

            with mock.patch.object(monitor, "check_public", return_value=([], {})), mock.patch.object(
                monitor, "notify", side_effect=notify
            ):
                self.assertEqual(monitor.run(self.args(state_file)), 0)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertFalse(state["alerted"])
            self.assertIn("手动", messages[0])

    def test_short_auto_recovery_event_is_not_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text(json.dumps({"alerted": False}), encoding="utf-8")
            messages: list[str] = []

            def notify(_recipient, message, _key):
                messages.append(message)
                return {"ok": True}

            server_state = {"healthy": True, "last_recovery_at": "2026-11-05T02:52:52+08:00"}
            with mock.patch.object(monitor, "check_public", return_value=([], {})), mock.patch.object(
                monitor, "check_server_parser_state", return_value=server_state
            ), mock.patch.object(monitor, "notify", side_effect=notify):
                self.assertEqual(monitor.run(self.args(state_file)), 0)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["last_server_recovery_at"], server_state["last_recovery_at"])
            self.assertIn("自动恢复", messages[0])
            self.assertIn("手动", messages[0])

    def test_short_incident_sends_separate_failure_and_recovery_notices(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text(json.dumps({"alerted": False}), encoding="utf-8")
            messages: list[str] = []

            def notify(_recipient, message, _key):
                messages.append(message)
                return {"ok": True, "sequence": len(messages)}

            server_state = {
                "healthy": True,
                "last_incident_at": "2026-11-05T03:10:00+08:00",
                "last_recovery_at": "2026-11-05T03:10:17+08:00",
            }
            with mock.patch.object(monitor, "check_public", return_value=([], {})), mock.patch.object(
                monitor, "check_server_parser_state", return_value=server_state
            ), mock.patch.object(monitor, "notify", side_effect=notify):
                self.assertEqual(monitor.run(self.args(state_file)), 0)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(len(messages), 2)
            self.assertIn("解析异常", messages[0])
            self.assertIn("自动恢复", messages[1])
            self.assertIn("手动", messages[1])
            self.assertEqual(state["last_server_incident_at"], server_state["last_incident_at"])
            self.assertEqual(state["last_server_recovery_at"], server_state["last_recovery_at"])

    def test_site_recovery_notice_also_consumes_server_recovery_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text(json.dumps({"alerted": True, "consecutive_failures": 2}), encoding="utf-8")
            messages: list[str] = []

            def notify(_recipient, message, _key):
                messages.append(message)
                return {"ok": True}

            server_state = {
                "healthy": True,
                "last_incident_at": "2026-11-05T03:20:00+08:00",
                "last_recovery_at": "2026-11-05T03:20:17+08:00",
            }
            with mock.patch.object(monitor, "check_public", return_value=([], {})), mock.patch.object(
                monitor, "check_server_parser_state", return_value=server_state
            ), mock.patch.object(monitor, "notify", side_effect=notify):
                self.assertEqual(monitor.run(self.args(state_file)), 0)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(len(messages), 2)
            self.assertIn("解析异常", messages[0])
            self.assertIn("官网恢复", messages[1])
            self.assertEqual(state["last_server_recovery_at"], server_state["last_recovery_at"])


if __name__ == "__main__":
    unittest.main()
