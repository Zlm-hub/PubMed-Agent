#!/bin/sh
# 本机执行：把当前代码同步到服务器并重启线上服务。
#
#   sh deploy/sync-to-server.sh
#
# 设计要点（都是为了不误伤服务器端状态）：
#   1) **不上传 deploy/.env** —— 那是服务器自己的配置（访问口令、密钥）。
#      上传它会把你改过的口令覆盖回模板值（实测坑）。
#   2) **不上传 deploy/data、deploy/cache、deploy/logs** —— 服务器运行期数据
#      （客户对话、检索记录、缓存），上传会用本机空目录盖掉。
#   3) **不上传 backend/data 下的 literature.db / sessions.db / users.db / auth_secret.key**
#      —— 那是**本机**积累的检索历史、对话与账号（含签名密钥），服务器上用不到
#      （容器读的是挂载的 deploy/data），传上去既浪费体积、也把本地数据摊到服务器磁盘。
#      只传 journal_metrics.*（构建与运行都需要）。
#   4) 不上传 node_modules / .venv / .git / output / 根 .env。
#
# 可用环境变量覆盖：DEPLOY_HOST / DEPLOY_DIR / DEPLOY_OWNER / SKIP_BUILD
set -e

DEPLOY_HOST="${DEPLOY_HOST:-root@101.37.23.175}"
DEPLOY_DIR="${DEPLOY_DIR:-/home/admin/project/pubmed-analytics}"
DEPLOY_OWNER="${DEPLOY_OWNER:-admin:admin}"

cd "$(dirname "$0")/.."
echo "==> 本地仓库: $(pwd)"
echo "==> 目标服务器: $DEPLOY_HOST:$DEPLOY_DIR"

# 前端改了要先构建；没改可设 SKIP_BUILD=1 跳过
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "==> 构建前端（生产：API 基址同源）"
  ( cd frontend && npm run build )
else
  echo "==> 跳过前端构建（SKIP_BUILD=1）"
fi

echo "==> 同步代码（保留服务器上的 .env 与运行期数据）"
tar czf - \
    --exclude='./node_modules' \
    --exclude='./frontend/node_modules' \
    --exclude='./backend/.venv' \
    --exclude='./backend/data/literature.db' \
    --exclude='./backend/data/literature.db-wal' \
    --exclude='./backend/data/literature.db-shm' \
    --exclude='./backend/data/sessions.db' \
    --exclude='./backend/data/sessions.db-wal' \
    --exclude='./backend/data/sessions.db-shm' \
    --exclude='./backend/data/users.db' \
    --exclude='./backend/data/users.db-wal' \
    --exclude='./backend/data/users.db-shm' \
    --exclude='./backend/data/auth_secret.key' \
    --exclude='./.git' \
    --exclude='./output' \
    --exclude='./.env' \
    --exclude='./deploy/.env' \
    --exclude='./deploy/data' \
    --exclude='./deploy/cache' \
    --exclude='./deploy/logs' \
    --exclude='./deploy/certs' \
    . \
  | ssh -o ConnectTimeout=15 "$DEPLOY_HOST" "
      set -e
      mkdir -p '$DEPLOY_DIR'
      tar xzf - -C '$DEPLOY_DIR'
      chown -R '$DEPLOY_OWNER' '$DEPLOY_DIR'
      echo 'SYNC_OK'
    "

echo "==> 在服务器上重建并重启"
ssh -o ConnectTimeout=15 "$DEPLOY_HOST" "cd '$DEPLOY_DIR' && sh deploy/deploy-on-server.sh"

echo ""
echo "==> 完成。线上地址： http://tangchaolizi.xyz:8000  （启动需约 110 秒）"
