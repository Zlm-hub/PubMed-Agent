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

> 本项目已经准备好一条命令落地子域名 HTTPS：`DOMAIN=pubmed.tangchaolizi.xyz EMAIL=你@邮箱 sh deploy/setup-https.sh`
> （幂等：会先预检 DNS，未解析就安全退出、不碰服务器；然后装 certbot → 放 nginx 配置 → 签发证书 → 验 https 与续期演练）。
> 手动等价做法用到的配置文件是 `deploy/nginx-pubmed.conf`
> （80→301 + ACME 挑战目录 + 443 反代，SSE 关缓冲、透传 X-Forwarded-For 以便后端按真实 IP 限流）。
> 落地四步：① DNS 加 A 记录 ② 放到 `/etc/nginx/conf.d/` 并 reload ③ `certbot --nginx -d <子域名>`
> ④ 只走 https 时把 `ACCESS_COOKIE_SECURE=1` 并重建容器（若仍保留 http 直连则保持 0）。

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

## 十三、备份与恢复（2026-10-14 补）

```bash
# 手动备份（默认写 deploy/backups/，保留 7 份）
sh deploy/backup.sh
KEEP=14 sh deploy/backup.sh
OUT=/mnt/nas/pa sh deploy/backup.sh      # 推荐：写到另一块盘/挂载点

# 定时（每天 03:00）
crontab -e
0 3 * * * cd /home/admin/project/pubmed-analytics && sh deploy/backup.sh >> deploy/logs/backup.log 2>&1
```

**要不要停服**：不用。脚本用 sqlite3 的在线备份 API（`Connection.backup`）逐页复制，
对源库只加读锁，服务照常写入；备份完成后对副本跑 `PRAGMA integrity_check`，
在输出里逐个库打印 `[OK]/[FAIL]`（有 FAIL 时脚本以退出码 1 结束，方便 cron 告警）。

**恢复步骤**：

```bash
cd /home/admin/project/pubmed-analytics
ls -la deploy/backups/                     # 选一份备份
tar xzf deploy/backups/pa-backup-<时间戳>.tar.gz -C /tmp/pa-restore

sudo docker compose -f deploy/docker-compose.yml stop app     # ① 停容器（避免写坏库）
cp /tmp/pa-restore/deploy__data__users.db        deploy/data/users.db        # ② 按需还原
cp /tmp/pa-restore/deploy__data__sessions.db     deploy/data/sessions.db
cp /tmp/pa-restore/deploy__data__literature.db   deploy/data/literature.db
cp /tmp/pa-restore/deploy__data__journal_metrics.db deploy/data/journal_metrics.db
rm -f deploy/data/*.db-wal deploy/data/*.db-shm               # ③ 清掉 WAL/SHM 残片
sudo docker compose -f deploy/docker-compose.yml up -d --no-build   # ④ 起容器
curl -s 'http://127.0.0.1:8000/api/health?deep=1'             # ⑤ 深检：库真的打开了
```

> 备份包里的文件名 = **完整相对路径拍平**（例如 `deploy__data__users.db`），
> 恢复时改回 `<库名>.db` 放回原目录即可。脚本会**按优先级只备份一处**数据目录：
> 部署形态用 `deploy/data`（容器实际读写的挂载卷），本机开发回落到 `backend/data`
> —— 两处存在同名库，都备会撞名且白占体积（服务器上实测踩过）。
>
> 另外：脚本把副本的 `journal_mode` 切回 DELETE 并要求 `integrity_check` 通过，
> 所以归档里不会出现 `-wal`/`-shm` 伴生文件；任何一步失败都会**删除半截归档**并以
> 非零退出码结束，避免"看起来有备份、其实不能用"。

**边界**：只做本机快照 + 轮转，**不含异地容灾**；请把 `--out` 指到另一块盘或远端挂载点，
并监控 `deploy/logs/backup.log` 与脚本退出码。

## 十四、访问防护（2026-10-14 上线）

