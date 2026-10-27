#!/usr/bin/env bash
# ====================================================================
# 石董会 · Dify 全量自部署脚本（在腾讯云服务器本机执行，一次性）
# --------------------------------------------------------------------
# 设计目标：拿到服务器口令 + 两个模型 Key 后，一条命令跑完整个迁移，
#           期间不依赖浏览器、不需要人工点界面。
#
# 前置条件：
#   1) 本仓库已 clone 到服务器（含 deploy/dify/migration/）
#   2) 已执行 setup-dify.sh，Dify 运行在 127.0.0.1:8080 且健康
#   3) 依赖：curl、jq、openssl（服务器一般自带）
#
# 用法（在服务器上）：
#   sudo -E bash bootstrap-dify.sh
# 必填环境变量：
#   DEEPSEEK_KEY   DeepSeek 对话模型 Key（https://platform.deepseek.com）
#   ZHIPU_KEY      智谱 Embedding 模型 Key（https://open.bigmodel.cn）
# 可选环境变量：
#   ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_NAME   Dify 管理员（默认已给临时值）
#   DIFY_BASE / MIGRATION_DIR / AGENT_PROXY_CONFIG
# ====================================================================

set -euo pipefail

DIFY_BASE="${DIFY_BASE:-http://127.0.0.1:8080}"
MIGRATION_DIR="${MIGRATION_DIR:-/opt/stone-release/deploy/dify/migration}"
AGENT_PROXY_CONFIG="${AGENT_PROXY_CONFIG:-/opt/siyumenghai-agent-proxy/config.json}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@shidonghui.com}"
ADMIN_NAME="${ADMIN_NAME:-石董会}"
# 临时强口令，部署完成后请务必在 Dify 控制台修改
ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)}"
APP_NAME="${APP_NAME:-石董会运营实战顾问}"

: "${DEEPSEEK_KEY:?缺少 DEEPSEEK_KEY（DeepSeek 对话模型 Key）}"
: "${ZHIPU_KEY:?缺少 ZHIPU_KEY（智谱 Embedding 模型 Key）}"

LOG(){ echo -e "\033[32m[石董会-Dify]\033[0m $*"; }
WARN(){ echo -e "\033[33m[石董会-Dify]\033[0m $*"; }
ERR(){ echo -e "\033[31m[石董会-Dify]\033[0m $*" >&2; }

command -v curl >/dev/null || ERR "需要 curl"; command -v jq >/dev/null || ERR "需要 jq（apt install jq / yum install jq）"

COOKIE_JAR=$(mktemp)
TOKEN=""
WS_ID=""

# ---------- 等待 Dify 健康 ----------
wait_health(){
  LOG "等待 Dify 健康（${DIFY_BASE}）…"
  for i in $(seq 1 60); do
    if curl -fsS "${DIFY_BASE}/health" >/dev/null 2>&1 || \
       curl -fsS "${DIFY_BASE}/console/api/setup" >/dev/null 2>&1; then
      LOG "Dify 已就绪"; return 0
    fi
    sleep 5
  done
  ERR "等待 Dify 超时，请确认 setup-dify.sh 已成功执行且容器在运行"
}

# ---------- 通用 API 调用（带 token） ----------
api(){
  local method="$1" path="$2"; shift 2
  local args=("-sS" "-H" "Authorization: Bearer ${TOKEN}" "-H" "Content-Type: application/json")
  [[ -n "$WS_ID" ]] && args+=("-H" "Workspace-Id: ${WS_ID}")
  curl "${args[@]}" -X "$method" "${DIFY_BASE}${path}" "$@"
}

