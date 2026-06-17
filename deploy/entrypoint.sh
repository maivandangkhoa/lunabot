#!/usr/bin/env bash
# Bootstrap luna. Container start bằng root để chown volume, rồi drop xuống user 'node'
# (Claude từ chối bypassPermissions nếu chạy root). Port từ entrypoint.sh.
set -euo pipefail

if [ "$(id -u)" = "0" ]; then
  mkdir -p "${WORKSPACE:-/workspace}" /home/node/.claude
  chown -R node:node "${WORKSPACE:-/workspace}" /home/node
  exec gosu node "$0" "$@"
fi

# ----- từ đây chạy với quyền user 'node' -----
: "${GIT_AUTHOR_NAME:=luna bot}"
: "${GIT_AUTHOR_EMAIL:=bot@luna.dev}"

git config --global user.name  "$GIT_AUTHOR_NAME"
git config --global user.email "$GIT_AUTHOR_EMAIL"
git config --global init.defaultBranch main
git config --global --add safe.directory '*'

# Áp migrations trước khi serve (idempotent). Retry vì DB có thể chưa ready ngay
# (depends_on chỉ chờ container start, không chờ Postgres nhận kết nối).
for i in $(seq 1 30); do
  if alembic upgrade head; then
    echo "alembic upgrade OK (lần $i)"
    break
  fi
  echo "DB chưa sẵn sàng, chờ 2s rồi thử lại ($i/30)..." >&2
  sleep 2
done

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
