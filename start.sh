#!/usr/bin/env bash
# 一键启动后端(8000) + 前端(5173)。用法：bash start.sh （Git Bash / WSL）
set -e
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "启动后端 http://127.0.0.1:8000 ..."
( cd "$root/backend" && conda run --no-capture-output -n packaging \
    uvicorn app.main:app --port 8000 --reload ) &
backend_pid=$!

echo "启动前端 http://localhost:5173 ..."
if [ ! -d "$root/frontend/node_modules" ]; then
  ( cd "$root/frontend" && npm install )
fi
( cd "$root/frontend" && npm run dev ) &
frontend_pid=$!

# Ctrl+C 时一并关闭两个进程
trap 'kill $backend_pid $frontend_pid 2>/dev/null' INT TERM
wait