# ---------- 1. 管理员初始化 / 登录 ----------
bootstrap_admin(){
  # 先探测是否已完成初始化
  local setup_status
  setup_status=$(curl -fsS "${DIFY_BASE}/console/api/setup" 2>/dev/null | jq -r '.data.exist ?? "true"' 2>/dev/null || echo "true")
  if [[ "$setup_status" != "true" ]]; then
    LOG "首次初始化管理员账号…"
    curl -sS -c "$COOKIE_JAR" -X POST "${DIFY_BASE}/console/api/setup" \
      -H "Content-Type: application/json" \
      -d "$(jq -n --arg n "$ADMIN_NAME" --arg e "$ADMIN_EMAIL" --arg p "$ADMIN_PASSWORD" \
            '{name:$n, email:$e, password:$p}')" >/dev/null
    LOG "管理员已创建：${ADMIN_EMAIL}（请尽快修改口令）"
  else
    LOG "管理员已存在，直接登录"
  fi
  # 登录拿 token
  local resp
  resp=$(curl -sS -c "$COOKIE_JAR" -X POST "${DIFY_BASE}/console/api/login" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg e "$ADMIN_EMAIL" --arg p "$ADMIN_PASSWORD" \
          '{email:$e, password:$p, language:"zh-Hans", remember_me:true}')")
  TOKEN=$(echo "$resp" | jq -r '.data.access_token // empty')
  [[ -n "$TOKEN" ]] || { ERR "登录失败，检查 ADMIN_EMAIL/ADMIN_PASSWORD"; echo "$resp" >&2; exit 1; }
  LOG "已获取管理员 token"
  WS_ID=$(api GET "/console/api/workspaces/current" | jq -r '.data.id // empty')
  [[ -n "$WS_ID" ]] || WARN "未取得 workspace id，部分接口可能需手动指定"
}

# ---------- 2. 配置模型供应商（对话 + Embedding） ----------
configure_models(){
  LOG "配置模型供应商：DeepSeek（对话） / 智谱（Embedding）"
  # DeepSeek
  api POST "/console/api/workspaces/current/model-providers/deepseek/credentials" \
    -d "$(jq -n --arg k "$DEEPSEEK_KEY" '{credentials:{DEEPSEEK_API_KEY:$k}, load_balancing:{}}')" \
    >/dev/null 2>&1 && LOG "DeepSeek 已配置" || WARN "DeepSeek 自动配置失败，请到 设置→模型供应商 手动填入 Key"
  # 智谱（ZhipuAI）Embedding
  api POST "/console/api/workspaces/current/model-providers/zhipuai/credentials" \
    -d "$(jq -n --arg k "$ZHIPU_KEY" '{credentials:{ZHIPUAI_API_KEY:$k}, load_balancing:{}}')" \
    >/dev/null 2>&1 && LOG "智谱 已配置" || WARN "智谱 自动配置失败，请到 设置→模型供应商 手动填入 Key"
}

