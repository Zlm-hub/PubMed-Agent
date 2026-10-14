# PubMed Agent · 文献分析 Demo（全栈笔试）

> 沿长科技（成都）全栈开发工程师笔试 —— 关键词 → NCBI 检索 → 统计 + 词云 + 影响力排序 + 中文综述 一站式 web。
> 当前状态：**F1–F4 + 对话式外壳 + 用户体系 + 监控日志 + 单端口部署 全部完成**并端到端跑通；架构为**单 LLM**（非 RAG、非多智能体）；指标/文献/会话/账号落 **四个 SQLite 库**（按生命周期分库，见「存储结构」）；**支持中文检索**（本地术语映射 + LLM 改写，渐冻症 → ALS 实测全链路打通）；线上以**单容器单端口**提供服务，按账号登录、每账号免费试用 N 次（管理员可在后台重置）。
> 外层是对话式 Agent 外壳（左导航 + 对话流 + 工具调用可见），内核仍是那条已端到端验证过的固定流水线——**升级只加了一层壳，报告链路一行未改**。

## 界面预览

对话式外壳（左侧导航 + 中间对话流 + 工具调用可见）：

| 欢迎页（快捷开始 + 能力卡） | 对话流（工具卡片 + 结果内联） |
|---|---|
| ![外壳](docs/05-agent-home.png) | ![对话流](docs/06-agent-flow.png) |

「报告」视图（原 F1–F4 完整报告，逻辑未改，只是搬进了独立视图）：

| 概览（检索 + 统计卡 + 中文综述） | 年份分布 / 分区分布 |
|---|---|
| ![总览](docs/01-overview.png) | ![图表](docs/02-charts.png) |

| 词云 + 研究方向标签 | 影响力 Top 100 |
|---|---|
| ![词云](docs/03-wordcloud.png) | ![Top100](docs/04-top100.png) |

## 功能范围（已完成）
- ✅ **对话式外壳**：三栏布局（左导航 / 顶部视图切换 / 主区）、快捷开始、历史会话（服务端落库、按用户隔离）、输入区技能与模型 chips、后端连接状态实时检测
- ✅ **工具调用可见**：每步渲染为一张工具卡片（名称与入参对齐后端真实函数，结果值取自真实响应），思考过程可折叠，结果内联渲染并可跳转完整报告
- ✅ 关键词 → NCBI E-utilities 真实检索（ESearch + EFetch/XML 并发解析）
- ✅ **F1 统计**：命中总量、年份分布（Alzheimer 场景覆盖 1988→2026）、期刊分区分布（Q1–Q4 + 未知）、影响因子统计（均值/中位/极值）、IF 指标覆盖率
- ✅ **F2 可视化**：关键词词云（纯 DOM 渲染，字号∝词频、色阶分档）+ 研究方向标签（MeSH 聚类，纯统计不用 LLM）
- ✅ **F3 排序**：影响因子 Top 100 表格（近 5 年优先，样本不足时按年份就近补足并标注）+ 一键 CSV 导出
- ✅ **F4 综述**：取 Top 摘要 → 中文分点综述（约 500 字），每条论断可溯源 `[PMID: xxxxx]`
- ✅ 设计思考页（含界面升级与工具卡片边界的说明，命中"体现对该工具的思考"加分项）
- ✅ 前端现代 SaaS 风格（浅色卡片化），三栏外壳与原报告视图共用同一套设计 token

## 技术栈
- 后端：Python + FastAPI + httpx（异步并发）+ python-dotenv
- 数据源：NCBI E-utilities（免费，可挂 `NCBI_API_KEY` 提限流）
- 期刊指标：SQLite 库 `data/journal_metrics.db`——**SCImago 2025 全量 32,193 条（含源方已发布分区）+ OpenAlex 2,748 条**双源落库（合计 **34,941 本**），ISSN 索引 **58,867 行**；随包发布的 `journal_metrics.json` 快照为其中的 OpenAlex 部分（**2,748 本 / 5,462 条 ISSN**）；构建期抓取、运行时零联网，缺失降级"未知"（详见「数据来源」）
- 综述 LLM：DashScope qwen（OpenAI 兼容接口），无 key 时按真实统计生成示例综述
- 前端：Vite + React + TypeScript + Tailwind CSS + ECharts（**按需注册**：bar/pie/grid/tooltip/legend）+ 自研 DOM 词云
- 存储：**四个 SQLite 库，按数据生命周期分立**——`journal_metrics.db`（指标，只读随包，34,941 本）/ `literature.db`（文献、命中集、分析快照、术语映射，运行期积累）/ `sessions.db`（会话线程与报告，按 `user_id` 隔离）/ `users.db`（账号、角色、试用次数）；另含进程内存缓存 + 文件预缓存（演示加速用，非业务数据）