| 变量 | 默认 | 作用 |
|---|---|---|
| `LOGIN_MAX_FAILS` / `LOGIN_LOCK_SECONDS` | 8 / 300 | 登录失败锁定：同 IP+用户名 300 秒内失败 8 次即冷却，返回 429 + Retry-After |
| `RATE_LIMIT_PER_MIN` | 300 | 每 IP 每分钟接口上限（`/api/health` 豁免） |
| `ANALYZE_RATE_PER_MIN` | 30 | 每 IP 每分钟分析上限（最贵的两个端点单列） |
| `REGISTER_PER_DAY` | 3 | 每 IP 每天自助注册账号数（挡批量注册刷试用额度） |

- 登录 cookie 已改 **HttpOnly**：前端 JS 读不到凭证，XSS 也偷不走登录态（前端全程不读 cookie，链路零影响）。
- 计数是**进程内内存**（单容器单 worker）：重启清零；多实例部署需换 Redis（只改 `app/guard.py`）。
- 审计：被限流/被锁定都会落 `guard.rate.limited`、`guard.login.locked`、`guard.register.limited` 日志，
  可在 `deploy/logs/app.log` 里查来源 IP 与重试秒数。
- 深检探活：`curl 'http://127.0.0.1:8000/api/health?deep=1'` —— 会真的打开四个库与指标库，
  「进程活着但库坏了」这种假健康会在这一步暴露（失败返回 503）。

## 十五、告警与巡检（2026-10-14 上线）

服务跑起来不等于有人知道它挂了。这里用两个脚本把「出事有人通知」补齐：

```bash
sh deploy/alert.sh "自定义告警内容"     # 推一条到群机器人（未配 webhook 时只写本地日志）
sh deploy/monitor.sh                    # 巡检一次（crontab 每 5 分钟自动跑）
```

**monitor.sh 查三件事**，任一异常即推送，且**只在状态变化时推送**（去抖，避免每 5 分钟刷屏）：

| 检查 | 判据 | 命中后推送 |
|---|---|---|
| 健康深检 | `curl /api/health?deep=1` 非 200 / 超时 | 「服务健康检查失败」+ 最近 3 行 error.log；恢复时推一条「已恢复」 |
| 错误日志突增 | 最近 `MONITOR_ERROR_WINDOW_MIN`（默认 15）分钟内 `error.log` 的 ERROR 行数 ≥ `MONITOR_ERROR_THRESHOLD`（默认 5） | 「错误日志突增」+ 两条样例 |
| 备份新鲜度 | 最新备份超过 `MONITOR_BACKUP_MAX_HOURS`（默认 36）小时未更新 | 「备份超过 N 小时未更新」 |

另外 `backup.sh` 备份失败时会**立刻**调 alert.sh 推一条（不等巡检发现），退出码保持非零供 cron 记录。

**接入群机器人**（`deploy/.env`，改完即生效，不需要重启容器）：

```ini
ALERT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx   # 机器人 URL
ALERT_FORMAT=wecom        # wecom（企业微信，默认）/ dingtalk（钉钉）/ feishu（飞书）
```

| 平台 | 取 URL 的位置 | payload 结构 |
|---|---|---|
| 企业微信 | 群 → 添加群机器人 → 复制 Webhook | `{"msgtype":"text","text":{"content":"..."}}` |
| 钉钉 | 群 → 智能群助手 → 自定义机器人 | 同上 |
| 飞书 | 群 → 设置 → 群机器人 → 自定义机器人 | `{"msg_type":"text","content":{"text":"..."}}` |

**crontab（已装，root）**：

```
0 3 * * *   cd /home/admin/project/pubmed-analytics && sh deploy/backup.sh  >> deploy/logs/backup.log  2>&1
*/5 * * * * cd /home/admin/project/pubmed-analytics && sh deploy/monitor.sh >> deploy/logs/monitor.log 2>&1
```

留痕：`deploy/logs/alert.log`（每条告警 + webhook 返回码）、`deploy/logs/monitor.log`（每轮检查输出）、
`deploy/logs/.monitor-state`（去抖状态，删掉即「重新开始报」）。

**边界（如实说明）**：巡检是**轮询 + 状态去抖**，最坏情况是「服务挂了最多 5 分钟才通知」；
它不推送「业务指标」（如日活、额度消耗），那是下一阶段「用量统计」要补的。
