# 部署指南（单端口 + 访问口令）

把本项目部署到自己的服务器，给客户一个**网址**即可访问。前端页面与后端 API 由同一个
FastAPI 进程托管（同源），因此**不需要额外的 web 服务器**；要绑域名 + HTTPS 时再挂一层 nginx。

## 一、它长什么样

```
客户端浏览器 ──HTTP(S)──> [ 容器：FastAPI :8000 ]
                              ├── /            前端静态页面（构建产物 /app/web_dist）
                              ├── /api/*       业务接口（检索 / 统计 / 综述 / 会话）
                              └── /api/auth    访问口令（cookie 鉴权）
                         运行期外呼：NCBI E-utilities、阿里云百炼（DashScope）
```

## 二、前置条件

| 项 | 要求 |
|---|---|
| 服务器 | 已装 Docker 与 Docker Compose v2（`docker compose version` 可用） |
| 出网 | 服务器能访问 `eutils.ncbi.nlm.nih.gov` 与 `dashscope.aliyuncs.com`（若走代理需给容器配 `HTTP(S)_PROXY`） |
| 密钥 | `deploy/.env` 含 NCBI / DashScope 密钥（由仓库根 `.env` 生成，见第三节） |
| 端口 | 默认对外 8000，可用 `HOST_PORT` 改。**只占这一个端口，不碰服务器上其它服务** |

> ⚠️ **构建上下文必须是「有数据的完整工作区」**。`backend/data/journal_metrics.db`
> （期刊指标库，约 18MB）在 `.gitignore` 里，**不入 git**；因此**不要**在服务器上
> `git clone` 后直接构建，否则镜像里没有指标库，分区 / 影响因子会全部显示「未知」。
> 正确做法见下方「四、把代码送上服务器」的两种方式。

## 三、部署包是自包含的

服务器上**只需要 `deploy/` 这一个目录**（内含 compose、`.env`、entrypoint、nginx 模板）。
配置**只有一处来源**：`deploy/.env`（既放访问口令，也放 NCBI / DashScope 密钥）。
本机可直接一条命令生成含真实密钥的版本：

```bash
cd deploy && { cat ../.env; echo "ACCESS_CODE=你的口令"; echo "HOST_PORT=8000"; } > .env
```

快速开始（在 `deploy/` 目录执行）：

```bash
docker compose up -d --no-build   # 镜像已 load 时；从源码构建则用 --build
docker compose logs -f app        # 看到 "Uvicorn running on http://0.0.0.0:8000" 即成功
```

浏览器打开 `http://<服务器IP>:8000` → 出现「请输入访问口令」→ 输入 `.env` 里的
`ACCESS_CODE` → 进入应用。

### 只用 8000 端口（推荐用于「一台服务器跑多个项目」）

本服务**只占用宿主机 8000 一个端口**，不碰 80/443，因此**不会与服务器上已有的 nginx
或其它项目冲突**。这种模式下：

- **不需要**改 nginx、不需要子域名、不需要动证书；
- 访问地址二选一（都可用）：
  - `http://101.37.23.175:8000`
  - `http://tangchaolizi.xyz:8000` ← 域名已解析到本机，**带端口访问同样免配置、免备案**
- `deploy/.env` 里 `ACCESS_COOKIE_SECURE` 保持 `0`（因为是 http）。

> ⚠️ **代价（需知情）**：走 `http` 时流量是**明文**的——访问口令与检索内容在公网上不加密。
> 仅作客户演示通常可接受；若之后想加密，不必改变现有架构，只需给本服务加一个子域名
> （见第五节「情形 B」），用宿主机 nginx 反代 + HTTPS 即可，其它项目不受影响。

## 四、把代码送上服务器（二选一）

**方式 A：本地构建镜像后传镜像（推荐 —— 服务器零构建，规避 2G 内存 OOM）**