## 目录结构
```
pubmed-analytics/
├── backend/
│   ├── app/
│   │   ├── config.py      # 环境变量与配置
│   │   ├── pubmed.py      # NCBI 检索（esearch + efetch 批量 XML 解析）
│   │   ├── journaldb.py   # 期刊指标 SQLite 层（建表/写入/ISSN 索引/溯源 meta）
│   │   ├── literaturedb.py# 文献库 SQLite（检索词/文献/命中集/分析快照/术语映射）
│   │   ├── sessiondb.py   # 会话库 SQLite（线程/消息/报告快照，按 user_id 隔离）
│   │   ├── userdb.py      # 账号库 SQLite（PBKDF2 密码、HMAC 签 token、试用计数）
│   │   ├── monitor.py     # 监控日志（request_id 透传 + 双文件轮转 + 敏感值打码）
│   │   ├── wordzh.py      # 词云/主题词中文化（词典优先，未命中批量机翻落库）
│   │   ├── term_mapping_seed.json # 随包发布的中文术语种子（81 条已审核，首启导入）
│   │   ├── query_translate.py # 中文查询改写（L0 映射表 → L1 LLM → 试搜护栏）
│   │   ├── metrics.py     # 指标加载与刊名/ISSN 归一化匹配（DB 优先，JSON 回落，缺失降级）
│   │   ├── cache.py       # 缓存键（query × max_results × include_review）
│   │   ├── analyze.py     # 聚合：年份/分区/IF/词频/主题/Top100
│   │   ├── review.py      # 中文综述（qwen / 按真实统计生成的示例综述）
│   │   ├── pipeline.py    # 检索→聚合→综述 统一响应体（main 与 precache 共用）
│   │   └── main.py        # FastAPI 入口 + /api/analyze + CORS + 缓存
│   ├── data/journal_metrics.db    # 期刊指标 SQLite（SCImago + OpenAlex 双源，见「数据来源」）
│   ├── data/journal_metrics.json  # OpenAlex 快照（build_metrics_db.py openalex 的导入源）
│   ├── scripts/build_metrics_db.py        # 双源落库 CLI：scimago / openalex / all / stats / verify
│   ├── scripts/build_metrics_openalex.py  # OpenAlex 抓取（两阶段：分页抓取 + 关键词回填）产出 JSON 快照
│   ├── scripts/precache.py                # 演示预缓存生成（PRESETS 跑真实管线写 cache/）
│   ├── scripts/seed_term_mapping.py       # 中文术语映射表预置（81 条，交付期审核固化）
│   ├── scripts/db_report.py               # 四库只读盘点（表/列/索引/行数/文件大小）
│   ├── scripts/warm_wordzh.py             # 词云中文词表预热
│   ├── scripts/test_http_auth.py          # 回归：闸门三模式/登录登出（41 项）
│   ├── scripts/test_user_isolation.py     # 回归：会话/报告用户隔离（26 项）
│   ├── scripts/test_auth_register.py      # 回归：注册开关与首引导（16 项）
│   ├── scripts/test_trial_limit.py        # 回归：免费试用额度（27 项）
│   ├── scripts/migrate_cache_to_db.py     # 旧缓存迁移进 literature.db
│   ├── cache/                             # 演示预缓存（启动自动载入内存）
│   ├── .env.example       # 配置模板
│   ├── requirements.txt
│   └── .venv/             # 已建虚拟环境（阿里云 PyPI 镜像）
├── frontend/
│   ├── src/App.tsx        # 入口：仅挂载外壳
│   ├── src/ReportView.tsx # 「报告」视图 = 原 F1–F4 报告逻辑整体迁移（未改逻辑）
│   ├── src/Thinking.tsx   # 设计思考页
│   ├── src/api.ts         # 调 /api/analyze（类型定义）
│   ├── src/apiBase.ts     # API 基址 + 登录态/口令/试用额度请求封装
│   ├── src/AccessGate.tsx # 登录门（账号 / 口令 / 免鉴权 三模式自适应 + 注册入口）
│   ├── src/AdminPanel.tsx # 管理后台覆盖层（用户管理 / 全部会话 / 重置试用）
│   ├── src/admin.ts       # 管理接口封装
│   ├── src/CitationText.tsx # 综述正文里的 PMID 引用（可点击回原文）
│   ├── src/Pager.tsx      # Top100 表格分页
│   ├── src/EChart.tsx     # ECharts 封装（按需注册 + ResizeObserver 自适应）
│   ├── src/WordCloud.tsx  # 自研纯 DOM 词云（无 canvas 插件依赖）
│   ├── src/agent/         # 对话式外壳（本次新增，自包含，不侵入既有模块）
│   │   ├── AgentShell.tsx # 三栏骨架 + 视图切换 + 会话状态 + 连接检测
│   │   ├── Sidebar.tsx    # 左导航：品牌 / 新对话 / 快捷开始 / 历史 / 配置 / 工作目录
│   │   ├── ChatPanel.tsx  # 对话流 + 输入区 + 工具卡片推进编排
│   │   ├── ToolCard.tsx   # 工具调用卡片（入参可展开）
│   │   └── model.ts       # 数据模型 + 快捷开始定义 + 工具模板 + 会话持久化
│   └── dist/              # 已 build（596 模块 / gzip 237 KB）
├── deploy/                # 部署包：Dockerfile(.prebuilt) / compose / entrypoint / 同步脚本 / nginx 样例
├── docs/                  # 界面截图 + 交付文档 6 份 docx + 2 份专项设计 md
├── .gitignore             # 排除密钥与运行期数据（.env / auth_secret.key / *.db / deploy 运行期卷）
└── .dockerignore          # 构建上下文瘦身（node_modules / .venv / 运行期数据）
```

