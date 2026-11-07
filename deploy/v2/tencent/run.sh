#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$repo"
: "${DS_V2_QA_ORIGIN:?Set HTTPS origin}"
export DS_V2_ENVIRONMENT=development DS_V2_ALLOW_INSECURE_LOOPBACK=false
export DS_V2_ALLOWED_ORIGINS="[\"$DS_V2_QA_ORIGIN\"]"
export DS_V2_DB_NAME=ds_assistant_v2_qa
export DS_V2_FILE_STORAGE_ROOT="$HOME/.local/share/ds-assistant-v2/tencent-qa/files"
export DS_V2_PARSER_BACKEND=docker
for purpose in EMBEDDING RERANK GENERATION; do
 export "DS_V2_${purpose}_PROVIDER=deterministic"
 export "DS_V2_${purpose}_ALLOW_TEST_PROVIDER=true"
 export "DS_V2_${purpose}_CLOUD_ENABLED=false"
done
export PATH="$repo/deploy/v2/tencent/bin:$PATH"
python="$HOME/.virtualenvs/ai-datastructure-v2/bin/python"
case "${1:-}" in
 api) exec "$python" -m uvicorn backend.v2.main:create_app --factory --host 127.0.0.1 --port 8001 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log ;;
 parser) exec "$python" -m backend.v2.worker ;;
 embedding) exec "$python" -m backend.v2.embedding_worker ;;
 *) echo 'usage: run.sh api|parser|embedding' >&2; exit 2 ;;
esac