```bash
# ── 本机（有完整数据的工作区，且 Docker 已启动）──
docker build -f deploy/Dockerfile -t pubmed-analytics:latest .
docker save pubmed-analytics:latest | gzip > pa.tar.gz
scp pa.tar.gz root@101.37.23.175:/opt/
scp -r deploy root@101.37.23.175:/opt/pubmed-analytics/

# ── 服务器 ──
gunzip -c /opt/pa.tar.gz | docker load
cd /opt/pubmed-analytics && docker compose up -d --no-build
```

**方式 B：把整个工作区同步到服务器再构建（内存吃紧，非必要不用）**

```bash
rsync -av --exclude node_modules --exclude .venv --exclude frontend/dist \
      ./ root@101.37.23.175:/opt/pubmed-analytics/
ssh root@101.37.23.175 'cd /opt/pubmed-analytics/deploy && docker compose up -d --build'
```

> 方式 B 需在服务器上跑 `npm ci` + 前端构建（实测峰值 ~852MB）→ 2G 内存有 OOM 风险。

**方式 C：本地只构建前端（不需要 Docker），服务器只装 Python 依赖（2G 机器最稳）**

```bash
# ── 本机：不需要 Docker ──
cd frontend && npm run build && cd ..
rsync -av --exclude node_modules --exclude .venv --exclude .git \
      ./ root@101.37.23.175:/opt/pubmed-analytics/

# ── 服务器：跳过前端构建阶段 ──
cd /opt/pubmed-analytics
docker build -f deploy/Dockerfile.prebuilt -t pubmed-analytics:latest .
cd deploy && docker compose up -d --no-build
```

> 方式 C 用 `deploy/Dockerfile.prebuilt`（只 COPY 已构建的 `frontend/dist`），
> 服务器上只有 `pip install`（峰值约 200MB），**不存在 OOM 风险**。
> 代价：前端改了要本地重新 `npm run build` 再同步。

> 三种方式都要求 `deploy/.env` 存在且含密钥；方式 A 已在本地生成好并随 `deploy/` 一起传。

## 五、可选进阶：绑定域名 + HTTPS

> **不做也可以。** 只占 8000 端口（第三节）就能给客户用。
> 本节仅在你希望「网址不带端口号 / 走 https 加密」时才需要，
> 且下面三种情形**都不会影响服务器上其它项目**。

> ⚠️ **前提：域名必须已完成 ICP 备案，且接入商是这台服务器所在的阿里云账号。**
> 中国大陆服务器对 `80/443` 上的域名访问会做备案校验，未备案会被直接拦截
> （用 `IP:8000` 这种非标准端口一般不受影响，可先这样上线）。备案状态在
> 阿里云控制台「备案」里查；若备案是在别处（如学校服务器）办的，需在这里做「接入备案」。

域名解析：A 记录指向服务器公网 IP —— `tangchaolizi.xyz` 与 `www.tangchaolizi.xyz` **已解析正常**。

### 情形 A：服务器上没有 nginx（用我们自带的 nginx 容器）

1. 让 `app` 只监听内网：把 `docker-compose.yml` 里 `ports` 改成 `"127.0.0.1:8000:8000"`。
2. 反代配置用 `deploy/nginx.conf`（已按 `tangchaolizi.xyz` 填好 `server_name`）。
3. 打开 `docker-compose.yml` 末尾的 `nginx` 服务注释。
4. 证书放到 `deploy/certs/`（`fullchain.pem` + `privkey.pem`）：
   阿里云「数字证书管理服务」可申请**免费 DV 证书**；或
   `certbot certonly --standalone -d tangchaolizi.xyz -d www.tangchaolizi.xyz`。
5. `deploy/.env` 里 `ACCESS_COOKIE_SECURE=1`，然后 `docker compose up -d`。

### 情形 B：服务器上**已有 nginx**（推荐复用，避免 80/443 冲突）

> 这台服务器就属于情形 B：`80/443` 已由宿主机 `nginx/1.24.0 (Ubuntu)` 占用。
> 此时**不要**再起我们的 nginx 容器，而是把配置加进宿主机 nginx。