## 交付文档

除代码外，五份说明文档随仓库一并提供，位于 `docs/`（与界面截图同目录）：

| 文档 | 说明 |
|---|---|
| `docs/需求评审报告.docx` | 逐字引用笔试要求，识别 3 处硬卡点（IF/分区数据源、LLM 综述、PubMed 限流）与 8 个待拍板问题 |
| `docs/竞品调查报告.docx` | 5 款代表性竞品对比（Elicit / Connected Papers / ResearchRabbit / Scholarscope·EasyPubMed / VOSviewer），提炼差异化切入 |
| `docs/开发实施文档.docx` | 架构、模块、接口、实现细节、「规划 vs 实装」差异对照（16 节）+ **v1.1 增补：账号体系 / 试用额度 / 日志 / 部署形态（17 节）** |
| `docs/数据库设计文档.docx` | 数据分层、指标数据集结构、缓存与索引策略（12 节）+ **v1.1 增补：四库结构（指标 / 文献 / 会话 / 账号）与迁移并发策略（13 节）** |
| `docs/演示讲解稿.docx` / `docs/演示流程文档.docx` | 现场讲解脚本与演示动线 |
| `docs/监控日志设计方案.md` / `docs/升级设计方案-数据层与中文检索.md` | 两份专项设计说明 |

## 快速启动

### 1. 后端
```bash
cd backend
cp .env.example .env        # 可选：填 DASHSCOPE_API_KEY 用真实 qwen；留空则按真实统计生成示例综述
.venv/Scripts/pip.exe install -r requirements.txt   # 已装好

# 不配任何 key 也能完整演示（现场推荐）：
MOCK_LLM=1 .venv/Scripts/uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
# 真实 LLM 模式（在 .env 填好 DASHSCOPE_API_KEY）：
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000

# 离线预生成演示缓存（一键演示不翻车；建议演示前在能联网的环境跑一次，约 15 秒）：
MOCK_LLM=1 .venv/Scripts/python.exe scripts/precache.py
# 启动后后端自动从 cache/*.json 载入内存；前端「一键演示」按钮直接命中，断网也能秒回

# 重建期刊指标库（交付包内 .db 已就位，通常无需执行；重建需联网）：
.venv/Scripts/python.exe scripts/build_metrics_db.py all      # SCImago 下载落库 + OpenAlex 快照导入
.venv/Scripts/python.exe scripts/build_metrics_db.py stats    # 查看两源规模、分区分布与溯源 meta
.venv/Scripts/python.exe scripts/build_metrics_db.py verify   # 抽样核对（CA / BMJ / Nature / Science ...）

# 验证：
curl http://127.0.0.1:8000/api/health
curl -X POST http://127.0.0.1:8000/api/analyze -H "Content-Type: application/json" \
  -d "{\"query\":\"Alzheimer\",\"max_results\":200,\"include_review\":true}"
```

### 2. 前端
```bash
cd frontend
npm install            # 已装好（react / echarts 已含）
npm run dev            # 开发服务器 http://127.0.0.1:5173
# 或生产预览：
npm run build && npm run preview
```
> 前端 `api.ts` 直连 `http://localhost:8000`（演示时改 hosts/端口一致即可）。
> API 基址统一在 `src/apiBase.ts`：开发模式自动指向 `http://localhost:8000`，
> 生产构建留空（走同源，供单端口部署用）。
>
> ⚠️ **Vite 端口被占用会自动顺延**：若 5173 已有一个 dev server 在跑，新的会起在
> **5174**。后端 CORS 已放行本机**任意端口**（`allow_origin_regex`），所以换端口
> 也能连上；若出现「前端连不上后端」，先看浏览器控制台是不是 CORS 报错，
> 再确认后端进程还活着（`curl http://127.0.0.1:8000/api/health`）。
> **深链**（现场演示可直接进任意视图）：
> - `/?q=Alzheimer` → 报告视图并自动分析（升级前的既有行为，已保留）
> - `/?chat=Alzheimer` → 对话视图并自动跑一次完整链路
> - `/?tab=design` → 直接进设计思考页

