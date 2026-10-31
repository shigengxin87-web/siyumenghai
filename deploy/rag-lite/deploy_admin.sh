#!/bin/bash
set -e

DIR=/opt/siyumenghai-rag-lite
VENV=$DIR/venv

echo "== 1. 安装文件 =="
cp /tmp/app.py /tmp/admin.py /tmp/requirements.txt $DIR/
cp /tmp/siyumenghai-rag-admin.service /etc/systemd/system/
chmod 644 $DIR/admin.py

echo "== 2. 安装依赖 =="
$VENV/bin/pip install -q python-multipart pypdf python-docx
$VENV/bin/python -c "import multipart, pypdf, docx; print('deps ok')"

echo "== 3. 配置环境变量 =="
if ! grep -q "^ADMIN_PASSWORD=" $DIR/env; then
  PW=$(python3 -c "import secrets,string;print('sdh-'+''.join(secrets.choice(string.ascii_lowercase+string.digits) for _ in range(10)))")
  SEC=$(python3 -c "import secrets;print(secrets.token_hex(16))")
  echo "ADMIN_PASSWORD=$PW" >> $DIR/env
  echo "SESSION_SECRET=$SEC" >> $DIR/env
fi
for kv in "DEEPSEEK_MODEL=deepseek-chat" "TEMPERATURE=0.3" "MAX_TOKENS=1500"; do
  k=${kv%%=*}
  grep -q "^$k=" $DIR/env || echo "$kv" >> $DIR/env
done
chmod 600 $DIR/env

echo "== 4. 启动管理台 =="
systemctl daemon-reload
systemctl enable --now siyumenghai-rag-admin
sleep 4
echo -n "admin service: "; systemctl is-active siyumenghai-rag-admin
echo -n "admin health: "; curl -s http://127.0.0.1:8090/health || true
echo
echo -n "rag-lite health: "; curl -s http://127.0.0.1:8080/health || true
echo
echo "== 5. 管理密码 =="
grep "^ADMIN_PASSWORD=" $DIR/env