1. 让 `app` 只监听内网：`docker-compose.yml` 里 `ports` 改成 `"127.0.0.1:8000:8000"`。
2. 用 `deploy/nginx-host.example.conf`：把里面的子域名改成你要用的（如
   `pubmed.tangchaolizi.xyz`），该子域名需先在 DNS 加 A 记录指向服务器 IP。
3. 落地到宿主机 nginx：
   ```bash
   sudo cp nginx-host.example.conf /etc/nginx/sites-available/pubmed.conf
   sudo ln -sf /etc/nginx/sites-available/pubmed.conf /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```
4. 给该子域名签证书：
   `sudo certbot --nginx -d pubmed.tangchaolizi.xyz`
5. `deploy/.env` 里 `ACCESS_COOKIE_SECURE=1`，然后 `docker compose up -d --no-build`。

### 情形 C：把根域名交给本项目（可选 —— 仅在旧站确定不再需要时）

**实测环境**（2026-09-20 勘明）：

| 事实 | 值 |
|---|---|
| 80/443 占用 | 宿主机 `nginx/1.24.0 (Ubuntu)`（pid 91463/91465/91466） |
| nginx 站点配置 | `listen 80 / 443`，`server_name tangchaolizi.xyz www.tangchaolizi.xyz` |
| 443 的反代目标 | `proxy_pass http://172.25.42.176:5000;` ← **该后端已停，所以现在访问是 502** |
| 证书 | DigiCert DV，SAN 覆盖两个域名，**2026-09-22 到期**（非 certbot 签发，`/etc/letsencrypt/live/` 为空） |
| 5000 / 8000 端口 | 均无人监听 → **8000 空闲可用** ✅ |
| Docker | 已安装（有 3 个已停止的 milvus 容器） ✅ |

既然旧站的 5000 后端已经停掉（访问就是 502），最省事、体验最好的做法是**把根域名直接交给本项目**：

```bash
# ① 先备份现网配置
sudo cp -r /etc/nginx/sites-available /etc/nginx/sites-available.bak-$(date +%F)

# ② 找到那个 proxy_pass 172.25.42.176:5000 的 location，改成指向本项目容器
sudo nano /etc/nginx/sites-available/<你的站点文件>
#     proxy_pass http://172.25.42.176:5000;   ← 改成 ↓
#     proxy_pass http://127.0.0.1:8000;
#     并在同一 location 内补上（SSE 必需）：
#     proxy_buffering off;
#     proxy_cache off;
#     gzip off;
#     proxy_read_timeout 300s;
#     proxy_send_timeout 300s;

# ③ 校验并热加载（不中断服务）
sudo nginx -t && sudo systemctl reload nginx
```

之后客户直接访问 **`https://tangchaolizi.xyz`** 即可，**复用现有证书，无需新增 DNS 或子域名**。

> ⚠️ **证书 2026-09-22 到期**（仅剩 2 天）。这个证书不是 certbot 签的，
> 请在**阿里云「数字证书管理服务」**里续签，并重新部署到本服务器；或改成 certbot 托管：
> `sudo certbot --nginx -d tangchaolizi.xyz -d www.tangchaolizi.xyz`（之后自动续期）。

> ⚠️ **`ACCESS_COOKIE_SECURE` 要与访问方式匹配**：走 `https://` 访问就设 `1`；
> 若先用 `http://101.37.23.175:8000` 测试，则必须设 `0`，否则口令 cookie 存不下来会反复弹门。

> 如果想保留旧站、又不想动它，改用**子域名**方案：见上面的「情形 B」，
> 用 `deploy/nginx-host.example.conf` 建 `pubmed.tangchaolizi.xyz`。

## 六、数据与持久化

