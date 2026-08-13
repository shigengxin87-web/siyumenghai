#!/usr/bin/env python3
"""Atomically swap the current and previous accepted Siyumenghai releases."""

from __future__ import annotations

import json
import os
from pathlib import Path


RELEASES = Path("/var/www/releases/siyumenghai")
CURRENT = RELEASES / "current"
PREVIOUS = RELEASES / "previous"
STATE = Path("/home/site-deploy/.siyumenghai-main-sha")
REQUIRED = ("member-view/index.html", "member-view/app.js", "member-view/members.json")


def atomic_link(link: Path, target: Path) -> None:
    temporary = link.with_name(f".{link.name}.next-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def validate(root: Path) -> dict:
    for relative in REQUIRED:
        if not (root / relative).is_file():
            raise RuntimeError(f"rollback target missing {relative}")
    members = json.loads((root / "member-view/members.json").read_text(encoding="utf-8"))
    if members.get("count") != len(members.get("members", [])):
        raise RuntimeError("rollback target members.json mismatch")
    try:
        return json.loads((root / ".deploy-manifest.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"commit": "legacy-release"}


def main() -> None:
    if not CURRENT.is_symlink() or not PREVIOUS.is_symlink():
        raise SystemExit("current/previous release link is missing")
    current = CURRENT.resolve(strict=True)
    previous = PREVIOUS.resolve(strict=True)
    manifest = validate(previous)
    atomic_link(CURRENT, previous)
    atomic_link(PREVIOUS, current)
    state_tmp = STATE.with_suffix(".tmp")
    state_tmp.write_text(str(manifest.get("commit", "")) + "\n", encoding="utf-8")
    os.replace(state_tmp, STATE)
    print(json.dumps({"status": "rolled_back", "current": str(previous), "previous": str(current), **manifest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