## 配置项（.env）
| 变量 | 说明 | 默认 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 阿里云百炼 qwen key（真实综述） | 空=按统计生成示例 |
| `DASHSCOPE_BASE_URL` | DashScope OpenAI 兼容地址 | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| `LLM_MODEL` | 模型名 | qwen-plus |
| `NCBI_API_KEY` | NCBI E-utilities key（提限流） | 空 |
| `NCBI_TOOL` / `NCBI_EMAIL` | 礼貌参数 | pubmed-analytics |
| `MAX_RESULTS` | 检索上限 | 1000 |
| `REVIEW_TOP_N` | 综述取摘要篇数 | 30 |
| `MOCK_LLM` | 强制走示例综述 | 无 key 自动 true |
| `CACHE_DIR` | 文件预缓存目录 | `backend/cache` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 首启自动创建的管理员（仅 users 表为空时生效） | 空 |
| `AUTH_SECRET` | 登录 token 的 HMAC 签名密钥（未配置则自动生成落盘 `data/auth_secret.key`） | 空 |
| `ALLOW_REGISTRATION` | 是否开放自助注册（注册账号恒为普通用户） | 0 |
| `FREE_TRIAL_LIMIT` | 每个普通账号免费分析次数（0=不限；管理员豁免） | 0 |
| `ADMIN_CONTACT` | 额度用尽时展示的联系方式 | 空 |
| `ACCESS_CODE` | 旧共享口令通道（运维用 `X-Access-Code` 头）；服务器已改纯账号制故留空 | 空 |
| `LOG_DIR` / `LOG_LEVEL` | 监控日志目录与级别（双文件按天轮转） | `backend/logs` / INFO |

## 账号、权限与免费试用额度（v3 新增）

线上形态是**纯账号制**（不再使用共享访问口令）：访客可自助注册，每个普通账号默认免费试用 3 次。

| 维度 | 实现 |
|---|---|
| 账号 | `users.db`；密码 PBKDF2-HMAC-SHA256（10 万轮 + 16 字节随机盐）；用户名查重 `COLLATE NOCASE`（防 `Admin` 冒充 `admin`） |
| 登录态 | HMAC 签名的 token cookie（`pa_session`），无服务端会话表；每次请求解签后**回查用户行**，禁用/删除即时失效 |
| 角色 | `admin` / `user`；自助注册恒为 `user`（请求体里没有 role 字段）；首引导例外：库里零账号时第一个注册者成为管理员 |
| 访问闸门 | 三模式自动切换 `user` / `code` / `open`；未登录访问 `/api/*` 一律 401，拒绝事件也会落日志 |
| 隔离 | 会话按 `user_id` 三向隔离（读/写/删）；每用户各留 12 条历史；报告复用键含 `user_id` |
| 试用额度 | `FREE_TRIAL_LIMIT`（服务器=3）：两个分析接口各算一次、**含缓存命中**（否则换关键词/清缓存即可绕过）；管理员与运维通道豁免；计数存 `users.trial_used`，`BEGIN IMMEDIATE` 原子扣减 |
| 超限提示 | 非流式：403 + 可读文案；**流式端点回 SSE `error` 事件**——`EventSource` 读不到 4xx 响应体，只能走事件通道；文案带 `ADMIN_CONTACT` |
| 管理后台 | 用户管理（建号 / 重置密码 / 禁用 / 删除 / **重置试用次数**）+ 全部会话；服务端同样做自我保护与「最后一名管理员」保护 |

> 诚实边界：额度按账号计，**同一人可注册多个账号绕过**——这是试用漏斗形态的固有边界；要严格限制需再加设备/IP 维度或关闭自助注册。

## 监控日志（v3 新增）

零新依赖（标准库 `logging`），按天轮转双文件：`backend/logs/app.log`（INFO 起，留 14 天）/ `error.log`（ERROR 起，留 30 天）。一次请求用 `request_id` 贯穿全链路（`contextvars` 透传，各模块函数签名零改动），响应体也带该码，客户报障可直接报码回放。