| 路径（容器内） | 内容 | 持久化 |
|---|---|---|
| `/app/data/journal_metrics.db` | 期刊指标库（只读参考） | 首次启动由镜像种子写入 `./data/` |
| `/app/data/literature.db` | 检索文献 / 分析快照（运行时积累） | 挂载 `./data`，重启保留 |
| `/app/data/sessions.db` | 历史对话 / 报告（运行时积累） | 挂载 `./data`，重启保留 |
| `/app/cache/` | 分析结果文件缓存（预缓存秒回） | 挂载 `./cache` |
| `/app/logs/` | 运行日志（按天轮转） | 挂载 `./logs` |

备份：直接打包 `deploy/data/` 即可（`tar czf backup.tgz data/`）。

## 七、运维速查

```bash
docker compose ps                       # 状态
docker compose logs -f app              # 日志
docker compose restart app              # 重启（改 .env 后必做）
docker compose up -d --build            # 改代码后重建
docker compose down                     # 停止（数据在 ./data，不丢）
```

## 八、常见问题

| 现象 | 原因 / 解决 |
|---|---|
| 页面打开是 404 / 一片空白 | 镜像里没有 `web_dist`——构建时 `frontend` 未成功 `npm run build`，看构建日志 |
| 构建报 `COPY frontend/dist: not found`（方式 C） | 根 `.dockerignore` 把 `frontend/dist` 排除了。**已修**（该行已移除），若你本地 `.dockerignore` 是旧版请更新；或先 `cd frontend && npm run build` |
| 用户访问只看到 JSON / 404，没有页面 | 镜像里缺前端产物：确认用的是 `Dockerfile.prebuilt` 且 `frontend/dist` 存在，或改用标准 `Dockerfile`（阶段 1 会自己构建） |
| 分区 / 影响因子全是「未知」 | 镜像里缺 `journal_metrics.db`；按「方式 A」用完整工作区构建 |
| 一直停在「正在连接服务…」 | 容器起不来或端口未放开；`docker compose logs app` 看报错，检查防火墙 `HOST_PORT` |
| 分析报 502 | 容器出不了网（NCBI / DashScope 不可达）；给容器配代理或放行出网 |
| 输入口令后仍被弹回 | `ACCESS_CODE` 改了但没重启容器：`docker compose restart app` |
| 用 https 打不开 / 口令存不住 | 设了 `ACCESS_COOKIE_SECURE=1` 却在用 http 访问；二者要匹配 |

## 九、资源占用实测（对照「2 核 2G」小服务器）

本项目在同类环境下实测：

| 环节 | 实测值 | 评价 |
|---|---|---|
| 后端启动后（期刊指标库 34,941 本全部载入内存） | **112 MB** | 很轻 |
| 跑完一次 **1000 篇**分析后（含全量结果快照缓存） | **153 MB** | 稳定 |
| 前端构建 `npm run build` 峰值 | **约 852 MB** | 偏高 ⚠️ |
| 镜像体积 | 约 250 MB | 轻 |
| 页面资源（单次分析响应体） | 约 100 KB | 轻 |

**结论：2 核 2G 跑得动，正常使用不会卡。** 分析耗时的瓶颈是**到 NCBI（美国）的网络往返**，不是服务器 CPU——本项目检索与聚合全程异步 I/O，2 核与 8 核差别很小（单次 200 篇约 5–8 秒，加中文综述总计约 15–25 秒）。

**但请务必用「方式 A」（本地构建镜像 → 传镜像），不要在服务器上构建**：2G 内存里前端构建单进程峰值就到 852 MB，再叠加 `npm ci` 与 Docker 守护进程，有 **OOM 风险**。服务器上只做 `docker load` + `docker compose up`，零构建压力。

### 上线前必做两件事

1. **放行端口**：阿里云控制台 → 轻量应用服务器 → **防火墙**，添加规则放行你要用的端口（默认 `8000`）；
   服务器内若启用了 `ufw`，也要 `sudo ufw allow 8000/tcp`。
2. **域名与备案**：先用 `http://<公网IP>:8000` 访问——**用 IP + 非 80 端口一般无需备案**；
   若要绑域名走 80/443，中国大陆服务器需先完成 **ICP 备案**，否则会被拦截。
   （备案会显著拉长上线周期；仅做客户演示，建议先走 IP 方式。）

