#!/bin/sh
# 巡检脚本：健康深检 + 错误日志突增 + 备份新鲜度，异常时推送到群机器人。
#
#   sh deploy/monitor.sh          # 建议 crontab：*/5 * * * *
#
# 三项检查（每项都带「去抖」：只在状态变化时推送，避免每 5 分钟刷屏）：
#   1. 健康深检 —— curl /api/health?deep=1（会真的开库），非 200/超时即异常；
#   2. 错误日志突增 —— 最近窗口内 error.log 的 ERROR 行数超过阈值即异常；
#   3. 备份新鲜度 —— 最新备份超过 N 小时未更新即异常（crontab 挂了 / 备份连续失败）。
#
# 配置（deploy/.env，均可留空用默认）：
#   MONITOR_HEALTH_URL=http://127.0.0.1:8000/api/health?deep=1
#   MONITOR_ERROR_WINDOW_MIN=15     检查窗口（分钟）
#   MONITOR_ERROR_THRESHOLD=5       窗口内 ERROR 行数阈值
#   MONITOR_BACKUP_MAX_HOURS=36     备份最大未更新时长
#   ALERT_WEBHOOK / ALERT_FORMAT    见 deploy/alert.sh
#
# 状态文件 deploy/logs/.monitor-state 记录上一次各检查的结论，用于去抖。
set -e

cd "$(dirname "$0")/.."
mkdir -p deploy/logs
STATE=deploy/logs/.monitor-state
[ -f "$STATE" ] || : > "$STATE"

read_env() {
  grep -E "^$1=" deploy/.env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r'
}
state_get() { grep -E "^$1=" "$STATE" 2>/dev/null | tail -n 1 | cut -d= -f2- || true; }
state_set() {
  # 就地更新一个键（保持文件短小）
  tmp="${STATE}.tmp"
  grep -vE "^$1=" "$STATE" 2>/dev/null > "$tmp" || : > "$tmp"
  echo "$1=$2" >> "$tmp"
  mv "$tmp" "$STATE"
}

HEALTH_URL="$(read_env MONITOR_HEALTH_URL)"
[ -n "$HEALTH_URL" ] || HEALTH_URL="http://127.0.0.1:8000/api/health?deep=1"
WINDOW="$(read_env MONITOR_ERROR_WINDOW_MIN)"; [ -n "$WINDOW" ] || WINDOW=15
THRESHOLD="$(read_env MONITOR_ERROR_THRESHOLD)"; [ -n "$THRESHOLD" ] || THRESHOLD=5
MAX_HOURS="$(read_env MONITOR_BACKUP_MAX_HOURS)"; [ -n "$MAX_HOURS" ] || MAX_HOURS=36

echo "[$(date '+%F %T')] monitor start"

# ---------- 1) 健康深检 ----------
# 注意：curl 连接失败时自己也会把 %{http_code} 打成 000，所以不能再 `|| echo 000`
# （那样会拼成 000000，我第一次就这么踩了）。这里只在**取空**时兜底。
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$HEALTH_URL" 2>/dev/null) || true
[ -n "$CODE" ] || CODE=000
if [ "$CODE" = "200" ]; then HEALTH_NOW=ok; else HEALTH_NOW=fail; fi
echo "  health: $CODE ($HEALTH_NOW)"
if [ "$HEALTH_NOW" != "$(state_get health)" ]; then
  if [ "$HEALTH_NOW" = "fail" ]; then
    ERRTAIL="$(tail -n 3 deploy/logs/error.log 2>/dev/null | tr '\n' ' ' | cut -c1-300)"
    sh deploy/alert.sh "服务健康检查失败（HTTP $CODE）：$HEALTH_URL${ERRTAIL:+  最近错误: $ERRTAIL}"
  else
    sh deploy/alert.sh "服务已恢复：健康深检 HTTP 200"
  fi
  state_set health "$HEALTH_NOW"
fi

# ---------- 2) 错误日志突增 ----------
ERRL=deploy/logs/error.log
if [ -f "$ERRL" ]; then
  # 只数窗口内的 ERROR 行（日志格式 `%Y-%m-%d %H:%M:%S | LEVEL | ...`，按时间戳前缀比较）
  SINCE=$(date -d "-${WINDOW} minutes" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S')
  COUNT=$(awk -v since="$SINCE" '{ ts=substr($0,1,19); if (ts >= since && $0 ~ / ERROR /) c++ } END { print c+0 }' "$ERRL")
  echo "  errors(last ${WINDOW}m): $COUNT (阈值 $THRESHOLD)"
  if [ "$COUNT" -ge "$THRESHOLD" ] && [ "$(state_get errors_spike)" != "1" ]; then
    TOP="$(grep ' ERROR ' "$ERRL" | tail -n 2 | cut -c1-200 | tr '\n' ' ')"
    sh deploy/alert.sh "错误日志突增：最近 ${WINDOW} 分钟出现 ${COUNT} 条 ERROR（阈值 ${THRESHOLD}）。样例：$TOP"
    state_set errors_spike 1
  elif [ "$COUNT" -lt "$THRESHOLD" ] && [ "$(state_get errors_spike)" = "1" ]; then
    state_set errors_spike 0
  fi
fi

# ---------- 3) 备份新鲜度 ----------
NEWEST=$(ls -t deploy/backups/pa-backup-*.tar.gz 2>/dev/null | head -n 1)
if [ -z "$NEWEST" ]; then
  if [ "$(state_get backup)" != "missing" ]; then
    sh deploy/alert.sh "没有任何备份文件（deploy/backups/ 为空）——请检查定时任务"
    state_set backup missing
  fi
else
  AGE_S=$(( ( $(date +%s) - $(date -r "$NEWEST" +%s) ) / 3600 ))
  echo "  backup: $(basename "$NEWEST") 已 $AGE_S 小时"
  if [ "$AGE_S" -ge "$MAX_HOURS" ]; then
    if [ "$(state_get backup)" != "stale" ]; then
      sh deploy/alert.sh "备份超过 ${MAX_HOURS} 小时未更新（最新：$(basename "$NEWEST")，$AGE_S 小时前）"
      state_set backup stale
    fi
  elif [ "$(state_get backup)" != "ok" ]; then
    state_set backup ok
  fi
fi

echo "[$(date '+%F %T')] monitor done"