| 事件 | 说明 |
|---|---|
| `auth.gate.denied` | 被闸门拒绝的请求（路径、IP、是否带 cookie、当前模式） |
| `auth.login.ok` / `auth.login.failed` / `auth.code.failed` | 登录成功与失败（用户名、IP、UA 摘要） |
| `auth.register.ok` / `auth.register.failed` / `auth.logout` | 注册与退出审计 |
| `api.access` | 除 health / analyze / stream 外每个 `/api/*` 请求：方法、路径、状态码、耗时、用户名 |
| `trial.consumed` / `trial.limit.reached` | 试用额度扣减与超限 |
| `api.unhandled.error` | 未捕获异常兜底（堆栈落 `error.log`，响应体带 `request_id`） |

排查入口：`GET /api/logs?tail=100`；设计与事件清单见 `docs/监控日志设计方案.md`。

## 部署（单端口 Docker，v3 新增）

单容器单端口：**FastAPI 一个进程**同时托管前端构建产物（`/`）与接口（`/api/*`），无需额外 web 服务器。部署包在 `deploy/`：

| 文件 | 用途 |
|---|---|
| `Dockerfile` | 多阶段（node 构建前端 → python 运行），适合内存充裕的机器 |
| `Dockerfile.prebuilt` | **2 核 2G 小服务器用**：只 `COPY frontend/dist` + 装 pip 依赖（前端在本机构建好），避开 850MB 峰值 OOM |
| `docker-compose.yml` | 单服务编排，`env_file: ./.env`，挂载 `data/cache/logs` |
| `entrypoint.sh` | 首次启动把只读参考库补进挂载卷（只补不覆盖） |
| `sync-to-server.sh` | 本机一条命令：构建前端 → 同步（排除密钥与运行期数据）→ 服务器重建重启 |
| `deploy-on-server.sh` | 服务器端一键：构建镜像 → 起容器 → 等就绪 → 自检 |
| `nginx.conf*` | 可选：绑域名 + HTTPS 时的反代样例（SSE 需关闭缓冲） |
| `README.md` | 部署手册（含踩坑清单与实测记录） |

实测（阿里云轻量 2 核 2G / Ubuntu 24.04）：容器内存约 150MB、启动约 105 秒（载入 18MB 指标库），只占 8000 一个端口，不触碰宿主机已有 nginx。

## 数据来源（期刊 IF / 分区）

PubMed 官方不返回影响因子与分区，因此指标数据集在**构建期**从公开来源抓取、落 SQLite 单文件随包发布，运行时零联网依赖。库文件 `backend/data/journal_metrics.db`（约 18 MB），由 `app/journaldb.py` 提供建表/写入/查询：

| 来源 | 规模 | 说明 |
|---|---|---|
| `scimago`（优先） | 32,193 条（期刊 30,412） | SCImago Journal Rank 2025 全量导出（11.25 MB CSV）。带**源方已发布分区**（SJR Best Quartile：Q1 9,470 / Q2 7,916 / Q3 7,116 / Q4 6,585）、SJR、近 2 年篇均被引，以及期刊类型（剔除非期刊条目）与 Coverage 活跃区间（识别停刊） |
| `openalex`（兜底） | 2,748 条 | OpenAlex sources API 的 `2yr_mean_citedness`，分区为按被引阈值推算；仅当某 ISSN 未被 SCImago 覆盖时才生效 |

关键设计：

- **口径分列、不合并**：两源指标口径不同，分列存放以杜绝"A 源数值配 B 源分区"的静默串味；查询时 SCImago 优先、OpenAlex 只兜底。
- **ISSN 独立索引表**：印刷号 + 电子号拆到 `journal_issn`（两源共 58,867 行），ISSN → 期刊是一次索引命中。
- **刊名归一化匹配**：抹平 PubMed 的 5 种常见写法差异——`括号限定词`（Science (New York, N.Y.)）、`句点`（Nature reviews. Cancer）、`主标题 : 缩写`（Journal of Alzheimer's disease : JAD）、`标题 = 平行标题`、`开头缩写前缀`（JPMA. ...）。
- **同名刊用 `(source, source_id)` 唯一**：SCImago 存在同名不同 Sourceid 的条目（不同学科分类独立计），不能拿刊名当唯一键。
- **溯源可回查**：每个来源的抓取 URL、时间、原始文件 SHA-256、口径说明、许可注记全部落在 `dataset_meta` 表；`scripts/build_metrics_db.py stats` / `verify` 可随时核对。
- **历史脏值已消除**：旧 OpenAlex-only 数据集存在停刊刊 367.0 霸榜、BMJ=0.0 等脏值；SCImago 覆盖后 BMJ=2.95、Nature=18.62、CA=285.55（`verify` 子命令可复现）。残余风险：个别只被 OpenAlex 收录的长尾条目仍可能带出离群值（如 Chem Comm 旧刊号 367.0），三个预设实测 Top100 未受影响。
- **口径注记**：两源的指标本质都是「近 2 年篇均被引」，系统性低于 JCR 影响因子（SCImago 分母含社论/letters 等非可引用项）；UI 沿用「影响因子(IF)」称谓，精确口径以本节与库内 `dataset_meta` 为准。
- 未收录期刊如实降级「未知」，不编造数值；前端概览卡展示 IF 指标覆盖率。
- 重建：`python scripts/build_metrics_db.py all`（SCImago 需联网且需完整浏览器头，OpenAlex 限流期间直接导入磁盘快照即可，免联网）。

