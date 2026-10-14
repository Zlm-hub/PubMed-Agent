#!/bin/sh
# 发送一条告警到群机器人（企业微信 / 钉钉 / 飞书），并在本地留痕。
#
#   sh deploy/alert.sh "服务不可用：/api/health 深检失败"
#
# 配置（写在 deploy/.env 里，改完立即生效，不需要重启容器）：
#   ALERT_WEBHOOK=     机器人 webhook URL（**留空 = 只写本地日志、不外发**，便于先观察再接入）
#   ALERT_FORMAT=      wecom（默认）/ dingtalk / feishu —— 三家 payload 结构不同，这里做适配
#
# 设计说明：
#   - 不用 `. deploy/.env` 直接 source：.env 里的值可能含空格、`#`、`&`（如 URL 查询串），
#     source 会把它当 shell 代码执行/截断。这里只按 KEY= 精确取值，稳。
#   - 无论发不发得出去，都会往 deploy/logs/alert.log 追加一行（留痕比送达更重要）。
set -e

cd "$(dirname "$0")/.."

read_env() {
  # shellcheck disable=SC2002
  grep -E "^$1=" deploy/.env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r'
}

MSG="$*"
[ -n "$MSG" ] || { echo "用法: sh deploy/alert.sh \"告警内容\"" >&2; exit 2; }

WEBHOOK="$(read_env ALERT_WEBHOOK)"
FORMAT="$(read_env ALERT_FORMAT)"
[ -n "$FORMAT" ] || FORMAT=wecom

HOST="$(hostname 2>/dev/null || echo unknown)"
TEXT="[PubMed Agent] ${MSG}
主机: ${HOST}
时间: $(date '+%Y-%m-%d %H:%M:%S')"

mkdir -p deploy/logs
echo "$(date '+%Y-%m-%d %H:%M:%S') | $MSG" >> deploy/logs/alert.log

if [ -z "$WEBHOOK" ]; then
  echo "（未配置 ALERT_WEBHOOK，仅记录到 deploy/logs/alert.log）"
  exit 0
fi

case "$FORMAT" in
  feishu)   PAYLOAD=$(printf '{"msg_type":"text","content":{"text":"%s"}}' "$(printf '%s' "$TEXT" | sed ':a;N;$!ba;s/\n/\\n/g')") ;;
  dingtalk) PAYLOAD=$(printf '{"msgtype":"text","text":{"content":"%s"}}' "$(printf '%s' "$TEXT" | sed ':a;N;$!ba;s/\n/\\n/g')") ;;
  *)        PAYLOAD=$(printf '{"msgtype":"text","text":{"content":"%s"}}' "$(printf '%s' "$TEXT" | sed ':a;N;$!ba;s/\n/\\n/g')") ;;
esac

# 推送失败不应该让调用方（如备份脚本）跟着失败：这里只记录返回码
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST \
  -H 'Content-Type: application/json' -d "$PAYLOAD" "$WEBHOOK" || echo 000)
echo "$(date '+%Y-%m-%d %H:%M:%S') | webhook 返回 $HTTP_CODE | $MSG" >> deploy/logs/alert.log
if [ "$HTTP_CODE" != "200" ]; then
  echo "!! 告警推送失败（HTTP $HTTP_CODE），已留在 deploy/logs/alert.log" >&2
fi
