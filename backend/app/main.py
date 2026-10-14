"""FastAPI 入口：/api/health, /api/analyze（检索 + 聚合 + 中文综述）, /api/analyze/stream（SSE 流式）, /api/demo/presets, /api/logs, /api/sessions（历史会话持久化）。"""
import asyncio
import glob
import hashlib
import json
import os
import time

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cache, config, monitor, pipeline, sessiondb, userdb, wordzh

app = FastAPI(title="PubMed 文献分析", version="0.5.0")

# 无需鉴权即可访问的路径（健康检查用于前端探活；鉴权接口自身做校验）。
# 注意：注册接口必须在这里——它是"还没有身份的人"唯一的入口，闸门放行后由接口
# 内部按 ALLOW_REGISTRATION 与首引导规则决定是否真的允许（实测踩过：漏了它会被
# 闸门直接 401，前端只会看到"未登录"而不是"未开放注册"）。
_OPEN_PATHS = {"/api/health", "/api/auth", "/api/auth/register"}

# 运维虚拟管理员：X-Access-Code 头（旧共享口令）或旧口令 cookie 命中时以此身份通行。
# 用途：服务器自检脚本 / curl 排障不依赖浏览器登录；不占用真实账号。
_OPS_ADMIN = {"id": "_ops", "username": "ops", "role": "admin", "display_name": "运维通道"}


def _code_token(code: str) -> str:
    """口令的令牌值。cookie 值只能是 ASCII，而口令可能含中文，故统一存 SHA-256 十六进制。"""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _header_matches(raw: str) -> bool:
    """请求头按 latin-1 解码；口令含中文时需先还原成 UTF-8 再比较。"""
    if raw == config.ACCESS_CODE:
        return True
    try:
        return raw.encode("latin-1").decode("utf-8") == config.ACCESS_CODE
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


def _users_active() -> bool:
    """用户体系是否激活（users 表非空）。激活后浏览器端一律走账号登录。"""
    return userdb.count() > 0


def _resolve_user(request: Request) -> dict | None:
    """从请求中解出身份：签名 cookie（用户体系）或旧口令通道（运维兜底）。

    用户体系激活后，旧口令 cookie 不再授予权限（防止共享口令外泄后冒充管理员），
    仅保留 `X-Access-Code` 请求头作为运维通道。返回 None 表示未识别。
    """
    if _users_active():
        tok = request.cookies.get(config.AUTH_COOKIE)
        if tok:
            user = userdb.verify_token(tok)  # 解签 + 回查用户行：禁用/删除即时失效
            if user:
                return user
        hdr = request.headers.get("x-access-code")
        if hdr and config.ACCESS_CODE and _header_matches(hdr):
            return _OPS_ADMIN
        return None
    if config.ACCESS_CODE:
        if request.cookies.get(config.ACCESS_COOKIE) == _code_token(config.ACCESS_CODE):
            return _OPS_ADMIN
        hdr = request.headers.get("x-access-code")
        if hdr and _header_matches(hdr):
            return _OPS_ADMIN
    return None


@app.middleware("http")
async def _access_gate(request: Request, call_next):
    """访问闸门（v2：用户体系）+ 请求级访问日志（2026-09-21 升级）。

    三种模式自动切换：
      user —— users 表非空：/api/* 必须携带有效登录 cookie（或运维头），身份挂
              request.state.user，下游按 user_id 隔离会话；
      code —— 未建用户但配置了 ACCESS_CODE：保持旧共享口令行为（部署过渡期兼容）；
      open —— 两者皆无（本地开发）：直接放行，身份为 None（会话不隔离，同旧版）。

    cookie 作主通道是为了让「无法自定义请求头的 EventSource」也能带上凭证——
    同源请求自动携带 cookie，流式分析链路一行不用改。

    2026-09-21 日志升级：
      - 被闸门拒绝的请求（401）落 `auth.gate.denied`（此前只在 uvicorn 控制台一闪而过，
        app.log 里无痕，用户反馈"报错都没有记录"）；
      - 放行的 /api/* 请求落 `api.access`（method/path/status/耗时/用户），
        health 与 analyze/stream 除外——health 是探活噪音，analyze 有更细的
        request.start/done，重复记只会稀释日志。
    """
    path = request.url.path
    request.state.user = None
    started = time.perf_counter()
    if path.startswith("/api/"):
        monitor.set_request_id()
    if path.startswith("/api/") and path not in _OPEN_PATHS:
        user = _resolve_user(request)
        required = _users_active() or bool(config.ACCESS_CODE)
        if required and user is None:
            # 拒绝也要留痕：谁（IP）、带了什么、想访问哪，排障/安全审计都靠它
            monitor.warning(
                "auth", "gate.denied",
                path=path, method=request.method,
                client=request.client.host if request.client else None,
                has_session_cookie=bool(request.cookies.get(config.AUTH_COOKIE)),
                has_code_header=bool(request.headers.get("x-access-code")),
                mode="user" if _users_active() else "code",
                ms=round((time.perf_counter() - started) * 1000),
            )
            return JSONResponse({"detail": "未登录或登录态已失效"}, status_code=401)
        request.state.user = user
    response = await call_next(request)
    if (
        path.startswith("/api/")
        and path not in _OPEN_PATHS
        and path not in {"/api/analyze", "/api/analyze/stream"}
    ):
        monitor.step(
            "api", "access",
            method=request.method, path=path, status=response.status_code,
            user=(request.state.user or {}).get("username"),
            client=request.client.host if request.client else None,
            ms=round((time.perf_counter() - started) * 1000),
        )
    return response