## 技术取舍（为什么这么做）
| 决策点 | 选择 | 理由 |
|---|---|---|
| 界面形态 | **网页内做对话式外壳**，不做桌面应用 | 笔试要求是「独立开发一个网页 demo」；桌面壳（Electron）会偏离要求且演示成本更高。参考了科研 Agent 类产品的交互范式，但只取其"过程可见"的内核，形态仍留在浏览器里。 |
| 升级边界 | **只加外壳，不动报告链路** | 报告链路已端到端验证过，为换皮重写它风险与收益不成比例。做法是把原报告逻辑整体迁到 `ReportView.tsx` 作为独立视图，**逻辑一行未改**，对话只是新的入口层。 |
| 工具卡片 | 卡片**对齐后端真实函数**，结果值取自真实响应 | 卡片名与入参直接用 `pubmed.esearch` / `pubmed.efetch` / `metrics.annotate` / `analyze.aggregate` / `review.generate`，顺序即真实执行顺序；数值全部来自 `/api/analyze` 响应。**需如实说明**：后端目前是一次性返回，故卡片"逐步点亮"是前端按真实阶段做的回放、不是服务端推送；汇总行显示的是**接口真实往返耗时**而非播放时长。下一步改 SSE 增量推送即可去掉回放层。 |
| 快捷开始清单 | 6 项真实能力 + 2 项显式标注「规划中」 | 把没做的东西列成已完成，在演示追问下必然被问穿；不如当路线图如实交底（选题助手 / 元分析流程尚未实现）。 |
| 词云实现 | **自研纯 DOM**（不用 echarts-wordcloud） | canvas 词云依赖容器实测宽高做贪心排版：SPA 首帧尺寸未稳、图表重绘、无头截图等场景下容易整块画不出来，排布结果也不可预期。改为 DOM 文本流后：字号按词频 `sqrt` 压缩（15~41px，长尾词不会被压成噪点）、颜色按频率分 4 档品牌蓝且**与字号严格对应**（避免"字大色浅"的视觉错位），渲染确定、无空白面板风险，文字还可选中/检索/缩放不糊。只取词频前 36 个词——词太多会把容器塞满小字反而看不清层次。 |
| ECharts 引入方式 | **按需注册**（core + bar/pie/grid/tooltip/legend） | 全量 `import "echarts"` 打包 1.19 MB；按需后 **678 KB（gzip 228 KB）**，体积减少 43%。代价是新增图表类型需手动补注册，已在 `EChart.tsx` 注释说明。 |
| 分区标准 | **SCImago 官方发布分区为主**，OpenAlex 阈值推算兜底 | JCR 为 Clarivate 付费授权数据，GitHub 扒表有版权/DMCA 风险，不进交付物；中科院分区 2026-03 起停更。SCImago 免费开放且自带官方分区（早期 403 是缺浏览器头，补齐 UA/Referer 后实测可稳定下载）。两源口径在库内分列、SCImago 优先，UI 不标「JCR」以免误导。 |
| 期刊指标 | 构建期抓取落 SQLite + 运行期零联网 | 演示现场网络不可控；指标构建期落 `journal_metrics.db` 随包发布，运行时只读本地单文件（标准库 sqlite3，零第三方依赖），未收录期刊如实降级"未知"而非编造数值。 |
| 综述生成 | 单次 LLM 调用（非 RAG / 非多智能体） | 输入是已检索到的 Top-N 摘要（自带上下文），无需向量库检索；单次调用延迟低、链路短。多智能体/RAG 的数据量与调试成本对 demo 不成正比。 |
| 无 key 时的综述 | 用**真实统计**拼装分点综述 | 空 key 场景下若返回一段与数据无关的占位话，F4 就没法看。改为把命中量、年份跨度、主题聚类、分区与 IF 分布写成 4~5 点并附真实 PMID 出处（实测 587~641 字），现场不配 key 也能展示 F4 的实际形态；是否调用大模型由响应体 `mock` 字段标记、前端据此提示。 |
| 检索排序 | `sort=relevance`（非 `pub_date`） | 按时间倒序会让样本全部挤在最近年份，年份分布退化成"1–2 根柱子"；改相关性排序后年份跨度达 1988→2026，分布图才有分析价值。 |
| 会话持久化 | 服务端 `sessions.db`（v3 已落库，按用户隔离） | v2 时历史会话存在浏览器 localStorage，换设备即丢、也无法做多用户隔离与追问上下文。v3 落库后：每用户各留 12 条、报告复用键含 `user_id`、追问可直接读服务端全量快照。 |

