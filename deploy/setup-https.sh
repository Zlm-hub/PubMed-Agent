#!/bin/sh
# 一键落地「子域名 + HTTPS」（幂等、可重复执行；DNS 未就绪会安全退出，不改任何配置）
#
#   DOMAIN=pubmed.tangchaolizi.xyz EMAIL=you@example.com sh deploy/setup-https.sh
#
# 它会做四件事：
#   1) 预检：DNS 是否已把子域名解析到本机（不满足直接退出，不动服务器）
#   2) 装 certbot（已装则跳过）
#   3) 把 deploy/nginx-pubmed.conf 装到 /etc/nginx/conf.d/ 并 reload（此步只有 80 段生效）
#   4) certbot --nginx 签发证书 + 自动续期，然后验证 https 首页与 /api/health
#
# 不影响宿主机上已有的站点：本配置用独立 server_name，旧站（tangchaolizi.xyz）继续走它自己的
# server 块；nginx 按 server_name 分流，且旧站没用 default_server，所以不存在抢占。
#
# 证书签发后还需要你决定（脚本会提示，不自动改）：
#   只走 https → 把 deploy/.env 的 ACCESS_COOKIE_SECURE 置 1 并重建容器
#   仍保留 http 直连 → 保持 0（否则 http 下 cookie 存不住，用户会反复被弹回登录页）
set -e

cd "$(dirname "$0")/.."

DOMAIN="${DOMAIN:-pubmed.tangchaolizi.xyz}"
EXPECT_IP="${EXPECT_IP:-101.37.23.175}"
EMAIL="${EMAIL:-}"
CONF_SRC="deploy/nginx-pubmed.conf"
CONF_DST="/etc/nginx/conf.d/pubmed.conf"

echo "==> 目标域名: $DOMAIN（期望解析到 $EXPECT_IP）"

# ---------- 0) 需要 root ----------
if [ "$(id -u)" != "0" ]; then
  echo "!! 需要 root（要写 /etc/nginx 并调用 certbot）。请用 sudo 或 root 执行。" >&2
  exit 2
fi

# ---------- 1) DNS 预检 ----------
RESOLVED="$(getent hosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -n 1)"
if [ -z "$RESOLVED" ]; then
  echo "!! DNS 还没解析：$DOMAIN 查不到记录。" >&2
  echo "   请先在域名商添加：A 记录  主机记录 pubmed  值 $EXPECT_IP，等生效后再跑本脚本。" >&2
  exit 3
fi
if [ "$RESOLVED" != "$EXPECT_IP" ]; then
  echo "!! DNS 指向 $RESOLVED，与期望的 $EXPECT_IP 不一致 —— 先核对解析记录。" >&2
  exit 3
fi
echo "    DNS OK：$DOMAIN → $RESOLVED"

# ---------- 2) certbot ----------
if command -v certbot >/dev/null 2>&1; then
  echo "==> certbot 已安装：$(certbot --version 2>&1)"
else
  echo "==> 安装 certbot（python3-certbot-nginx）"
  apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q certbot python3-certbot-nginx
fi

# ---------- 3) 装 nginx 配置并 reload ----------
[ -f "$CONF_SRC" ] || { echo "!! 找不到 $CONF_SRC" >&2; exit 4; }
if [ -f "$CONF_DST" ] && cmp -s "$CONF_SRC" "$CONF_DST"; then
  echo "==> nginx 配置未变，跳过复制"
else
  cp "$CONF_SRC" "$CONF_DST"
  echo "==> 已写入 $CONF_DST"
fi
nginx -t
systemctl reload nginx
echo "    nginx 已 reload（此刻 80 段生效：301 跳转 + ACME 挑战目录）"

# ---------- 4) 签发证书 ----------
if [ -n "$EMAIL" ]; then
  MAILARG="-m $EMAIL"
else
  MAILARG="--register-unsafely-without-email"
  echo "    （未提供 EMAIL，用 --register-unsafely-without-email；建议下次带上邮箱以便证书到期提醒）"
fi

certbot --nginx -d "$DOMAIN" --agree-tos $MAILARG --redirect --non-interactive --keep-until-expiring

# ---------- 5) 验证 ----------
echo "==> 验证"
systemctl reload nginx
curl -sk -o /dev/null -w "    首页        → %{http_code}\n" "https://$DOMAIN/" || true
curl -sk -o /dev/null -w "    /api/health → %{http_code}\n" "https://$DOMAIN/api/health" || true
curl -sk -o /dev/null -w "    http 跳转   → %{http_code}（期望 301）\n" "http://$DOMAIN/" || true
echo "==> 续期演练（certbot renew --dry-run，只看最后一行）"
certbot renew --dry-run 2>&1 | tail -n 1

cat <<TIP

==> 完成。接下来需要你决定一件事（脚本不自动改，避免误伤既有访问方式）：

  · 只走 https：把 deploy/.env 里 ACCESS_COOKIE_SECURE 改成 1，然后
        cd /home/admin/project/pubmed-analytics/deploy && docker compose up -d --force-recreate app
  · 仍保留 http://IP:8000 直连：保持 ACCESS_COOKIE_SECURE=0
    （secure=1 的 cookie 在 http 下不会被保存，用户会被反复弹回登录页）

  另外建议：https 起来后可把阿里云防火墙的 8000 端口关掉，只留 80/443，
  避免有人绕过 https 走明文端口（宿主机 nginx 与容器都不需要改）。
TIP