# 注意顺序：CORS 在闸门之后 add_middleware，因而位于中间件栈最外层——
# 这样闸门返回的 401 也会带上 CORS 头（本地跨端口开发时前端才能读到错误）。
# allow_credentials=True（2026-09-21）：登录 cookie 是凭证，前端 fetch 统一
# credentials:"include"，浏览器要求响应带 Access-Control-Allow-Credentials 才会
# 接受 Set-Cookie/发送 cookie；缺了它登录"成功"但 cookie 存不下 → 全部 401（实测踩过）。
if config.ALLOWED_ORIGINS:
    # 显式白名单优先（跨域部署时用；单端口同源部署其实用不到 CORS）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # 本地开发：放行本机**任意端口**。
    # 别把 5173 写死——Vite 发现端口被占用会自动顺延到 5174，而白名单没有它，
    # 浏览器会把响应整条拦掉，表现成「前端连不上后端」（后端其实完全正常）。实测踩过。
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

_cache: dict[str, dict] = {}


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    """未捕获异常兜底（2026-09-21 日志升级）：堆栈落 error.log，响应带 request_id。

    此前 FastAPI 默认只把 500 打在 uvicorn 控制台，app.log/error.log 无痕；
    现在统一落 `api.unhandled.error`（ok=False + exc=True → 带完整堆栈）。
    HTTPException 不走这里（FastAPI 有专门的处理器），4xx 语义不受影响。
    """
    monitor.step(
        "api", "unhandled.error", ok=False, exc=True,
        path=request.url.path, method=request.method,
        error=f"{type(exc).__name__}: {exc}",
    )
    return JSONResponse(
        {"detail": "服务器内部错误", "request_id": monitor.get_request_id()},
        status_code=500,
    )


class AnalyzeRequest(BaseModel):
    query: str
    max_results: int = 200
    include_review: bool = True


class SessionExchange(BaseModel):
    """一轮问答：用户提问 + 完整分析结果快照（含 articles 全量，追问时可直接作上下文）。

    ask = 用户原话（可选）：用户气泡存原话，query 只是检索词；缺省时退回 query。
    """
    query: str
    result: dict
    elapsed_ms: int | None = None
    ask: str | None = None


class SessionCreateRequest(BaseModel):
    """新建两类记录之一：

    kind='chat'   → 新建对话线程（首问即标题，需要 result）
    kind='report' → 新建/复用报告（需要 doc = 全量快照；可带 chat_id 关联来源对话，
                    chat_id 为空则是独立报告）
    """
    kind: str = "chat"
    query: str
    title: str | None = None
    # kind='chat'
    result: dict | None = None
    elapsed_ms: int | None = None
    ask: str | None = None
    # kind='report'
    doc: dict | None = None
    meta: dict | None = None
    chat_id: str | None = None


def _load_file_cache() -> None:
    """启动时把 cache/*.json 载入内存，使演示预缓存即使断网也能秒回。"""
    if not os.path.isdir(config.CACHE_DIR):
        return
    for path in glob.glob(os.path.join(config.CACHE_DIR, "*.json")):
        key = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8") as f:
                _cache[key] = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue


def _persist_cache(key: str, payload: dict) -> None:
    try:
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        with open(os.path.join(config.CACHE_DIR, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError:
        pass


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "pubmed-analytics"}


class AuthRequest(BaseModel):
    """登录请求。用户体系激活时用 username/password；旧口令模式用 code（过渡兼容）。"""

    code: str = ""
    username: str = ""
    password: str = ""


class RegisterRequest(BaseModel):
    """自助注册请求。role 不在请求里——注册出来的永远是普通用户。"""

    username: str = ""
    password: str = ""
    display_name: str | None = None


def _public_user(user: dict | None) -> dict | None:
    if not user:
        return None
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "display_name": user.get("display_name"),
    }


