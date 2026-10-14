#!/bin/sh
# 服务器端一键备份：把运行期数据库打成 tar.gz 并轮转。
#
#   sh deploy/backup.sh              # 保留默认 7 份
#   KEEP=14 sh deploy/backup.sh      # 保留 14 份
#   OUT=/mnt/nas/pa sh deploy/backup.sh   # 备份到另一块盘/挂载点（推荐，防灾）
#
# 建议加进 crontab（每天 03:00，日志追加到 deploy/logs/backup.log）：
#   0 3 * * * cd /home/admin/project/pubmed-analytics && sh deploy/backup.sh >> deploy/logs/backup.log 2>&1
#
# 恢复：见 deploy/README.md「备份与恢复」一节（停容器 → 解包回 deploy/data → 起容器）。
set -e

cd "$(dirname "$0")/.."
KEEP="${KEEP:-7}"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "!! 找不到 python3/python —— 备份脚本需要它（sqlite3 在线备份 API）" >&2
  exit 2
fi

if [ -n "$OUT" ]; then
  exec "$PY" deploy/backup.py --keep "$KEEP" --out "$OUT"
fi
exec "$PY" deploy/backup.py --keep "$KEEP"
