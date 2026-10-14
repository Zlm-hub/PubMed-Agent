#!/bin/sh
# 服务器端一键备份：把运行期数据库打成 tar.gz 并轮转。
#
#   sh deploy/backup.sh              # 保留默认 7 份
#   KEEP=14 sh deploy/backup.sh      # 保留 14 份
#   OUT=/mnt/nas/pa sh deploy/backup.sh   # 备份到另一块盘/挂载点（推荐，防灾）
#
# 定时（已装在 root crontab，每天 03:00）：
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

run_backup() {
  if [ -n "$OUT" ]; then
    "$PY" deploy/backup.py --keep "$KEEP" --out "$OUT"
  else
    "$PY" deploy/backup.py --keep "$KEEP"
  fi
}

# 备份失败要**立刻告警**，而不是等巡检发现「备份 36 小时没更新」。
# backup.py 只在真出错时返回非零（缺库 / integrity_check 不过 / 归档写不出），
# 所以这里不会误报。
CODE=0
run_backup || CODE=$?

if [ "$CODE" -ne 0 ]; then
  echo "!! 备份失败（退出码 $CODE），详见 deploy/logs/backup.log" >&2
  if [ -f deploy/alert.sh ]; then
    sh deploy/alert.sh "数据库备份失败（退出码 $CODE）——详见 deploy/logs/backup.log" || true
  fi
fi

exit "$CODE"