## 验证结果

### v2 实测（2026-09-18 晚；指标库 SQLite + 文献落库 + 中文检索 全链路复测）

以下数字全部来自**真实链路实测**——真实 NCBI 检索 + 只读本地指标库，可用 `python scripts/precache.py` 逐条复现：

- **检索**：真实调 NCBI E-utilities，各取前 200 篇分析——Alzheimer 命中 **278,960** 篇 / CRISPR cancer **18,121** / COVID-19 vaccine **61,233** / 渐冻症（中文改写后）**41,712**。
- **F1 统计**：年份分布 Alzheimer 1988→2026（26 个年份）、CRISPR cancer 2014→2027（14 个）、COVID-19 vaccine 2020→2025（6 个）；分区分布为 **SCImago 官方分区**（Alzheimer：Q1 112 / Q2 39 / Q3 26 / Q4 14 / 未知 9）；影响因子统计齐备（Alzheimer 均值 4.80、中位 3.22、最高 18.62；CRISPR cancer 均值 9.55、最高 40.4）。
- **F2 可视化**：词云 80 词 + MeSH 研究方向 6 个（三预设一致，已过滤 Humans/Animals 等泛词）。
- **F3 Top100**：各预设均返回 100 条并支持 CSV 导出。Alzheimer 近 5 年样本 95 篇、按年份就近补足 5 条（界面与导出标注「补」）；CRISPR cancer（129 篇）/ COVID-19 vaccine（189 篇）无需补足。
- **F4 综述**：真实大模型（qwen-plus）基于摘要原文生成 1200+ 字中文分点综述，关键论断带 `[PMID: xxxxx]` 标注且无越界 PMID（指标库切换前实测；综述只依赖 Top-N 摘要、不读指标库，切换不受影响）。不配 key 时改为基于本次真实统计拼装的分点综述（响应体 `mock: true`，前端如实提示）。
- **指标覆盖**：Alzheimer **95.5%**（191/200）/ CRISPR cancer **99.0%** / COVID-19 vaccine **99.0%**——SCImago 全量入库后长尾刊基本全覆盖；离群条目（375 条）已在匹配层过滤。
- **对话外壳**：工具卡片结果值与后端实测逐项一致（Alzheimer：命中 278,960 / 匹配指标 191 篇即 95.5% / 词云 80 词 · 方向 6 个 · Top100 100 条），无编造数值。
- **中文检索（v2 新增）**：「渐冻症」经本地术语映射改写为 amyotrophic lateral sclerosis（105ms），命中 41,712 篇；长尾词「肠漏综合征」LLM 改写为 Intestinal Permeability（含检索验证护栏 4.6s），命中 34,316 篇、指标覆盖 100%。文献与分析已落 `literature.db`，ISO 缩写别名自学习 184 个。
- **性能**：三预设命中预缓存秒回（断网可演示）；真实首跑 200 篇总耗时约 21s，其中 NCBI 网络 19%、本地计算 <1%、大模型 81%——提速应换更快模型而非调小 `REVIEW_TOP_N`（30 篇 20.5s vs 10 篇 19.8s）。
- **渲染**：已用真实浏览器（headless Chrome）逐屏截图核验外壳欢迎页、对话流工具卡片、报告总览/图表/词云/Top100，无空白面板（截图见 `docs/`）。

### v3 实测（2026-09-21；账号体系 + 免费试用额度 + 监控日志 + 线上部署）

- **账号与隔离**：注册 → 登录 → 3 次分析全部放行 → 第 4 次 `403` 且文案含联系方式；管理员连打 5 次全部放行、计数保持 0（`test_trial_limit.py` 27 项覆盖，与 41 + 26 + 16 项回归一起全绿）。
- **线上外网实测**（`http://101.37.23.175:8000`）：未登录 401 → 注册 / 登录 200 → `/api/trial` 剩余 3 次 → 3 次分析 200 → 第 4 次 403 → 流式端点回 `trial_limit` error 事件 → 管理面板用户表可见 `trial_used`。
- **日志**：`auth.login.ok` / `auth.logout` / `auth.gate.denied` / `trial.limit.reached` / `api.access` 等事件在服务器 `deploy/logs/app.log` 实际落盘并逐条核对。
- **数据规模**（`python scripts/db_report.py` 只读盘点）：指标库 **34,941 本 / ISSN 索引 58,867**；文献库 5,575 篇 / 45,938 条主题词 / 术语映射 94 条（其中随包种子 81 条）；会话库 5 线程 / 6 消息；账号库 2 行。

