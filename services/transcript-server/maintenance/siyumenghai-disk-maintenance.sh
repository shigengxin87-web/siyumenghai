#!/usr/bin/env bash
set -euo pipefail

DATA_DIR=/var/lib/siyumenghai-transcriber
CHROME_PROFILE=/root/.openclaw/browser-existing-session
SOFT_FREE_BYTES=$((10 * 1024 * 1024 * 1024))

before=$(df --output=avail -B1 / | tail -n 1 | tr -d ' ')

find "$DATA_DIR/jobs" -xdev -type f -mmin +2880 -delete
find "$DATA_DIR/cache" -xdev -type f -mmin +10080 -delete
find "$DATA_DIR/tmp" -xdev -type f -mmin +1440 -delete
find "$DATA_DIR/tmp" -xdev -depth -type d -empty -mmin +1440 -delete
journalctl --vacuum-size=200M >/dev/null

free_now=$(df --output=avail -B1 / | tail -n 1 | tr -d ' ')
if (( free_now < SOFT_FREE_BYTES )) && systemctl is-active --quiet lighthouse-chromium.service; then
  systemctl stop lighthouse-chromium.service
  for relative in \
    "Default/Cache" \
    "Default/Code Cache" \
    "Default/GPUCache" \
    "Default/Media Cache" \
    "Default/Service Worker/CacheStorage" \
    "GrShaderCache" \
    "ShaderCache" \
    "DawnCache"; do
    target="$CHROME_PROFILE/$relative"
    resolved=$(readlink -m "$target")
    case "$resolved" in
      "$CHROME_PROFILE"/*)
        if [[ -d "$resolved" ]]; then
          find "$resolved" -xdev -mindepth 1 -delete
        fi
        ;;
      *)
        logger -t siyumenghai-disk-maintenance "refused unsafe cache path"
        ;;
    esac
  done
  systemctl start lighthouse-chromium.service
fi

after=$(df --output=avail -B1 / | tail -n 1 | tr -d ' ')
logger -t siyumenghai-disk-maintenance "free_before=$before free_after=$after"
