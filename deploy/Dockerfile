# syntax=docker/dockerfile:1
#
# PubMed Analytics —— 单端口镜像
#   阶段 1 用 Node 构建前端静态产物；阶段 2 用 Python 跑 FastAPI，
#   由 FastAPI 同时托管前端页面与 /api（同源，无需额外 web 服务器 / 反向代理）。
#
# 构建（在仓库根目录执行）：
#     docker build -f deploy/Dockerfile -t pubmed-analytics:latest .
#
# 注意：构建上下文是**仓库根目录**，因为镜像需要 backend/ 与 frontend/ 两棵子树。

# ---------------- 阶段 1：构建前端 ----------------
FROM node:22-alpine AS web
WORKDIR /web
# 先只拷依赖清单，让 npm ci 这层可缓存
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# 生产构建不注入 VITE_API_BASE → 前端 API 基址为空串，走同源 /api
RUN npm run build

# ---------------- 阶段 2：运行后端 ----------------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./
# 国内服务器直连 PyPI 常慢/抖动。默认走阿里云镜像并加重试；
# 海外机器可覆盖：--build-arg PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
RUN pip install --no-cache-dir --retries 5 --timeout 60 \
        --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY backend/ ./
COPY --from=web /web/dist ./web_dist

# 只把「只读参考库」留作种子（期刊指标），运行时库（文献 / 会话）不打包——
# 那是本机历史数据，容器里首次启动会按 schema 新建，避免把本地记录带进生产。
RUN mkdir -p /opt/seed/data \
 && for f in /app/data/journal_metrics.db /app/data/journal_metrics.json; do \
        [ -e "$f" ] && cp -f "$f" /opt/seed/data/ || true; \
    done \
 && rm -f /app/data/literature.db /app/data/literature.db-wal /app/data/literature.db-shm \
          /app/data/sessions.db   /app/data/sessions.db-wal   /app/data/sessions.db-shm

COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV FRONTEND_DIST=/app/web_dist \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