## 开发流程约定

仓库：`git@github.com:Zlm-hub/PubMed-Agent.git`（走 SSH；本机 HTTPS 直连 GitHub 会被 reset）。

- 主干为 `main`；约定是功能改动走 `feat|fix|refactor|docs|chore/<scope>` 分支合入（早期提交里也有直接在 `main` 上的，历史保留不改）。
- 分支命名：`feat/<scope>`、`fix/<scope>`、`refactor/<scope>`、`docs/<scope>`、`chore/<scope>`。
- 提交信息用 Conventional Commits，标题一行说清「做了什么」，正文写「为什么这么做」与影响面。
- 提交前跑通：前端 `npm run build`（含 `tsc -b` 类型检查）、后端 `curl /api/health` 与一次 `/api/analyze` 真实请求。
- **密钥与运行期数据不入库**（规则见 `.gitignore`，可 `git check-ignore -v <path>` 复核）：`.env` 类文件、`backend/data/auth_secret.key`（签名密钥，泄漏即可伪造登录态）、`backend/data/*.db` 及其 `-wal`/`-shm` 伴生文件（literature / sessions / users；journal_metrics.db 为可重生的只读指标库，需要随包发布时 `git add -f`）、`backend/cache/`、`backend/logs/`、`deploy/{data,cache,logs,certs}/`、`deploy/.env*`、`frontend/dist/`、`node_modules/`、`output/`。
- **发布形态下的数据文件**：随包发布的是 `backend/data/journal_metrics.json`（OpenAlex 快照，2,748 本）与容器内的 `deploy/data/*.db`（运行期卷，不在仓库里）。

## 已知优化点（非阻塞）
- **工具卡片是前端回放而非服务端流式**（后端 `/api/analyze` 为一次性返回）。要变成真流式需改 SSE 增量推送；这是实现细节，不影响功能完整度，但演示时若被问需如实说明。
- **离群值护栏已上线**：OpenAlex 兜底条目入库即打 `flagged` 标记（篇均被引为 0 或 >100，已标记 375 条），指标匹配在 SQL 层过滤——停刊旧刊号 367.0 这类极端值不再可能透出。残余风险仅为 SCImago 覆盖范围内的极端但真实值。
- 分区是 **SCImago 官方分区（SJR Best Quartile）**而非 JCR 分区；OpenAlex 兜底条目的分区为阈值推算。两者口径已在库内分列，UI 不标「JCR」。
- OpenAlex 对单 IP 限流严（实测 Retry-After 可达 16 小时）；`build_metrics_db.py openalex --live` 在限流期间会失败，直接导入磁盘快照即可。
- 指标库为 18 MB SQLite 单文件，`.gitignore` 默认排除（可由脚本重生）；若演示要求零联网零构建，`git add -f backend/data/journal_metrics.db` 显式纳入即可。
- 打包后仍有 675 KB（echarts 运行时本体），如需进一步压缩可做 `manualChunks` 拆包 + 路由级懒加载；当前单页应用收益有限，未做。
- 真实 LLM 综述需填 `DASHSCOPE_API_KEY`（笔试可报销额度内）。
- `config.CACHE_TTL` 已定义但当前代码未引用，缓存实际不过期——演示场景下是有意为之（预缓存不失效），如需生产化需接入过期判定。

## 演示建议
1. 演示前在能联网环境跑一次 `scripts/precache.py` 生成缓存（现场断网也能秒出）。
2. 启动后端（`MOCK_LLM=1` 即可）+ 前端 `npm run dev`。
3. **动线**：① 对话视图欢迎页讲外壳与快捷开始 → ② 点「文献检索」预填关键词并发送，看 5 张工具卡片推进与结果内联 → ③ 点「查看完整报告」切到报告视图，展开图表 / 词云 / Top100 → ④ 导出 CSV → ⑤ 切设计思考页讲取舍。
4. 讲解主线：过程可见 + 一站式 + 中文优先 + 数据可溯源（每段综述跳 PMID）+ 工程取舍（见「技术取舍」）。
5. 若被问到工具卡片的真实性，直接指 `frontend/src/agent/model.ts` 顶部的注释与 `ToolCard` 的数据来源，如实说明回放与流式的差别。
