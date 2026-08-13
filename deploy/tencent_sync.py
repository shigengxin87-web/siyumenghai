#!/usr/bin/env python3
"""Incremental, verified and atomic Tencent deployment for Siyumenghai."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request


REPO = "shigengxin87-web/siyumenghai"
BRANCH = "main"
API = f"https://api.github.com/repos/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}"
CDN = f"https://cdn.jsdelivr.net/gh/{REPO}"
RELEASES = Path("/var/www/releases/siyumenghai")
CURRENT = RELEASES / "current"
PREVIOUS = RELEASES / "previous"
STATE = Path("/home/site-deploy/.siyumenghai-main-sha")
KEEP_RELEASES = 6
ROOT_PRESERVE = {"index.html", "member-view"}
REQUIRED = (
    "index.html",
    "member-view/index.html",
    "member-view/app.js",
    "member-view/members.json",
    "member-view/video-downloader-20260808-17.html",
    "member-view/video-downloader-app.js",
)
EXCLUDED_PREFIXES = ("member-view/tools/",)
EXCLUDED_SUFFIXES = (
    "member-view/assets/paraformer-zh-small/sherpa-onnx-wasm-main-vad-asr.wasm",
    "member-view/assets/paraformer-zh-small/sherpa-onnx-wasm-main-vad-asr.data",
)
FAILPOINT = os.environ.get("SIYUMENGHAI_FAILPOINT", "")
FORCE = os.environ.get("SIYUMENGHAI_FORCE", "") == "1"


def get_bytes(url: str, attempts: int = 3, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "siyumenghai-tencent-sync/2"})
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed: {url}: {'; '.join(errors)}")


def get_json(url: str) -> dict:
    return json.loads(get_bytes(url, attempts=4, timeout=30).decode("utf-8"))


def get_repo_file(commit: str, path: str) -> bytes:
    if FAILPOINT == "download_timeout":
        raise RuntimeError("injected GitHub large-file timeout")
    errors: list[str] = []
    for url in (f"{CDN}@{commit}/{path}", f"{RAW}/{commit}/{path}"):
        try:
            return get_bytes(url)
        except RuntimeError as error:
            errors.append(str(error))
    raise RuntimeError("; ".join(errors))


def wanted(entry: dict) -> bool:
    path = entry.get("path", "")
    return (
        entry.get("type") == "blob"
        and (path == "index.html" or path.startswith("member-view/"))
        and not any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES)
        and path not in EXCLUDED_SUFFIXES
    )


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def atomic_link(link: Path, target: Path) -> None:
    temporary = link.with_name(f".{link.name}.next-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def current_root() -> Path:
    if CURRENT.is_symlink():
        return CURRENT.resolve(strict=True)
    return Path("/var/www/html").resolve(strict=True)


def validate_release(root: Path, entries: list[dict]) -> dict[str, object]:
    for relative in REQUIRED:
        path = root / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"required file missing: {relative}")

    members = json.loads((root / "member-view/members.json").read_text(encoding="utf-8"))
    if members.get("count") != len(members.get("members", [])) or not members.get("members"):
        raise RuntimeError("members.json count mismatch or empty")

    homepage = (root / "index.html").read_text(encoding="utf-8")
    if "网站升级中" not in homepage or "【石董会】" in homepage or "群聊学习情报" in homepage:
        raise RuntimeError("root homepage is not the reserved holding page")

    node = shutil.which("node")
    if node:
        result = subprocess.run(
            [node, "--check", str(root / "member-view/app.js")],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"app.js syntax failure: {result.stderr[-500:]}")
    elif "const days = {" not in (root / "member-view/app.js").read_text(encoding="utf-8"):
        raise RuntimeError("app.js structure marker missing")

    for entry in entries:
        path = root / entry["path"]
        if not path.is_file() or git_blob_sha(path) != entry["sha"]:
            raise RuntimeError(f"blob integrity mismatch: {entry['path']}")

    return {"members": len(members["members"]), "verified_blobs": len(entries)}


def cleanup_releases() -> None:
    protected = {link.resolve() for link in (CURRENT, PREVIOUS) if link.is_symlink()}
    releases = sorted(
        (path for path in RELEASES.glob("release-*") if path.is_dir() and path not in protected),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old in releases[max(0, KEEP_RELEASES - len(protected)) :]:
        shutil.rmtree(old, ignore_errors=True)


def main() -> None:
    RELEASES.mkdir(parents=True, exist_ok=True)
    commit = get_json(f"{API}/commits/{BRANCH}")["sha"]
    active = current_root()
    manifest_path = active / ".deploy-manifest.json"
    try:
        active_commit = json.loads(manifest_path.read_text(encoding="utf-8")).get("commit")
    except (FileNotFoundError, json.JSONDecodeError):
        active_commit = ""
    if active_commit == commit and not FORCE:
        print(json.dumps({"status": "unchanged", "commit": commit}, ensure_ascii=False))
        return

    tree = get_json(f"{API}/git/trees/{commit}?recursive=1")
    if tree.get("truncated"):
        raise RuntimeError("GitHub tree response was truncated")
    entries = [entry for entry in tree["tree"] if wanted(entry)]
    entry_paths = {entry["path"] for entry in entries}
    if not set(REQUIRED).issubset(entry_paths):
        raise RuntimeError("required website files are missing from GitHub tree")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"release-{stamp}-{commit[:12]}"
    staging = RELEASES / f".{name}.staging-{os.getpid()}"
    release = RELEASES / name
    old_target = active

    try:
        staging.mkdir(parents=True)
        # Copy the accepted local release as the base. Network transfer remains
        # incremental: unchanged Git blobs are reused from this local copy.
        # A normal copy also works with Linux protected_hardlinks enabled.
        shutil.copytree(active, staging, dirs_exist_ok=True, symlinks=True, copy_function=shutil.copy2)
        if FAILPOINT == "download_timeout":
            raise RuntimeError("injected GitHub large-file timeout")

        # The public root now belongs exclusively to Shidonghui. Legacy report,
        # group and learning-intelligence files remain recoverable in previous
        # releases, but must not survive in the active public release.
        for existing in staging.iterdir():
            if existing.name in ROOT_PRESERVE:
                continue
            if existing.is_dir() and not existing.is_symlink():
                shutil.rmtree(existing)
            else:
                existing.unlink(missing_ok=True)

        member_root = staging / "member-view"
        member_root.mkdir(parents=True, exist_ok=True)

        for existing in member_root.rglob("*"):
            if not existing.is_file():
                continue
            full = "member-view/" + existing.relative_to(member_root).as_posix()
            preserved = full in EXCLUDED_SUFFIXES or any(full.startswith(p) for p in EXCLUDED_PREFIXES)
            if full not in entry_paths and not preserved:
                existing.unlink()

        def materialize(entry: dict) -> None:
            target = staging / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file() and git_blob_sha(target) == entry["sha"]:
                return
            target.unlink(missing_ok=True)
            target.write_bytes(get_repo_file(commit, entry["path"]))

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(materialize, entries))

        if FAILPOINT == "bad_release":
            (staging / "member-view/app.js").write_text("syntax error {", encoding="utf-8")
        if FAILPOINT == "after_download":
            raise RuntimeError("injected failure after download")

        verification = validate_release(staging, entries)
        manifest = {
            "commit": commit,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "previous": str(old_target),
            **verification,
        }
        (staging / ".deploy-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if FAILPOINT == "before_switch":
            raise RuntimeError("injected failure before atomic switch")

        os.replace(staging, release)
        atomic_link(PREVIOUS, old_target)
        atomic_link(CURRENT, release)
        try:
            validate_release(CURRENT.resolve(strict=True), entries)
        except Exception:
            atomic_link(CURRENT, old_target)
            raise

        state_tmp = STATE.with_suffix(".tmp")
        state_tmp.write_text(commit + "\n", encoding="utf-8")
        os.replace(state_tmp, STATE)
        cleanup_releases()
        print(json.dumps({"status": "deployed", "release": str(release), **manifest}, ensure_ascii=False))
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    main()
