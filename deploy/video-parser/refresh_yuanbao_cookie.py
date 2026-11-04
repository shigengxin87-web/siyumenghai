#!/usr/bin/env python3
"""Refresh the private Yuanbao cookie from the server-local Chrome profile."""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
import websocket
import yaml


CDP_BASE = "http://127.0.0.1:9222"
CDP_URL = f"{CDP_BASE}/json/list"
YUANBAO_URL = "https://yuanbao.tencent.com/"
PAGE_WAIT_SECONDS = 25


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


def yuanbao_page():
    pages = requests.get(CDP_URL, timeout=5).json()
    return next(
        (item for item in pages if item.get("type") == "page" and "yuanbao.tencent.com" in item.get("url", "")),
        None,
    )


def ensure_yuanbao_page():
    page = yuanbao_page()
    if page:
        return page, False

    target_url = f"{CDP_BASE}/json/new?{quote(YUANBAO_URL, safe='')}"
    response = requests.put(target_url, timeout=10)
    response.raise_for_status()

    deadline = time.monotonic() + PAGE_WAIT_SECONDS
    while time.monotonic() < deadline:
        page = yuanbao_page()
        if page:
            return page, True
        time.sleep(0.5)
    raise RuntimeError("Yuanbao page did not become ready after automatic creation")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: refresh_yuanbao_cookie.py CONFIG_PATH")

    config_path = Path(sys.argv[1])
    page, page_created = ensure_yuanbao_page()

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
    print(json.dumps({"status": "cookie_refreshed", "page_created": page_created, "cookie_count": len(cookies)}))


if __name__ == "__main__":
    main()
