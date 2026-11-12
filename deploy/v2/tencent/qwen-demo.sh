#!/usr/bin/env bash
# Isolated synthetic demo only. The systemd credential is read into process memory.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$repo"
: "${DS_V2_DB_NAME:?}"
: "${DS_V2_FILE_STORAGE_ROOT:?}"
: "${DS_V2_PYTHON:?}"
: "${DS_V2_ALLOWED_ORIGINS:?}"
: "${CREDENTIALS_DIRECTORY:?}"
[ "$(id -u)" -ne 0 ] || exit 1
key="$(cat "$CREDENTIALS_DIRECTORY/dashscope")"
[[ "$key" == sk-* && "$key" != *[[:space:]]* ]] || exit 1
export DS_V2_EMBEDDING_API_KEY="$key" DS_V2_RERANK_API_KEY="$key" DS_V2_GENERATION_API_KEY="$key"
unset key
export DS_V2_ENVIRONMENT=production DS_V2_ALLOW_INSECURE_LOOPBACK=false
export DS_V2_EMBEDDING_PROVIDER=dashscope DS_V2_EMBEDDING_CLOUD_ENABLED=true
export DS_V2_EMBEDDING_MODEL=qwen3.7-text-embedding DS_V2_EMBEDDING_MODEL_REVISION=singapore-demo-v1
export DS_V2_RERANK_PROVIDER=qwen DS_V2_RERANK_CLOUD_ENABLED=true DS_V2_RERANK_MODEL_VERIFIED=true DS_V2_RERANK_MODEL=qwen3-rerank
export DS_V2_GENERATION_PROVIDER=qwen DS_V2_GENERATION_CLOUD_ENABLED=true DS_V2_GENERATION_MODEL_VERIFIED=true DS_V2_GENERATION_MODEL=qwen3.8-flash
export DS_V2_GENERATION_VALIDATION_RETRIES=1
host='https://trial.ap-southeast-1.maas.aliyuncs.com'
export DS_V2_EMBEDDING_ENDPOINT="$host/api/v1/services/embeddings/text-embedding/text-embedding"
export DS_V2_RERANK_ENDPOINT="$host/api/v1/services/rerank/text-rerank/text-rerank"
export DS_V2_GENERATION_ENDPOINT="$host/compatible-mode/v1/chat/completions"
export DS_V2_PARSER_BACKEND=docker XDG_RUNTIME_DIR="/run/user/$(id -u)"
export PATH="$repo/deploy/v2/tencent/bin:$PATH"
case "${1:-}" in
 api) exec "$DS_V2_PYTHON" -m uvicorn backend.v2.main:create_app --factory --host 127.0.0.1 --port 18001 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log ;;
 parser) exec "$DS_V2_PYTHON" -m backend.v2.worker ;;
 embedding) exec "$DS_V2_PYTHON" -m backend.v2.embedding_worker ;;
 *) exit 2 ;;
esac