## 十、上线实测记录（阿里云轻量 2核2G / Ubuntu 24.04）

2026-09-20 在 `101.37.23.175`（华东1杭州）完成首次真实部署，实测数据与踩坑留档：

| 指标 | 实测值 |
|---|---|
| 首次启动耗时（载入 18MB 期刊指标库） | **约 1 分 50 秒** |
| 容器内存占用 | 约 150 MB |
| 镜像构建耗时（走阿里云 PyPI 镜像） | 约 2 分钟 |
| 一次真实分析（中文词，40 篇 + 中文综述） | 约 20–40 秒 |

### 三个踩过的坑（都已修）

1. **直连 PyPI 会"假性报错"**：`pip install` 解析 221 秒后报
   `Could not find a version that satisfies httptools>=0.8.0 … (from versions: none)`，
   而同一包单独 `pip download` 是成功的 —— 属于网络抖动而非缺包。
   → Dockerfile 已默认走**阿里云 PyPI 镜像**并加 `--retries 5`；海外机器可用
   `--build-arg PIP_INDEX_URL=https://pypi.org/simple` 覆盖。

2. **启动慢会被误判成"起不来"**：2 核机器启动要 ~110 秒，
   原来的健康检查 `start_period: 20s` 与脚本 30 秒等待都会误报失败。
   → 已把 `start_period` 调到 `150s`、脚本等待调到 `180s` 并打印进度。

3. **术语种子被挂载卷盖住**：中文术语映射（L0）原本只存在运行期的 `literature.db` 里，
   而该库不入包（避免带上本机历史），导致新环境 `term_mapping` 为空 →
   **所有中文提问都退化到大模型改写**（多一次调用、且失去无 key 时的兜底）。
   修复：已审核词条导出为 `backend/app/term_mapping_seed.json`（81 条），
   启动时若库内无 approved 词条则自动导入。
   注意该文件放在 **Python 包内**而不是 `backend/data/` —— 后者在容器里是挂载卷，
   会把镜像里的文件盖住（第一版就踩了这个，种子读不到）。

### 验证通过项（外网实测）

```
GET  /                       → 200（返回前端页面）
GET  /api/health             → {"status":"ok"}
GET  /api/demo/presets 无口令 → 401
POST /api/auth 错口令/对口令  → 401 / 200
POST /api/analyze「肺癌」     → source=mapping（走本地映射）、命中 510,149、
                               IF/分区匹配正常、中文综述 1123 字（非 mock）
```

## 十一、用户与管理员体系（2026-09-20 上线）

**形态**：管理员建号制。用户名 + 密码登录（PBKDF2 哈希存储，纯标准库）；会话按用户
隔离；管理员有「管理后台」面板（建号 / 重置密码 / 禁用 / 删除 / 查看全部会话）。

**配置**（已在 `.env` 预置，上线前建议改掉初始密码）：

| 变量 | 说明 |
|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 容器首启自动创建的管理员（仅 users 表为空时生效） |
| `AUTH_SECRET` | 登录 token 的 HMAC 签名密钥；不配则自动生成落盘（重启不掉线） |
| `ACCESS_CODE` | 降级为**运维通道**：`curl -H "X-Access-Code: ..."` 仍可访问 API（自检脚本不变）；浏览器端不再认共享口令 |

**升级行为**：重启后自动迁移——`chat_sessions` 补 `user_id` 列，存量无归属会话全部
划给管理员账号；老用户浏览器里的旧口令 cookie 登录时会自动清除。

**验证**：打开网址 → 登录 admin → 顶栏「管理后台」建一个演示账号 → 用该账号登录
确认侧栏为空、检索后只出自己的历史。

### 自助注册（同日补充）

登录页是否显示「注册」入口由 `ALLOW_REGISTRATION` 控制：

| 值 | 行为 |
|---|---|
| `0`（默认） | 关闭注册，账号只能由管理员在后台创建 |
| `1` | 登录页出现「注册」入口，注册即登录 |

