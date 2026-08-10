#!/usr/bin/env python3
"""Publish the standalone comment cloud from GitHub main as an atomic release."""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import tempfile
import time
import urllib.request


REPO = "shigengxin87-web/siyumenghai"
BRANCH = "main"
PREFIX = "comment-cloud/"
API = f"https://api.github.com/repos/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}"
RELEASES = pathlib.Path("/var/www/releases")
CURRENT = pathlib.Path("/var/www/comment-cloud")
STATE = pathlib.Path("/home/site-deploy/.siyumenghai-comment-cloud-sha")
REQUIRED = {
    "index.html",
    "app.js",
    "styles.css",
    "comments.json",
    "favicon.svg",
    "og.jpg",
    "audio/zhumeng-chizixin.mp3",
}


def get_bytes(url: str, attempts: int = 4) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "siyumenghai-comment-cloud-sync/1"})
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed: {url}: {error}")


def get_json(url: str) -> dict:
    return json.loads(get_bytes(url).decode("utf-8"))


def validate(stage: pathlib.Path) -> None:
    found = {str(path.relative_to(stage)) for path in stage.rglob("*") if path.is_file()}
    missing = REQUIRED - found
    if missing:
        raise RuntimeError(f"required files missing: {sorted(missing)}")

    records = json.loads((stage / "comments.json").read_text(encoding="utf-8"))
    main_count = sum(item.get("类型") == "主评论" for item in records)
    if main_count < 1:
        raise RuntimeError("comments.json has no main comments")

    html = (stage / "index.html").read_text(encoding="utf-8")
    links = re.findall(r'(?:href|src)="([^"]+)"', html)
    forbidden = [link for link in links if link == "/" or link.startswith("/member-view")]
    if forbidden:
        raise RuntimeError(f"standalone page links into the member site: {forbidden}")


def main() -> None:
    commit = get_json(f"{API}/commits/{BRANCH}")["sha"]
    tree = get_json(f"{API}/git/trees/{commit}?recursive=1")
    if tree.get("truncated"):
        raise RuntimeError("GitHub tree response was truncated")
    paths = [
        entry["path"]
        for entry in tree["tree"]
        if entry["type"] == "blob" and entry["path"].startswith(PREFIX)
    ]
    if not paths:
        raise RuntimeError("comment-cloud files are missing from GitHub main")

    release = RELEASES / f"comment-cloud-{commit[:12]}"
    RELEASES.mkdir(parents=True, exist_ok=True)
    if not release.exists():
        stage_root = pathlib.Path(tempfile.mkdtemp(prefix=".comment-cloud-", dir=RELEASES))
        stage = stage_root / "site"
        stage.mkdir()
        try:
            for source_path in paths:
                relative = pathlib.Path(source_path).relative_to(PREFIX)
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(get_bytes(f"{RAW}/{commit}/{source_path}"))
            validate(stage)
            os.replace(stage, release)
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)
    else:
        validate(release)

    if CURRENT.exists() and not CURRENT.is_symlink():
        raise RuntimeError(f"refusing to replace non-symlink path: {CURRENT}")
    next_link = CURRENT.with_name(f".comment-cloud-next-{os.getpid()}")
    next_link.unlink(missing_ok=True)
    next_link.symlink_to(release, target_is_directory=True)
    os.replace(next_link, CURRENT)

    STATE.parent.mkdir(parents=True, exist_ok=True)
    state_tmp = STATE.with_suffix(".tmp")
    state_tmp.write_text(commit + "\n", encoding="utf-8")
    os.replace(state_tmp, STATE)
    print(f"{time.strftime('%F %T')} deployed {commit} -> {release}")


if __name__ == "__main__":
    main()
