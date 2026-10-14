#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run as root'; exit 1; }
[[ -r /etc/siyumenghai-xhs/cloud.env ]] || { echo 'Provision /etc/siyumenghai-xhs/cloud.env first'; exit 1; }
ROOT=/opt/siyumenghai-xhs-cloud
NODE_BIN=${NODE_BIN:-$(command -v node || true)}
[[ -n $NODE_BIN && -x $NODE_BIN ]] || { echo 'Set NODE_BIN to an existing Node.js >=22 binary'; exit 1; }
getent passwd siyumenghai-xhs >/dev/null || useradd --system --home /nonexistent --shell /usr/sbin/nologin siyumenghai-xhs
install -d -m 755 "$ROOT/runtime"
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install -r requirements.lock
install -m 644 engine.py gateway.mjs browser_parser.mjs browser_author.mjs "$ROOT/"
install -m 755 "$NODE_BIN" "$ROOT/runtime/node"
chown root:siyumenghai-xhs /etc/siyumenghai-xhs/cloud.env
chmod 640 /etc/siyumenghai-xhs/cloud.env
if [[ -f /etc/siyumenghai-xhs/cookie.txt ]]; then
  chown root:siyumenghai-xhs /etc/siyumenghai-xhs/cookie.txt
  chmod 640 /etc/siyumenghai-xhs/cookie.txt
fi
install -m 644 ./*.service /etc/systemd/system/
systemctl daemon-reload
# The browser worker shares only its own persistent profile. No Mac relay required.
[[ -x /usr/bin/google-chrome ]] || { echo "Google Chrome is required for browser fallback"; exit 1; }
install -d -o siyumenghai-xhs -g siyumenghai-xhs -m 700 /var/lib/siyumenghai-xhs-browser
# SQLite parse-cache lives here; the engine unit grants ReadWritePaths on it.
install -d -o siyumenghai-xhs -g siyumenghai-xhs -m 700 /var/lib/siyumenghai-xhs-engine
systemctl enable --now siyumenghai-xhs-browser
systemctl enable --now siyumenghai-xhs-engine siyumenghai-xhs-gateway
# Back up and validate Nginx separately before reload.
