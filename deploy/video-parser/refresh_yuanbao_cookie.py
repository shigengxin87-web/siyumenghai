#!/usr/bin/env python3
"""Refresh the private Yuanbao cookie from the server-local Chrome profile."""

import json
import os
import sys
from pathlib import Path

import requests
import websocket
import yaml


CDP_URL = "http://127.0.0.1:9222/json/list"
YUANBAO_URL = "https://yuanbao.tencent.com/"


def cdp_call(websocket_url, method, params=None):
    client = websocket.create_connection(websocket_url, timeout=10, suppress_origin=True)
    try:
        client.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            message = json.loads(client.recv())
            if message.get("id") == 1:
                if message.get("error"):
                    raise RuntimeError(message["error"].get("message", "CDP request failed"))
                return message.get("result", {})
    finally:
        client.close()


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: refresh_yuanbao_cookie.py CONFIG_PATH")

    config_path = Path(sys.argv[1])
    pages = requests.get(CDP_URL, timeout=5).json()
    page = next(
        (item for item in pages if item.get("type") == "page" and "yuanbao.tencent.com" in item.get("url", "")),
        None,
    )
    if not page:
        raise SystemExit("Yuanbao is not open in the server browser")

    result = cdp_call(
        page["webSocketDebuggerUrl"],
        "Network.getCookies",
        {"urls": [YUANBAO_URL]},
    )
    cookies = result.get("cookies", [])
    cookie = "; ".join(f"{item['name']}={item['value']}" for item in cookies if item.get("name"))
    if not cookie:
        raise SystemExit("Yuanbao login cookie is unavailable")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config.setdefault("cloudflare", {})["sphCookie"] = cookie
    temporary = config_path.with_suffix(".tmp")
    temporary.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(config_path)


if __name__ == "__main__":
    main()