def _set_login_cookie(response: Response, user: dict) -> None:
    """签发登录 cookie 并清掉旧共享口令 cookie（同一逻辑登录/注册共用）。"""
    response.delete_cookie(config.ACCESS_COOKIE)
    response.set_cookie(
        key=config.AUTH_COOKIE,
        value=userdb.make_token(user["id"]),
        max_age=userdb.TOKEN_TTL,
        samesite="lax",
        secure=config.ACCESS_COOKIE_SECURE,
        httponly=False,
    )


def _device_hint(request: Request) -> str:
    """注册来源（排障/审计用，仅存 60 字符）。"""
    ip = request.client.host if request.client else ""
    return (request.headers.get("user-agent", "")[:40] + f" | {ip}").strip(" |")


@app.get("/api/auth")
def auth_status(request: Request):
    """鉴权状态：前端据此决定弹哪种登录门（并显示注册入口与否），以及当前用户与角色。"""
    active = _users_active()
    user = _resolve_user(request)
    reg = bool(config.ALLOW_REGISTRATION)
    # 首引导：一个账号都没有 + 开放注册 → 第一个注册者即管理员。
    # 注意：此时闸门处于 open 模式（auth_required=False），但前端仍要看到
    # can_bootstrap 才会显示注册入口——全新部署（既没配 ADMIN_* 也没账号）
    # 若不放注册入口，就彻底进不去任何界面。
    boot = (not active) and reg
    if not active and not config.ACCESS_CODE:
        return {
            "auth_required": False, "authorized": True, "mode": "open",
            "user": None, "allow_registration": reg, "can_bootstrap": boot,
            "trial": None,
        }
    return {
        "auth_required": True,
        "authorized": user is not None,
        "mode": "user" if active else "code",
        "user": _public_user(user),
        "allow_registration": reg,
        "can_bootstrap": boot,
        # 试用额度（未启用/管理员豁免时为 None）——前端登录后即显示剩余次数
        "trial": _trial_quota(user),
    }


@app.post("/api/auth")
def auth_login(req: AuthRequest, request: Request, response: Response):
    """登录。用户体系激活 → 用户名+密码签发 token cookie；否则退回旧口令校验。

    成功/失败都落审计日志（2026-09-21 用户要求记录登录退出）：
    `auth.login.ok` / `auth.login.failed` / `auth.code.failed`，带用户名、IP 与 UA 摘要。
    """
    client = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:60]
    if _users_active():
        name = req.username.strip()
        user = userdb.authenticate(name, req.password)
        if user is None:
            # 失败留痕是安全审计的基本盘：连续失败可在此发现撞库/忘密码
            monitor.warning("auth", "login.failed", user=name, client=client, ua=ua)
            raise HTTPException(status_code=401, detail="用户名或密码不正确")
        userdb.touch_login(user["id"])
        _set_login_cookie(response, user)
        monitor.step("auth", "login.ok", user=user["username"], role=user["role"], client=client, ua=ua)
        return {"ok": True, "user": _public_user(user)}
    if not config.ACCESS_CODE:
        return {"ok": True}
    if req.code.strip() != config.ACCESS_CODE:
        monitor.warning("auth", "code.failed", client=client, ua=ua)
        raise HTTPException(status_code=401, detail="访问口令不正确")
    response.set_cookie(
        key=config.ACCESS_COOKIE,
        value=_code_token(config.ACCESS_CODE),
        max_age=60 * 60 * 24 * 30,  # 30 天
        samesite="lax",
        secure=config.ACCESS_COOKIE_SECURE,
        httponly=False,
    )
    monitor.step("auth", "login.ok", user="(口令模式)", client=client, ua=ua)
    return {"ok": True}


