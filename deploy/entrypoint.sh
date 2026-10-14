#!/bin/sh
# 容器入口：补齐种子数据 → 启动单端口服务。
set -e

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# 运行时可写目录（可能被挂载为卷：首次启动是空目录）
mkdir -p /app/data /app/cache /app/logs

# 把镜像内的只读种子（期刊指标库）补进 data —— 只在文件不存在时复制，
# 因此不会覆盖容器里已经积累的运行时数据。
if [ -d /opt/seed/data ]; then
  for f in /opt/seed/data/*; do
    [ -e "$f" ] || continue
    b=$(basename "$f")
    [ -e "/app/data/$b" ] || cp "$f" "/app/data/$b"
  done
fi

exec uvicorn app.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}"
