#!/usr/bin/env bash
# Run as root from this checked-out directory. Credentials are provisioned separately.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run as root'; exit 1; }
[[ -r /etc/siyumenghai-douyin/cloud.env && -r /etc/siyumenghai-douyin/cookies.yaml ]] || { echo 'Provision private environment and cookies first'; exit 1; }
ROOT=/opt/siyumenghai-douyin-cloud
PIN=473c90ff70c663cfb69310fff2b8d5192f200661
NODE_BIN=${NODE_BIN:-$(command -v node || true)}
[[ -n $NODE_BIN && -x $NODE_BIN ]] || { echo 'Set NODE_BIN to an existing Node.js >=22 binary'; exit 1; }
getent passwd siyumenghai-douyin >/dev/null || useradd --system --home /nonexistent --shell /usr/sbin/nologin siyumenghai-douyin
install -d -m 755 "$ROOT/runtime" "$ROOT/vendor"
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install -r requirements.lock
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
git clone --quiet https://github.com/JoeanAmier/TikTokDownloader.git "$STAGE/douk"
git -C "$STAGE/douk" checkout --quiet "$PIN"
cp -R "$STAGE/douk/src" "$ROOT/vendor/"
install -m 644 "$STAGE/douk/LICENSE" "$ROOT/vendor/LICENSE"
install -m 644 engine.py gateway.mjs "$ROOT/"
install -m 755 "$NODE_BIN" "$ROOT/runtime/node"
chown root:siyumenghai-douyin /etc/siyumenghai-douyin/{cloud.env,cookies.yaml}
chmod 640 /etc/siyumenghai-douyin/{cloud.env,cookies.yaml}
install -m 644 ./*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now siyumenghai-douyin-engine siyumenghai-douyin-gateway
# Nginx routing changes must be separately backed up, checked with nginx -t, then reloaded.