@app.post("/api/auth/register")
def auth_register(req: RegisterRequest, request: Request, response: Response):
    """自助注册（2026-09-20 用户要求）。

    规则（安全边界，均可在 userdb 对应函数核到）：
      - 受 `ALLOW_REGISTRATION` 开关控制，默认关闭 → 403；
      - **注册账号永远是 role='user'**，请求体里根本没有 role 字段；
      - 唯一的例外是「系统里一个账号都没有」时（全新部署、管理员的 ADMIN_* 又没配，
        否则会彻底锁死）：允许注册，且首个账号即管理员。「can_bootstrap」为真前端才放行；
      - 用户名查重**不区分大小写**（防止 Admin / admin 这类冒充）。
    """
    if not config.ALLOW_REGISTRATION:
        raise HTTPException(status_code=403, detail="本服务未开放自助注册，请联系管理员开通账号")
    username = req.username.strip()
    password = req.password
    boot = not _users_active()
    if boot:
        # 只为避免"全新部署无人能进"的场景；已有管理员时走后台建号
        existing_admin = userdb.first_admin()
        if existing_admin is not None:
            raise HTTPException(status_code=403, detail="本服务未开放自助注册，请联系管理员开通账号")
    try:
        user = userdb.create_user(
            username, password,
            role="admin" if boot else "user",
            display_name=req.display_name or username,
            source=_device_hint(request),
        )
    except ValueError as e:
        monitor.warning("auth", "register.failed", user=username, client=request.client.host if request.client else None, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    userdb.touch_login(user["id"])
    _set_login_cookie(response, user)
    monitor.step(
        "auth", "register.ok",
        user=user["username"], role=user["role"], bootstrap=boot,
        client=request.client.host if request.client else None,
    )
    return {"ok": True, "user": _public_user(user), "bootstrap": boot}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    """退出登录：清登录 cookie（服务端无状态 token，无需吊销表）。

    审计：先按 cookie 解出是谁在退出（cookie 无效/已过期也照常清，仅少记一个用户名）。
    """
    user = _resolve_user(request)
    response.delete_cookie(config.AUTH_COOKIE)
    monitor.step(
        "auth", "logout",
        user=user["username"] if user else None,
        client=request.client.host if request.client else None,
    )
    return {"ok": True}


# ---------- 会话接口的身份助手 ----------

def _identity(request: Request) -> dict | None:
    return getattr(request.state, "user", None)


def _uid_of(request: Request) -> str | None:
    """当前身份的 user_id。open 模式（无身份）返回 None = 不过滤，与旧版行为一致。"""
    user = _identity(request)
    return user["id"] if user else None


def _require_admin(request: Request) -> dict:
    user = _identity(request)
    if not (user and user.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ---------- 免费试用额度（2026-09-21：服务器版「每个账号免费试用 N 次」） ----------

def _trial_quota(user: dict | None) -> dict | None:
    """额度快照（前端展示用）。None = 不适用：未启用额度 / 无身份 / 管理员豁免。"""
    limit = config.FREE_TRIAL_LIMIT
    if limit <= 0 or not user or user.get("role") == "admin":
        return None
    used = userdb.trial_used_of(user["id"])
    return {
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
        "contact": config.ADMIN_CONTACT or None,
    }


def _trial_message() -> str:
    msg = f"免费试用次数已用完（共 {config.FREE_TRIAL_LIMIT} 次），请与管理员联系开通"
    if config.ADMIN_CONTACT:
        msg += f"\n管理员联系方式：{config.ADMIN_CONTACT}"
    return msg


def _trial_gate(request: Request) -> dict | None:
    """额度闸门：**放行时已扣减一次**，返回 None；超限返回拒绝信息。

    豁免：额度未启用（FREE_TRIAL_LIMIT=0）、无身份（open 模式本地开发）、
    role=admin（含运维通道 _OPS_ADMIN）——管理员自己试用不该被计数。
    扣减用 userdb.consume_trial 的原子事务，并发下不会超额放行。
    """
    limit = config.FREE_TRIAL_LIMIT
    if limit <= 0:
        return None
    user = _identity(request)
    if not user or user.get("role") == "admin":
        return None
    ok, used = userdb.consume_trial(user["id"], limit)
    if not ok:
        monitor.warning("trial", "limit.reached", user=user["username"], used=used, limit=limit)
        return {
            "message": _trial_message(),
            "limit": limit,
            "used": used,
            "remaining": 0,
            "contact": config.ADMIN_CONTACT or None,
        }
    monitor.step("trial", "consumed", user=user["username"], used=used, limit=limit)
    return None


@app.get("/api/trial")
def api_trial(request: Request):
    """当前账号的试用额度：前端据此显示「剩余 N 次」或「已用尽，联系管理员」。

    limit 是顶层字段（管理员也要看得到总数，用于管理面板的「已用 / 总次数」列）；
    quota 则是**当前身份自己**的额度快照，管理员豁免时为 None。
    """
    user = _identity(request)
    return {
        "enabled": config.FREE_TRIAL_LIMIT > 0,
        "limit": config.FREE_TRIAL_LIMIT,
        "contact": config.ADMIN_CONTACT or None,
        "exempt": bool(user and user.get("role") == "admin"),
        "quota": _trial_quota(user),
    }


@app.get("/api/demo/presets")
def demo_presets():
    return {"presets": config.PRESETS}


@app.post("/api/sessions")
def api_create_session(req: SessionCreateRequest, request: Request):
    """新建对话线程（kind=chat）或报告记录（kind=report，带全量快照）。归属当前用户。"""
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    uid = _uid_of(request)
    try:
        if req.kind == "report":
            if not isinstance(req.doc, dict):
                raise HTTPException(status_code=400, detail="report 需要 doc（全量快照）")
            return sessiondb.save_report(
                query, req.doc, req.meta, req.chat_id, req.title, user_id=uid
            )
        if not isinstance(req.result, dict):
            raise HTTPException(status_code=400, detail="chat 需要 result（首问结果）")
        return sessiondb.create_thread(query, req.result, req.elapsed_ms, req.title, req.ask, user_id=uid)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        monitor.step("api", "session.save.failed", ok=False, exc=True, error=str(e))
        raise HTTPException(status_code=500, detail=f"会话保存失败: {e}")


@app.post("/api/sessions/{sid}/messages")
def api_append_session_message(sid: str, req: SessionExchange, request: Request):
    """向已有线程追加一轮问答（同一线程连问不分家），返回轻量线程行。
    只允许追加到自己的线程（服务端按登录身份校验归属）。"""
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    try:
        item = sessiondb.append_exchange(
            sid, query, req.result, req.elapsed_ms, req.ask, user_id=_uid_of(request)
        )
    except Exception as e:  # noqa: BLE001
        monitor.step("api", "session.save.failed", ok=False, exc=True, error=str(e))
        raise HTTPException(status_code=500, detail=f"会话追加失败: {e}")
    if item is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return item


@app.get("/api/sessions")
def api_list_sessions(request: Request, limit: int = sessiondb.MAX_CHATS, kind: str = "all"):
    """侧栏列表：只返回**当前登录用户**自己的会话（admin 的全局视图走 /api/admin/sessions）。
    轻量行不含报告快照（doc_json 一份几百 KB），详情走 /api/sessions/{id}。"""
    return {"sessions": sessiondb.list_threads(limit, kind, user_id=_uid_of(request))}


@app.get("/api/sessions/{sid}")
def api_session_detail(sid: str, request: Request):
    """详情：对话给消息数组；报告给 {query, meta, doc 快照}。
    普通用户只能看自己的；admin 可看任意人的（诚实口径：管理权限，非越权漏洞）。"""
    user = _identity(request)
    is_admin = bool(user and user.get("role") == "admin")
    item = sessiondb.get_thread(sid, user_id=None if is_admin else _uid_of(request))
    if item is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return item


@app.delete("/api/sessions/{sid}")
def api_delete_session(sid: str, request: Request):
    """删单条：删对话时其报告只断链（chat_id 置 NULL）不删除；删报告只删自己。
    普通用户只能删自己的；admin 可删任何人的。"""
    user = _identity(request)
    is_admin = bool(user and user.get("role") == "admin")
    return {"deleted": sessiondb.delete(sid, user_id=None if is_admin else _uid_of(request))}


@app.delete("/api/sessions")
def api_clear_sessions(request: Request):
    """清空**当前用户自己**的全部历史会话（admin 想全站清空走 /api/admin/sessions）。"""
    return {"cleared": sessiondb.clear(user_id=_uid_of(request))}


# ---------- 管理员接口（仅 role=admin；X-Access-Code 运维通道同样放行） ----------

class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"
    display_name: str | None = None


class AdminUserPatch(BaseModel):
    disabled: bool | None = None
    password: str | None = None
    role: str | None = None
    display_name: str | None = None
    # 免费试用额度：置 true 把该账号已用次数清零（客户联系后「再给 3 次」用这个）
    reset_trial: bool = False


def _user_rows_with_stats() -> list[dict]:
    """用户表 + 各自会话统计（chats/reports/last_active），管理面板一次取全。"""
    stats = sessiondb.counts_by_user()
    rows = []
    for u in userdb.list_users():
        s = stats.get(u["id"], {"chats": 0, "reports": 0, "last_active": None})
        rows.append({**u, **s})
    orphan = stats.get("_orphan")
    if orphan and (orphan["chats"] or orphan["reports"]):
        rows.append({
            "id": "_orphan", "username": "（无归属）", "role": "-", "display_name": None,
            "created_at": None, "last_login_at": None, "disabled": 0, **orphan,
        })
    return rows


@app.get("/api/admin/overview")
def admin_overview(request: Request):
    """管理台总览：用户数、会话/报告总量、每用户统计。"""
    _require_admin(request)
    rows = _user_rows_with_stats()
    real = [r for r in rows if r["id"] != "_orphan"]
    return {
        "users": len(real),
        "chats": sum(r["chats"] for r in rows),
        "reports": sum(r["reports"] for r in rows),
        "per_user": rows,
    }


@app.get("/api/admin/users")
def admin_list_users(request: Request):
    """用户管理列表（含会话统计）。"""
    _require_admin(request)
    return {"users": _user_rows_with_stats()}


@app.post("/api/admin/users")
def admin_create_user(req: AdminUserCreate, request: Request):
    """建号（管理员建号制：不开自助注册）。"""
    admin = _require_admin(request)
    try:
        user = userdb.create_user(req.username, req.password, req.role, req.display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    monitor.step("api", "admin.user.created", by=admin["username"], user=user["username"], role=user["role"])
    return {"user": _public_user(user)}


@app.patch("/api/admin/users/{uid}")
def admin_patch_user(uid: str, req: AdminUserPatch, request: Request):
    """改用户：禁用/启用、重置密码、改角色、改显示名。含自我保护与最后管理员保护。"""
    admin = _require_admin(request)
    if req.disabled and uid == admin["id"]:
        raise HTTPException(status_code=400, detail="不能禁用自己的账号")
    if req.role == "user":
        target = userdb.get_by_id(uid)
        if target and target["role"] == "admin":
            admins = [u for u in userdb.list_users() if u["role"] == "admin" and not u["disabled"]]
            if len(admins) <= 1:
                raise HTTPException(status_code=400, detail="不能降级最后一名管理员")
    try:
        user = userdb.update_user(uid, req.disabled, req.password, req.role, req.display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.reset_trial:
        userdb.reset_trial(uid)
        monitor.step("api", "admin.trial.reset", by=admin["username"], user=user["username"])
    return {"user": _public_user(user), "trial_used": userdb.trial_used_of(uid)}


@app.delete("/api/admin/users/{uid}")
def admin_delete_user(uid: str, request: Request):
    """删用户。保护：不能删自己、不能删最后一名管理员。
    其名下会话**转给操作者**而非删除（保数据，可再转出）。"""
    admin = _require_admin(request)
    if uid == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    target = userdb.get_by_id(uid)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target["role"] == "admin":
        admins = [u for u in userdb.list_users() if u["role"] == "admin" and not u["disabled"]]
        if len(admins) <= 1:
            raise HTTPException(status_code=400, detail="不能删除最后一名管理员")
    transferred = sessiondb.reassign(uid, admin["id"])
    userdb.delete_user(uid)
    monitor.step("api", "admin.user.deleted", by=admin["username"], user=target["username"],
                 transferred=transferred)
    return {"deleted": True, "transferred_sessions": transferred}


@app.get("/api/admin/sessions")
def admin_list_sessions(
    request: Request,
    user_id: str | None = None,
    kind: str = "all",
    limit: int = 50,
):
    """全局会话视图：admin 可按用户过滤查看（user_id 缺省 = 全部）。"""
    _require_admin(request)
    return {"sessions": sessiondb.list_threads(limit, kind, user_id=user_id or None)}


@app.delete("/api/admin/sessions/{sid}")
def admin_delete_session(sid: str, request: Request):
    """admin 删除任意一条会话/报告。"""
    _require_admin(request)
    return {"deleted": sessiondb.delete(sid)}


@app.delete("/api/admin/sessions")
def admin_clear_sessions(request: Request):
    """admin 清空**全站**会话（侧栏的「清空」只影响当前用户自己）。"""
    _require_admin(request)
    return {"cleared": sessiondb.clear()}


@app.get("/api/analyze/stream")
async def api_analyze_stream(query: str, request: Request, max_results: int = 200, include_review: bool = True):
    """SSE 流式分析（EventSource 友好：GET + text/event-stream）。

    事件协议（data: {json} 每行一条）：
      start        {request_id}
      stage        {key,label,status:running|done|error,ms?,detail?} —— 与 5 张工具卡的映射在前端
      review_delta {text}                                           —— 综述逐字增量
      done         {payload}                                        —— 与 POST /api/analyze 同一返回契约
      word_zh      {map}  —— done 之后补发的词云/主题词中文译名（不拖慢主链路；失败则不发）
      end          —— 全部事件发完，前端据此关闭连接（防止浏览器自动重连）
      error        {message}

    设计决策：新增独立端点而非改造 POST /api/analyze——旧端点被报告页与
    scripts/precache.py 依赖，属已验证链路；pipeline 通过可选 on_event 回调外发事件，
    不传时行为与旧版完全一致（最小侵入）。事件经 asyncio.Queue 从回调桥接到响应生成器。
    """
    query = (query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    max_results = max(1, min(max_results, config.MAX_RESULTS))

    # 试用额度（放行时已扣一次）。注意：EventSource 读不到非 2xx 的响应体，
    # 所以这里不能靠 HTTP 403 传递提示——直接回一条 error 事件，
    # 前端复用已有的错误提示位把「请联系管理员 QQ…」原样显示出来。
    deny = _trial_gate(request)
    if deny:
        async def denied():
            yield f"data: {json.dumps({'type': 'error', 'message': deny['message'], 'code': 'trial_limit'}, ensure_ascii=False)}\n\n"
            yield 'data: {"type": "end"}\n\n'

        return StreamingResponse(
            denied(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    rid = monitor.set_request_id()

    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        task: asyncio.Task | None = None

        def sse(obj: dict) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        try:
            yield sse({"type": "start", "request_id": rid})
            key = cache.cache_key(query, max_results, include_review)
            payload: dict | None = None

            # 缓存命中：不重跑，按 trace 秒发阶段事件（与同步端点同款语义）
            if key in _cache:
                payload = {**_cache[key], "cached": True, "request_id": rid}
                for t in payload.get("trace") or []:
                    yield sse({
                        "type": "stage",
                        "key": t.get("stage"),
                        "label": t.get("label"),
                        "status": "done" if t.get("ok", True) else "error",
                        "ms": t.get("ms"),
                        "detail": t.get("detail"),
                    })
            else:
                def on_event(ev: dict) -> None:
                    queue.put_nowait(ev)

                async def run() -> None:
                    try:
                        p = await pipeline.build_payload(
                            query, max_results, include_review, on_event=on_event
                        )
                    except Exception as e:  # noqa: BLE001
                        monitor.step("api", "stream.failed", ok=False, exc=True, query=query, error=str(e))
                        await queue.put({"type": "error", "message": str(e)})
                        return
                    p["request_id"] = rid
                    _cache[key] = p
                    if p.get("total", 0) > 0:
                        _persist_cache(key, p)
                    await queue.put({"type": "done", "payload": p})

                task = asyncio.create_task(run())
                while True:
                    ev = await queue.get()
                    if ev["type"] == "done":
                        payload = ev["payload"]
                        break
                    yield sse(ev)

            if payload is None:
                return
            yield sse({"type": "done", "payload": payload})

            # 词云/主题词中文化（用户拍板：done 之后单独补发，不拖慢分析主链路）。
            # 词典命中 0ms；未命中走一次批量机翻并落库；失败就保持英文，绝不阻塞。
            if config.WORD_ZH:
                try:
                    zh = await wordzh.translate_payload(payload)
                    if zh:
                        wordzh.attach(zh, payload)  # 同时写回缓存体，后续请求直接带中文
                        yield sse({"type": "word_zh", "map": zh})
                except Exception as e:  # noqa: BLE001
                    monitor.step("wordzh", "payload.failed", ok=False, exc=True, error=str(e))
            yield sse({"type": "end"})
        finally:
            # 客户端中途断开时取消仍在跑的分析任务，避免空转占用 NCBI/LLM 配额
            if task is not None and not task.done():
                task.cancel()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/logs")
def api_logs(tail: int = 100):
    """查看最近的监控日志（决策 D2）：返回当前 app 日志最后 N 行，便于现场排障。"""
    tail = max(1, min(tail, 500))
    log_dir = config.LOG_DIR
    files = sorted(glob.glob(os.path.join(log_dir, "app*.log")))
    if not files:
        return {"file": None, "lines": []}
    latest = files[-1]
    try:
        with open(latest, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return {"file": os.path.basename(latest), "lines": []}
    return {"file": os.path.basename(latest), "lines": [ln.rstrip("\n") for ln in lines[-tail:]]}


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest, request: Request):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    max_results = max(1, min(req.max_results, config.MAX_RESULTS))

    # request_id 贯穿本次请求的所有日志；响应体也带上，排障时报这个码即可
    rid = monitor.set_request_id()
    monitor.step("api", "request.start", query=query, retmax=max_results,
                 review=req.include_review, client=request.client.host if request.client else None)

    # 试用额度：放在缓存判断之前——用户视角「我提了一次分析」就是一次，
    # 命不命中预缓存不影响计数（否则清缓存/换词就能绕过限制）。
    deny = _trial_gate(request)
    if deny:
        # detail 里带完整提示 + 结构化字段，前端直接把 message 显示出来
        raise HTTPException(status_code=403, detail=deny["message"],
                            headers={"X-Trial-Remaining": "0"})

    key = cache.cache_key(query, max_results, req.include_review)
    if key in _cache:
        # 命中预缓存：保留生成时的真实 trace，仅标记来源，前端据此显示「预缓存秒回」
        monitor.step("api", "cache.hit", key=key)
        payload = _cache[key]
        # 词云/主题词中文化：报告页走非流式，装配响应时内联补译（词典命中 0ms，失败保持英文）
        if config.WORD_ZH:
            try:
                wordzh.attach(await wordzh.translate_payload(payload), payload)
            except Exception as e:  # noqa: BLE001
                monitor.step("wordzh", "payload.failed", ok=False, exc=True, error=str(e))
        return {**payload, "cached": True, "request_id": rid}

    # 全流程交给 pipeline，接口层只负责参数校验与缓存
    try:
        payload = await pipeline.build_payload(query, max_results, req.include_review)
    except Exception as e:  # noqa: BLE001
        monitor.step("api", "pipeline.failed", ok=False, exc=True, query=query, error=str(e))
        raise HTTPException(status_code=502, detail=f"分析流水线失败（request_id: {rid}）: {e}")

    # 词云/主题词中文化（同上：best-effort，不阻塞响应）
    if config.WORD_ZH:
        try:
            wordzh.attach(await wordzh.translate_payload(payload), payload)
        except Exception as e:  # noqa: BLE001
            monitor.step("wordzh", "payload.failed", ok=False, exc=True, error=str(e))

    _cache[key] = payload
    # 0 命中的结果只进内存缓存（重启即失效），不落文件——否则空结果被固化，
    # 后续改进（如中文改写上线）也永远轮不到跑，实测踩过的坑。
    if payload.get("total", 0) > 0:
        _persist_cache(key, payload)

    payload["request_id"] = rid
    monitor.step("api", "request.done", total=payload.get("total"),
                 cached=False, elapsed_ms=payload.get("trace") and sum(
                     t.get("ms", 0) for t in payload["trace"]))
    return payload


@app.on_event("startup")
def _warm():
    import importlib

    monitor.setup(
        level=config.LOG_LEVEL,
        log_dir=config.LOG_DIR,
        retention_app=config.LOG_RETENTION_DAYS_APP,
        retention_error=config.LOG_RETENTION_DAYS_ERROR,
    )
    monitor.step("api", "startup", presets=config.PRESETS,
                 query_rewrite=config.QUERY_REWRITE)
    importlib.import_module("app.metrics").load()
    _load_file_cache()
    sessiondb.connect().close()  # 确保 sessions.db schema 早期就绪

    # 用户体系（2026-09-20 拍板）：首启自动建管理员；存量无归属会话划给管理员。
    # 划归放在 connect() 之后，保证 user_id 列已补齐（迁移失败不阻塞启动）。
    try:
        admin = userdb.bootstrap()
        if admin:
            monitor.step("startup", "admin.bootstrapped", username=admin["username"])
        owner = (
            userdb.get_by_username(config.ADMIN_USERNAME)
            if config.ADMIN_USERNAME
            else None
        ) or userdb.first_admin()
        if owner:
            moved = sessiondb.claim_orphans(owner["id"])
            if moved:
                monitor.step("startup", "sessions.claimed", count=moved, owner=owner["username"])
    except Exception as e:  # noqa: BLE001
        monitor.warning("startup", "userdb.failed", error=str(e))

    # 首次部署（literature.db 是新建的、term_mapping 为空）时导入随包发布的中文术语种子；
    # 否则所有中文提问都会退化到大模型改写（多一次调用，且失去无 key / 断网时的兜底）。
    try:
        from . import literaturedb

        conn = literaturedb.connect()
        try:
            added = literaturedb.seed_mappings(conn)
            if added:
                monitor.step("startup", "term_seed.loaded", count=added)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        monitor.warning("startup", "term_seed.failed", error=str(e))


# 单端口部署：把前端构建产物挂到根路径（必须在所有 /api 路由之后注册，二者互不抢占）。
# 目录不存在时跳过——本地开发时前端由 Vite 提供，不受影响。
_dist = config.FRONTEND_DIST
if _dist and os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="spa")


def main():
    host = os.getenv("HOST", "127.0.0.1")  # 容器内需 0.0.0.0
    port = int(os.getenv("PORT", "8000"))  # 云平台/容器以 PORT 注入
    uvicorn.run("app.main:app", host=host, port=port, reload=False, proxy_headers=True)


if __name__ == "__main__":
    main()