安全边界（代码位置：`backend/app/main.py::auth_register`、`userdb.py::create_user`）：

- 自助注册的账号**一律 `role='user'`**，请求体里没有 role 字段，无法提权；
- 用户名查重**不区分大小写**（`COLLATE NOCASE`），防 `Admin` 冒充 `admin`；
- 唯一例外是「系统里一个账号都没有」时（首引导）：第一个注册者成为管理员。
  没这个例外，全新部署（既没配 `ADMIN_*` 又没人能建号）会彻底锁死；前端会在
  按钮下方如实标注这一条；
- 注册来源（UA + IP，截断 120 字符）记入 `users.source`，管理后台可追溯。

## 十二、服务器改为纯账号制 + 免费试用 3 次（2026-09-21）

### 去掉共享口令

服务器**不再使用 `ACCESS_CODE`**（已在 `deploy/.env` 清空）。原因是口令是"一次泄露、
所有人可用"的共享凭证，无法按人计量；改账号制后每个访客有独立身份，才能做下面的
试用额度。清空后闸门自动落到 `user` 模式：所有 `/api/*` 必须携带登录 cookie，
未登录一律 401（运维自检仍可用 `X-Access-Code` 头——**前提是 .env 里仍配了口令值**，
本机开发用得到；服务器上留空即彻底关闭该通道）。

> 清空口令的前提是**库里已有账号**。全新部署时建议保留 `ADMIN_*`（首启自动建管理员），
> 否则无人能进；若两者都没有，登录页会显示「首次使用」入口，第一个注册者成为管理员。

### 免费试用额度

| 变量 | 说明 |
|---|---|
| `FREE_TRIAL_LIMIT` | 每个**普通账号**最多分析 N 次。`0`（默认）= 不限制、不计数（本地开发形态）；服务器设 `3` |
| `ADMIN_CONTACT` | 额度用尽时展示的联系方式（服务器设 `QQ3184331768`） |

规则（代码位置：`main.py::_trial_gate`、`userdb.py::consume_trial`）：

- **计次口径**：`POST /api/analyze` 与 `GET /api/analyze/stream` 各算一次，**含缓存命中**
  （否则换个词/清缓存就能绕过）；「生成报告」只是复用结果快照，不计次。
- **豁免**：`role=admin` 的账号与运维通道不计数、不受限；本地 `open` 模式（无身份）不启用。
- **超限提示**：非流式返回 `403` + 可读文案；流式端点因为 EventSource 读不到 4xx 响应体，
  改为回一条 SSE `error` 事件（前端同样原样显示文案）。文案形如
  「免费试用次数已用完（共 3 次），请与管理员联系开通：QQ3184331768」。
- **前端**：顶栏显示「免费试用剩余 N 次」（用尽变红），用尽后主区顶部常驻提示条；
  数字每次都向后端查询（不做本地推算），管理面板用户表新增「试用」列显示 `已用 / 总数`。
- **给客户加次数**：管理后台 → 用户管理 → 该用户「重置试用」（`PATCH /api/admin/users/{id}`
  带 `reset_trial: true`），计数清零即可再用 N 次。
- **边界（诚实声明）**：额度按账号计，**同一人可以注册多个账号绕过**——这是"试用漏斗"
  形态的固有边界。若要严格限制，需要再加设备/IP 维度或关闭自助注册（`ALLOW_REGISTRATION=0`）。

### 验证（本机同构 + 服务器外网）

本机以生产同源模式（临时端口 8010、`FREE_TRIAL_LIMIT=3`）实测：注册 → 顶栏显示
「免费试用剩余 3 次」→ 连续 3 次分析均 200 → 第 4 次 403 且提示含 QQ 号 →
刷新后顶栏变「免费试用已用尽」+ 顶部常驻提示条。后端回归脚本
`backend/scripts/test_trial_limit.py`（27 项）覆盖限额 0/1/3、管理员豁免、
SSE 超限、重置额度与 open 模式不受限。
