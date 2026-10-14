#!/bin/sh
# 在**服务器上**执行的一键部署脚本（已针对 2G 内存优化：跳过前端构建阶段）。
#   sh deploy/deploy-on-server.sh
# 前提：代码已同步到服务器（含 backend/data/journal_metrics.db 与 frontend/dist），
#       且 deploy/.env 已配置账号体系（ADMIN_* / AUTH_SECRET / 试用额度等）。
#
# 2026-09-21 起服务器为**纯账号制**（不再用共享访问口令）：首启自动建管理员；
# 访客可自助注册普通账号，每个普通账号默认免费试用 FREE_TRIAL_LIMIT 次。
set -e

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
echo "==> 仓库根目录: $ROOT"

if [ ! -f backend/data/journal_metrics.db ] && [ ! -f backend/data/journal_metrics.json ]; then
  echo "!! 缺少期刊指标库（backend/data/journal_metrics.*）—— 分区 / 影响因子会全部显示「未知」。"
  echo "   请从本机完整工作区重新同步，不要用 git clone。"
  exit 1
fi

if [ ! -f frontend/dist/index.html ]; then
  echo "!! 缺少前端构建产物 frontend/dist —— 用户访问会看到空白页。"
  echo "   请在本机先执行：cd frontend && npm run build"
  exit 1
fi

if [ ! -f deploy/.env ]; then
  echo "!! 缺少 deploy/.env —— 请先 cp deploy/.env.example deploy/.env 并填写密钥。"
  exit 1
fi

# 账号体系自检：没有 ADMIN_* 时，第一个访问者要走「首次使用」入口注册（该账号即管理员）
if ! grep -qE '^ADMIN_USERNAME=.+' deploy/.env; then
  echo "!! 提示：未配置 ADMIN_USERNAME/ADMIN_PASSWORD —— 首个访问者需在登录页"
  echo "   走「首次使用：创建第一个账号」入口（该账号即管理员）。"
fi

echo -n "==> 试用额度: "
grep -E '^FREE_TRIAL_LIMIT=' deploy/.env || echo "(未配置 = 不限制)"
echo -n "==> 管理员联系方式: "
grep -E '^ADMIN_CONTACT=' deploy/.env || echo "(未配置)"
if grep -qE '^ACCESS_CODE=.+' deploy/.env; then
  echo "!! 注意：deploy/.env 仍设置了 ACCESS_CODE —— 服务器已改为账号制，"
  echo "   建议清空（ACCESS_CODE=）以免旧共享口令继续可用。"
fi

SUDO=""
if ! docker info >/dev/null 2>&1; then
  SUDO="sudo"
  echo "==> 当前用户无 docker 权限，改用 sudo"
fi

echo "==> 构建镜像（只装 Python 依赖，不跑前端构建）"
$SUDO docker build -f deploy/Dockerfile.prebuilt -t pubmed-analytics:latest .

echo "==> 启动容器"
cd deploy
$SUDO docker compose up -d --no-build
cd "$ROOT"

echo "==> 等待服务起来（首次启动要把 18MB 期刊指标库载入内存，2 核机器约需 1~2 分钟）"
i=0
while [ $i -lt 180 ]; do
  if curl -s -m 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "    已就绪（等待 ${i}s）"
    break
  fi
  i=$((i + 1))
  if [ $((i % 15)) -eq 0 ]; then echo "    仍在启动… ${i}s"; fi
  sleep 1
done
if [ $i -ge 180 ]; then
  echo "!! 等待超过 180s 仍未就绪。请查看日志排障："
  echo "   cd deploy && $SUDO docker compose logs --tail 50 app"
  exit 1
fi

echo "==> 自检"
echo -n "   /api/health                 → "; curl -s -m 5 http://127.0.0.1:8000/api/health || echo "(无响应)"
echo
echo -n "   /api/demo/presets 未登录     → 期望 401，实际 "
curl -s -m 5 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/demo/presets
echo -n "   /api/auth（鉴权模式）        → "
curl -s -m 5 http://127.0.0.1:8000/api/auth | head -c 160
echo
echo -n "   / 首页                      → 期望 200，实际 "
curl -s -m 5 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/

echo ""
echo "==> 完成。浏览器访问： http://<服务器公网IP>:8000   或   http://tangchaolizi.xyz:8000"
echo "    登录方式：管理员账号登录（管理后台建号）；访客可在登录页自助注册，"
echo "             普通账号免费试用 ${FREE_TRIAL_HINT:-N} 次，用尽后提示联系管理员。"
echo "    查看日志： cd deploy && $SUDO docker compose logs -f app"
