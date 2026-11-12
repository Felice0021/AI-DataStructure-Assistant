#!/usr/bin/env bash
# Installed root-owned outside the checkout; invoked only by a forced SSH command.
set -Eeuo pipefail
umask 077
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
readonly base=/opt/ds-v2-qa
readonly repo=https://github.com/Felice0021/AI-DataStructure-Assistant.git
readonly branch=refs/heads/deploy/qwen-demo
readonly node_bin=/home/ubuntu/.local/opt/node-v24.22.0-linux-x64/bin
readonly api=https://api.github.com/repos/Felice0021/AI-DataStructure-Assistant
test "$(id -u)" -eq 0
test -f /etc/ds-v2-qa/qwen-ci-enabled
test -z "${SSH_ORIGINAL_COMMAND:-}"
IFS= read -r commit
[[ "$commit" =~ ^[a-f0-9]{40}$ ]]
if IFS= read -r extra; then echo 'unexpected input' >&2; exit 1; fi
exec 9>/run/lock/ds-v2-qwen-deploy.lock
flock -n 9 || { echo 'deployment already running' >&2; exit 1; }
old=$(readlink -f "$base/qwen-demo")
case "$old" in "$base"/releases/qa-qwen-*) ;; *) echo 'unexpected current release' >&2; exit 1;; esac

# The key alone cannot bypass the test gates; refuse stale commits and missing checks.
scratch=$(mktemp -d /tmp/ds-qwen-ci.XXXXXXXX)
git -C "$scratch" init -q
git -C "$scratch" fetch -q --depth=1 "$repo" "$branch"
test "$(git -C "$scratch" rev-parse FETCH_HEAD)" = "$commit"
curl --fail --silent --show-error --max-time 20 -H 'Accept: application/vnd.github+json' \
  -H 'User-Agent: ds-v2-qwen-deploy' "$api/commits/$commit/check-runs?filter=latest&per_page=100" > "$scratch/checks.json"
/usr/bin/python3 - "$scratch/checks.json" <<'PY'
import json,sys
data=json.load(open(sys.argv[1]))
for name in ('V2 backend tests','V2 frontend tests and build','V2 macOS parser isolation'):
    items=[x for x in data.get('check_runs',[]) if x.get('name')==name and (x.get('app') or {}).get('slug')=='github-actions']
    if len(items)!=1 or items[0].get('status')!='completed' or items[0].get('conclusion')!='success':
        raise SystemExit('required CI check missing or unsuccessful')
PY
release=$(mktemp -d "$base/releases/qa-qwen-$commit.XXXXXXXX")
git -C "$scratch" archive FETCH_HEAD | tar -x -C "$release"

# Migrations, dependencies and the isolated parser image require separate review.
cmp "$old/backend/v2/requirements.txt" "$release/backend/v2/requirements.txt"
for f in deploy/v2/parser.Dockerfile deploy/v2/tencent/qwen-demo.sh deploy/v2/tencent/bin/docker \
  backend/v2/parser_child.py backend/v2/core/errors.py \
  backend/v2/services/chunking.py backend/v2/services/file_validation.py backend/v2/services/text_extraction.py; do
  cmp "$old/$f" "$release/$f"
done
/usr/bin/python3 - "$old" "$release" <<'PY'
import hashlib,sys
from pathlib import Path
def versions(root):
    p=Path(root)/'backend/v2/migrations/versions'
    return {x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in p.glob('*.py')}
if versions(sys.argv[1])!=versions(sys.argv[2]):raise SystemExit('migration changes require manual review')
PY
test -x "$node_bin/node"
id qwen-build >/dev/null
chown -R qwen-build:qwen-build "$release"
runuser -u qwen-build -- env HOME=/var/lib/qwen-build PATH="$node_bin:/usr/bin:/bin" \
  npm --prefix "$release/frontend-v2" ci --no-audit --no-fund
runuser -u qwen-build -- env HOME=/var/lib/qwen-build PATH="$node_bin:/usr/bin:/bin" \
  VITE_REGISTRATION_ENABLED=false VITE_USE_MOCK=false VITE_API_BASE= \
  npm --prefix "$release/frontend-v2" run build
test ! -e "$release/frontend-v2/dist/mockServiceWorker.js"
printf '%s\n' "$commit" > "$release/frontend-v2/dist/deployment-sha.txt"
chown -R root:root "$release"
chmod -R go-w "$release"

rollback() {
  trap - ERR
  ln -s "$old" "$base/.qwen-ci-rollback-$$"
  mv -Tf "$base/.qwen-ci-rollback-$$" "$base/qwen-demo"
  systemctl restart ds-v2-qwen@api ds-v2-qwen@parser ds-v2-qwen@embedding || true
  echo 'release rolled back' >&2
}
trap rollback ERR
ln -s "$release" "$base/.qwen-ci-next-$$"
mv -Tf "$base/.qwen-ci-next-$$" "$base/qwen-demo"
systemctl restart ds-v2-qwen@api ds-v2-qwen@parser ds-v2-qwen@embedding
ready=false
for _ in $(seq 1 20); do
  if systemctl is-active --quiet ds-v2-qwen@api && systemctl is-active --quiet ds-v2-qwen@parser && \
     systemctl is-active --quiet ds-v2-qwen@embedding && curl -fsS --max-time 5 http://127.0.0.1:18001/api/v2/health/db >/dev/null; then
    ready=true; break
  fi
  sleep 1
done
test "$ready" = true
curl -fsS --max-time 20 https://qwen.dsassistant.cn/api/v2/health/db >/dev/null
test "$(curl -fsS --max-time 20 -H 'Cache-Control: no-cache' "https://qwen.dsassistant.cn/deployment-sha.txt?sha=$commit")" = "$commit"
trap - ERR
echo "deployed $commit"