# ---------- 3. 创建知识库并上传 128 案例 ----------
create_kb(){
  LOG "创建知识库「${APP_NAME}知识库」…"
  local ds
  ds=$(api POST "/console/api/datasets" -d "$(jq -n \
        --arg n "${APP_NAME}知识库" \
        '{name:$n, permission:"only_me", data_source_type:"upload_file",
          indexing_technique:"high_quality", embedding_model:"zhipuai/text_embedding_3",
          embedding_model_provider:"zhipuai", retrieval_model:{
            search_method:"semantic_search", reranking_enable:false,
            top_k:4, score_threshold_enabled:false, score_threshold:0.5}}')")
  DATASET_ID=$(echo "$ds" | jq -r '.id // empty')
  [[ -n "$DATASET_ID" ]] || { ERR "知识库创建失败"; echo "$ds" >&2; exit 1; }
  LOG "知识库 ID: ${DATASET_ID}"

  LOG "上传 128 案例（来自 ${MIGRATION_DIR}/cases）…"
  local ok=0 fail=0
  for f in "$MIGRATION_DIR"/cases/*.md; do
    [[ -f "$f" ]] || continue
    local name; name=$(basename "$f" .md)
    local r
    r=$(api POST "/console/api/datasets/${DATASET_ID}/documents" \
        -F "data=$(jq -n --arg n "$name" '{original_document_id:"'"$name"'", indexing_type:"high_quality", doc_form:"text_model", doc_language:"zh"}' | jq -c .)" \
        -F "file=@${f}") || true
    if echo "$r" | jq -e '.id or .document.id or (.data.id)' >/dev/null 2>&1; then ok=$((ok+1)); else fail=$((fail+1)); WARN "上传失败：$name"; fi
  done
  LOG "案例上传完成：成功 ${ok} / 失败 ${fail}"
  if [[ $fail -gt 0 ]]; then WARN "有失败项，可在 Dify 知识库界面手动补传"; fi
}

# ---------- 4. 创建聊天助手应用并接入知识库 ----------
create_app(){
  LOG "创建聊天助手「${APP_NAME}」…"
  local app
  app=$(api POST "/console/api/apps" -d "$(jq -n --arg n "$APP_NAME" \
        '{name:$n, mode:"chat", description:"石董会 AI 问答 · 基于 128 案例知识库"}')")
  APP_ID=$(echo "$app" | jq -r '.id // empty')
  [[ -n "$APP_ID" ]] || { ERR "应用创建失败"; echo "$app" >&2; exit 1; }
  LOG "应用 ID: ${APP_ID}"

  # 读取系统提示词（含 {{#context#}}）与欢迎语
  local sp="$MIGRATION_DIR/SYSTEM_PROMPT.md"
  local prompt; prompt=$(cat "$sp" 2>/dev/null || echo "你是石董会运营实战顾问。")
  local welcome; welcome=$(head -c 200 "$MIGRATION_DIR/WELCOME_EXAMPLES.md" 2>/dev/null || echo "你好，我是石董会 AI 问答。")

  # 配置模型 + 提示词 + 知识库检索（retrieval 节点）
  api POST "/console/api/apps/${APP_ID}/model-config" -d "$(jq -n \
      --arg p "$prompt" --arg w "$welcome" --arg ds "$DATASET_ID" \
      '{
        pre_prompt:$p,
        opening_statement:$w,
        model:{provider:"deepseek", name:"deepseek-chat", mode:"chat", completion_params:{temperature:0.7, top_p:0.8}},
        dataset_configs:{retrieval_model:"single", datasets:[{id:$ds, name:"石董会知识库"}]},
        prompt_type:"simple"
      }') >/dev/null 2>&1 && LOG "应用模型与提示词已配置" || WARN "应用配置自动写入失败，请在 Dify 应用编排界面手动粘贴 SYSTEM_PROMPT.md 并接入知识库"

  # 发布
  api POST "/console/api/apps/${APP_ID}/publish" -d '{}' >/dev/null 2>&1 && LOG "应用已发布" || WARN "发布失败，请在界面点发布"

  # 取 API Key
  local key_resp; key_resp=$(api POST "/console/api/apps/${APP_ID}/api-keys" -d '{}')
  DIFY_API_KEY=$(echo "$key_resp" | jq -r '.id // .data.id // empty')
  [[ -n "$DIFY_API_KEY" ]] || { ERR "未取得 API Key"; echo "$key_resp" >&2; exit 1; }
  LOG "Dify API Key: ${DIFY_API_KEY}"
}

# ---------- 5. 写入 agent-proxy 并重启 ----------
patch_agent_proxy(){
  [[ -f "$AGENT_PROXY_CONFIG" ]] || { ERR "找不到 agent-proxy 配置：$AGENT_PROXY_CONFIG"; exit 1; }
  LOG "将 Dify Key 写入 agent-proxy 配置…"
  local tmp; tmp=$(mktemp)
  jq --arg k "$DIFY_API_KEY" --arg b "$DIFY_BASE" \
     '.difyApiKey=$k | .difyBaseUrl=$b | .upstream="dify"' "$AGENT_PROXY_CONFIG" > "$tmp" \
     && mv "$tmp" "$AGENT_PROXY_CONFIG" || { ERR "写入 agent-proxy 配置失败"; exit 1; }
  LOG "重启 agent-proxy 服务…"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart siyumenghai-agent-proxy && LOG "agent-proxy 已重启" || WARN "systemctl 重启失败，请手动重启"
  else
    WARN "未找到 systemctl，请手动重启 siyumenghai-agent-proxy"
  fi
}

# ---------- 主流程 ----------
main(){
  wait_health
  bootstrap_admin
  configure_models
  create_kb
  create_app
  patch_agent_proxy
  LOG "✅ 全部完成。石董会 AI 问答已切到自建 Dify（${DIFY_BASE}）。"
  LOG "管理员账号：${ADMIN_EMAIL} / 临时口令：${ADMIN_PASSWORD}（请尽快修改）"
  LOG "Dify API Key：${DIFY_API_KEY}"
  rm -f "$COOKIE_JAR"
}
main "$@"
