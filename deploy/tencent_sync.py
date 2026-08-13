#!/usr/bin/env python3
"""Pull the public member-view tree from GitHub to the Tencent web root."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import urllib.request


REPO = "shigengxin87-web/siyumenghai"
BRANCH = "main"
DEST = pathlib.Path("/var/www/html/member-view")
STATE = pathlib.Path("/home/site-deploy/.siyumenghai-main-sha")
API = f"https://api.github.com/repos/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}"
EXCLUDED_PREFIXES = ("member-view/tools/",)
EXCLUDED_SUFFIXES = (
    "member-view/assets/paraformer-zh-small/sherpa-onnx-wasm-main-vad-asr.wasm",
    "member-view/assets/paraformer-zh-small/sherpa-onnx-wasm-main-vad-asr.data",
)


def get_bytes(url: str, attempts: int = 4) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "siyumenghai-tencent-sync/1"})
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            # Large static assets (for example background audio) can exceed the
            # old 30-second limit when raw.githubusercontent.com is slow in CN.
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except Exception as exc:  # network errors are retried and surfaced afterward
            error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed: {url}: {error}")


def get_json(url: str) -> dict:
    return json.loads(get_bytes(url).decode("utf-8"))


def wanted(path: str, kind: str) -> bool:
    if kind != "blob" or not path.startswith("member-view/"):
        return False
    if any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    return path not in EXCLUDED_SUFFIXES


def git_blob_sha(path: pathlib.Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def main() -> None:
    commit = get_json(f"{API}/commits/{BRANCH}")["sha"]
    if STATE.exists() and STATE.read_text(encoding="utf-8").strip() == commit:
        return

    tree = get_json(f"{API}/git/trees/{commit}?recursive=1")
    if tree.get("truncated"):
        raise RuntimeError("GitHub tree response was truncated")
    entries = [entry for entry in tree["tree"] if wanted(entry["path"], entry["type"])]
    paths = [entry["path"] for entry in entries]
    if "member-view/index.html" not in paths or "member-view/members.json" not in paths:
        raise RuntimeError("required website files are missing from GitHub tree")

    stage_root = pathlib.Path(tempfile.mkdtemp(prefix="siyumenghai-sync-"))
    stage = stage_root / "member-view"

    def download(entry: dict) -> None:
        path = entry["path"]
        relative = pathlib.Path(path).relative_to("member-view")
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        current = DEST / relative
        if current.is_file() and git_blob_sha(current) == entry["sha"]:
            shutil.copy2(current, target)
            return
        target.write_bytes(get_bytes(f"{RAW}/{commit}/{path}"))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(download, entries))

        members = json.loads((stage / "members.json").read_text(encoding="utf-8"))
        if members.get("count") != len(members.get("members", [])):
            raise RuntimeError("members.json count does not match member list")

        DEST.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rsync", "-r", "--checksum", f"{stage}/", f"{DEST}/"], check=True)
        state_tmp = STATE.with_suffix(".tmp")
        state_tmp.write_text(commit + "\n", encoding="utf-8")
        os.replace(state_tmp, STATE)
        print(f"{time.strftime('%F %T')} deployed {commit}")
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


if __name__ == "__main__":
    main()
