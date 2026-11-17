#!/usr/bin/env bash
# Use from an activated V2 Python environment; never source secrets from other projects.
# Usage: DS_V2_QA_ORIGIN=https://host.trycloudflare.com bash deploy/v2/qa/run-secure-test-provider.sh api|parser|embedding|migrate|check
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"
action="${1:-}"
if [[ ! "${DS_V2_QA_ORIGIN:-}" =~ ^https://[A-Za-z0-9.-]+\.(ts\.net|trycloudflare\.com)$ ]]; then
  echo "Set DS_V2_QA_ORIGIN to your exact HTTPS private QA hostname (*.ts.net or *.trycloudflare.com)" >&2
  exit 2
fi
export DS_V2_ENVIRONMENT=development
export DS_V2_ALLOW_INSECURE_LOOPBACK=false
export DS_V2_ALLOWED_ORIGINS="[\"$DS_V2_QA_ORIGIN\"]"
export DS_V2_DB_NAME="${DS_V2_QA_DB_NAME:-ds_assistant_v2_qa}"
export DS_V2_FILE_STORAGE_ROOT="${DS_V2_QA_STORAGE_ROOT:-$HOME/.local/share/ds-assistant-v2/qa/files}"
mkdir -p "$DS_V2_FILE_STORAGE_ROOT"
chmod 700 "$DS_V2_FILE_STORAGE_ROOT"
for purpose in EMBEDDING RERANK GENERATION; do
  export "DS_V2_${purpose}_PROVIDER=deterministic"
  export "DS_V2_${purpose}_ALLOW_TEST_PROVIDER=true"
  export "DS_V2_${purpose}_CLOUD_ENABLED=false"
done
case "$action" in
  api)
    exec python -m uvicorn backend.v2.main:create_app --factory --host 127.0.0.1 --port 8001 \
      --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
    ;;
  parser) exec python -m backend.v2.worker ;;
  embedding) exec python -m backend.v2.embedding_worker ;;
  migrate) exec python -m alembic -c backend/v2/alembic.ini upgrade head ;;
  check) exec python -m alembic -c backend/v2/alembic.ini check ;;
  *)
    echo "Usage: DS_V2_QA_ORIGIN=https://host.trycloudflare.com bash $0 api|parser|embedding|migrate|check" >&2
    exit 2
    ;;
esac
