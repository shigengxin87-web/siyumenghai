#!/usr/bin/env bash
# ====================================================================
# 石董会 · Dify 开源自建一键部署脚本
# --------------------------------------------------------------------
# 设计要点（结合石董会现有服务器环境）：
#   1. Dify 开源版（Apache-2.0），部署在腾讯云服务器本机，完全免费
#   2. 端口锁死在 127.0.0.1:8080 —— 只监听本机，公网访问不到
#      （80/443 已被石董会主站 Nginx 占用，Dify 不能再用 80）
#   3. 不配域名、不配 SSL、不暴露公网，因此不存在被扫描/被抢注风险
#   4. 模型 Key 存在 Dify 自己的环境里，石董会的 agent-proxy 只持
#      有 Dify 的 API Key，分层隔离
#   5. agent-proxy 通过内网 http://127.0.0.1:8080 调用 Dify
#
# 前置条件：服务器已装 docker 与 docker compose
# 执行： sudo bash setup-dify.sh
# ====================================================================

set -euo pipefail

DIFY_DIR="/opt/dify"
DIFY_PORT="8080"
LOG_PREFIX="[石董会-Dify]"

log()  { echo -e "\033[32m${LOG_PREFIX}\033[0m $1"; }
warn() { echo -e "\033[33m${LOG_PREFIX}\033[0m $1"; }
err()  { echo -e "\033[31m${LOG_PREFIX}\033[0m $1"; exit 1; }

# ---------- 1. 依赖检查 ----------
command -v docker >/dev/null 2>&1 || err "未检测到 docker，请先在服务器安装 Docker"
docker compose version >/dev/null 2>&1 || docker-compose --version >/dev/null 2>&1 \
  || err "未检测到 docker compose，请先安装"

# ---------- 2. 工具函数 ----------
gen() { openssl rand -base64 32 | tr -d '/+=' | head -c 32; }

# 在 .env 里设置/追加一个 KEY=VALUE（跨平台，awk 实现，避免 sed -i 在 BSD 上静默失败）
set_env_var() {
  local file="$1" key="$2" val="$3"
  if grep -qE "^${key}=" "$file" 2>/dev/null; then
    awk -v k="$key" -v v="$val" 'BEGIN{FS="=";OFS="="} $1==k{print k,v;next} {print}' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
  else
    echo "${key}=${val}" >> "$file"
  fi
}

# ---------- 3. 克隆 Dify 开源版 ----------
if [ ! -d "$DIFY_DIR" ]; then
  log "克隆 Dify 开源版到 ${DIFY_DIR} …"
  git clone --depth 1 https://github.com/langgenius/dify.git "$DIFY_DIR" \
    || err "克隆失败，请检查服务器网络（或手动 git clone 到 ${DIFY_DIR}）"
else
  log "Dify 目录已存在，跳过克隆"
fi

cd "$DIFY_DIR/docker"

# ---------- 4. 生成 .env ----------
if [ ! -f .env ]; then
  cp .env.example .env
  log ".env 已生成"
else
  warn ".env 已存在，保留现有配置（仅补充缺失项）"
fi

# ---------- 5. 随机强口令，替换默认公开值 ----------
log "生成随机口令，替换 Dify 默认公开密码 …"
PG_PASS="$(gen)"; REDIS_PASS="$(gen)"; SECRET="$(openssl rand -base64 42 | tr -d '\n')"
set_env_var .env POSTGRES_PASSWORD   "$PG_PASS"
set_env_var .env REDIS_PASSWORD      "$REDIS_PASS"
set_env_var .env SECRET_KEY          "$SECRET"
set_env_var .env SANDBOX_API_KEY    "$(gen)"
set_env_var .env WEAVIATE_API_KEY   "$(gen)"
set_env_var .env PLUGIN_DAEMON_API_KEY "$(gen)"
set_env_var .env INNER_API_KEY_SECRETS  "$(gen)"
set_env_var .env CELERY_BROKER_URL  "redis://:${REDIS_PASS}@redis:6379/1"
# 插件调试端口收回本机，避免 0.0.0.0 暴露
set_env_var .env EXPOSE_PLUGIN_DEBUGGING_PORT "127.0.0.1:5003"

# ---------- 6. 端口锁死本机 8080 ----------
log "将 Dify 端口锁定为 127.0.0.1:${DIFY_PORT}（仅内网） …"
set_env_var .env EXPOSE_NGINX_PORT "$DIFY_PORT"

COMPOSE_FILE="$(ls docker-compose.y*ml 2>/dev/null | head -1)"
if [ -n "$COMPOSE_FILE" ]; then
  # 把 nginx 暴露端口绑定到本机，防止公网访问
  if grep -q 'EXPOSE_NGINX_PORT:-80' "$COMPOSE_FILE"; then
    sed -i.bak -E "s|\"\\\$\{EXPOSE_NGINX_PORT:-80\}:\\\$\{NGINX_PORT:-80\}\"|\"127.0.0.1:\${EXPOSE_NGINX_PORT:-80}:\${NGINX_PORT:-80}\"|g" "$COMPOSE_FILE"
    log "已修改 ${COMPOSE_FILE} 端口绑定为 127.0.0.1"
  else
    warn "未识别到标准端口配置行，请手动编辑 ${COMPOSE_FILE}，把 nginx 的 ports 改为 \"127.0.0.1:${DIFY_PORT}:80\""
  fi
else
  warn "未找到 docker-compose 文件，请确认克隆完整"
fi

# ---------- 7. 口令备份 ----------
cp .env /opt/dify-creds-backup.env 2>/dev/null && chmod 600 /opt/dify-creds-backup.env
log "口令备份至 /opt/dify-creds-backup.env（权限 600）"

# ---------- 8. 启动 ----------
warn "启动 Dify（首次拉取镜像较慢，约 5–15 分钟，请耐心等待） …"
docker compose up -d

# ---------- 9. 健康检查 ----------
log "等待 Dify 就绪 …"
READY=0
for i in $(seq 1 36); do
  if curl -sf "http://127.0.0.1:${DIFY_PORT}/health" >/dev/null 2>&1; then READY=1; break; fi
  sleep 5
done

echo ""
echo "=============================================="
if [ "$READY" = "1" ]; then
  log "Dify 部署完成，健康检查通过"
else
  warn "健康检查超时，可能仍在拉镜像或启动中，请稍后用 docker ps 确认"
fi
echo "=============================================="
echo ""
echo "  接下来访问控制台（必须用 SSH 隧道，因为只监听本机）："
echo "    本机终端执行：  ssh -L ${DIFY_PORT}:127.0.0.1:${DIFY_PORT} 你的服务器用户@服务器IP"
echo "    然后浏览器打开：http://127.0.0.1:${DIFY_PORT}/install"
echo ""
echo "  ⚠️  第一时间注册管理员账号！虽然只监听本机，仍须在 /install 被别人抢注前完成。"
echo "  详细控制台配置步骤见 deploy/dify/README.md"
echo ""
echo "  配置完成后，把 Dify 的 API Key 填进 /opt/siyumenghai-agent-proxy/config.json 的 difyApiKey，"
echo "  再执行：sudo systemctl restart siyumenghai-agent-proxy"
