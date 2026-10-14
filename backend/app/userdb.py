"""用户库 v1（users.db）：账号、角色与登录态（2026-09-20 拍板：管理员建号制）。

为什么独立成库：账号数据与文献库/会话库生命周期不同——文献库不可再生、会话库
可整体清空，账号库则要求**删会话/清库绝不动账号**。分库后互不影响（对齐既有分库思路）。

关键决策（均可核对）：
  - **密码存 PBKDF2-HMAC-SHA256**（10 万轮 + 16 字节随机盐），格式
    `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`。纯标准库零新依赖；
    即便 users.db 泄露，口令也无法被直接还原。
  - **登录态 = HMAC 签名 token cookie**（`<user_id>.<过期时间戳>.<签名>`）：
    无状态、无需服务端会话表；每次请求解签后回查用户行，禁用/删除即时生效。
    已知边界（诚实声明）：改密不会让已签发的旧 token 立即失效（30 天内有效），
    需要立即踢出某用户时用「禁用」。
  - **签名密钥**：优先取 AUTH_SECRET env；未配置则首次生成 64 位 hex 落盘
    data/auth_secret.key——保证重启后已登录用户不掉线（服务器容器重启常见）。
  - **管理员建号制**：不开放注册。users 表为空且配置了 ADMIN_USERNAME/ADMIN_PASSWORD
    时首启自动建 role='admin' 管理员；普通用户只能由管理员在管理后台创建。
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone

from . import config

DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "users.db")
)

# 密钥文件（AUTH_SECRET 未配置时的兜底）：放 data/ 目录，与三个业务库同处、随卷持久化
_SECRET_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "auth_secret.key")
)

PBKDF2_ITERATIONS = 100_000
TOKEN_TTL = 60 * 60 * 24 * 30  # 登录态 30 天

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',
    display_name  TEXT,
    created_at    TEXT NOT NULL,
    last_login_at TEXT,
    disabled      INTEGER NOT NULL DEFAULT 0,
    source        TEXT
);
"""

# 老库补列（ADD COLUMN，老数据一条不丢）。
#   source     = 建号来源（注册时的 UA + 来源 IP，或「后台建号」标记）——能追溯"这账号谁建的、从哪来"。
#   trial_used = 免费试用已用次数（2026-09-21 服务器版额度限制；0 = 没用过）。
#                额度只在 FREE_TRIAL_LIMIT>0 时生效，本地默认不启用、这列一直为 0。
_MIGRATE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source", "TEXT"),
    ("trial_used", "INTEGER NOT NULL DEFAULT 0"),
)

# 用户名：2~32 位，中文/字母/数字/下划线/点/短横线/空格（中文用户名是真实需求）
_USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fff .\-]{2,32}$", re.UNICODE)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(path: str = None) -> sqlite3.Connection:
    p = path or DB_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    added = False
    for name, ddl in _MIGRATE_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
            added = True
    if added:
        conn.commit()
    return conn


# ---------- 密码 ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """格式不符（例如手改库）一律按不匹配处理，绝不抛异常打断请求。"""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# ---------- 签名密钥与 token ----------

def _secret() -> bytes:
    if config.AUTH_SECRET:
        return config.AUTH_SECRET.encode("utf-8")
    try:
        with open(_SECRET_PATH, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key.encode("utf-8")
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(_SECRET_PATH), exist_ok=True)
        with open(_SECRET_PATH, "w", encoding="utf-8") as f:
            f.write(key)
    except OSError:
        pass  # 写不进去就每次重启重新生成——掉登录态，但不阻塞服务
    return key.encode("utf-8")


def make_token(user_id: str, ttl: int = TOKEN_TTL) -> str:
    payload = f"{user_id}.{int(time.time()) + ttl}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_token(token: str) -> dict | None:
    """校验签名与有效期，并回查用户行（删除/禁用即时失效）。无效返回 None。"""
    try:
        uid, exp, sig = token.split(".")
    except (ValueError, AttributeError):
        return None
    payload = f"{uid}.{exp}"
    good = hmac.compare_digest(
        hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest(), sig
    )
    if not good:
        return None
    try:
        if int(exp) < time.time():
            return None
    except ValueError:
        return None
    user = get_by_id(uid)
    if user is None or user["disabled"]:
        return None
    return user


# ---------- 用户 CRUD ----------

def _public(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "display_name": row["display_name"],
    }


def count() -> int:
    conn = connect()
    try:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    finally:
        conn.close()


def get_by_id(uid: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_by_username(username: str) -> dict | None:
    """按用户名查（**不区分大小写**：Admin 与 admin 视为同名，防冒充）。"""
    return get_by_username_ci(username)


def get_by_username_ci(username: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", ((username or "").strip(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def authenticate(username: str, password: str) -> dict | None:
    """登录校验：用户不存在/被禁用/密码错统一返回 None（不泄露具体原因）。"""
    if not username or not password:
        return None
    user = get_by_username_ci(username)
    if user is None or user["disabled"]:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def create_user(
    username: str,
    password: str,
    role: str = "user",
    display_name: str | None = None,
    source: str | None = None,
) -> dict:
    """建号（管理员后台与自助注册共用）。用户名重复/格式非法/密码过短抛 ValueError。

    用户名查重走 COLLATE NOCASE——`Admin` 与 `admin` 不能共存，否则登录时无从区分；
    这一检查不加锁，极端并发下有极小概率双写，注册接口另有一层唯一索引兜底。
    """
    username = (username or "").strip()
    if not _USERNAME_RE.match(username):
        raise ValueError("用户名需为 2~32 位中文、字母、数字、下划线、点或短横线")
    if not (6 <= len(password or "") <= 64):
        raise ValueError("密码长度需为 6~64 位")
    if role not in ("admin", "user"):
        raise ValueError("角色只能是 admin 或 user")
    conn = connect()
    try:
        dup = conn.execute(
            "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if dup:
            raise ValueError(f"用户名已存在：{username}")
        uid = uuid.uuid4().hex[:12]
        try:
            conn.execute(
                """INSERT INTO users (id, username, password_hash, role, display_name, created_at, source)
                   VALUES (?,?,?,?,?,?,?)""",
                (uid, username, hash_password(password), role,
                 (display_name or "").strip() or None, _now(), (source or "")[:120] or None),
            )
        except sqlite3.IntegrityError:
            # 并发下两个请求同时通过了查重：唯一索引兜底，如实报"已存在"
            raise ValueError(f"用户名已存在：{username}")
        conn.commit()
        return dict(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())
    finally:
        conn.close()


def update_user(
    uid: str,
    disabled: bool | None = None,
    password: str | None = None,
    role: str | None = None,
    display_name: str | None = None,
) -> dict | None:
    """局部更新。不存在返回 None；参数非法抛 ValueError。"""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if row is None:
            return None
        sets, args = [], []
        if disabled is not None:
            sets.append("disabled = ?")
            args.append(1 if disabled else 0)
        if password is not None:
            if not (6 <= len(password) <= 64):
                raise ValueError("密码长度需为 6~64 位")
            sets.append("password_hash = ?")
            args.append(hash_password(password))
        if role is not None:
            if role not in ("admin", "user"):
                raise ValueError("角色只能是 admin 或 user")
            sets.append("role = ?")
            args.append(role)
        if display_name is not None:
            sets.append("display_name = ?")
            args.append(display_name.strip() or None)
        if sets:
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", (*args, uid))
            conn.commit()
        return dict(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())
    finally:
        conn.close()


def delete_user(uid: str) -> bool:
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def touch_login(uid: str) -> None:
    try:
        conn = connect()
        try:
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_now(), uid))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass  # 最近登录时间写失败不影响登录本身


# ---------- 免费试用额度（2026-09-21：服务器版每账号限 N 次） ----------
#
# 计数放在 users.db 而不是文献库：额度的生命周期与**账号**绑定（删账号即清额度），
# 且 literature.db 里已有全局的 analysis_run 表（不含 user_id），不适合按人累计。

def trial_used_of(uid: str) -> int:
    """该账号已用试用次数（账号不存在返回 0）。"""
    conn = connect()
    try:
        row = conn.execute("SELECT trial_used FROM users WHERE id = ?", (uid,)).fetchone()
        return int(row["trial_used"] or 0) if row else 0
    finally:
        conn.close()


def consume_trial(uid: str, limit: int) -> tuple[bool, int]:
    """原子占用一次额度：返回 (是否放行, 用后次数)。

    limit <= 0 → 不限制也不计数（直接放行）；limit > 0 → 先看是否已满，
    未满则 +1。整段在一个事务里（BEGIN IMMEDIATE），并发下不会超额放行。
    账号不存在时按放行处理（调用方本就有身份校验，这里不制造新的失败面）。
    """
    if limit <= 0:
        return True, trial_used_of(uid)
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT trial_used FROM users WHERE id = ?", (uid,)).fetchone()
        if row is None:
            conn.rollback()
            return True, 0
        used = int(row["trial_used"] or 0)
        if used >= limit:
            conn.commit()
            return False, used
        used += 1
        conn.execute("UPDATE users SET trial_used = ? WHERE id = ?", (used, uid))
        conn.commit()
        return True, used
    except sqlite3.Error:
        # 计数失败绝不该拦住正常分析：放行并如实返回当前值
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return True, 0
    finally:
        conn.close()


def reset_trial(uid: str) -> bool:
    """把某账号的试用计数清零（管理员在后台给客户再开 N 次）。"""
    conn = connect()
    try:
        cur = conn.execute("UPDATE users SET trial_used = 0 WHERE id = ?", (uid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_users() -> list[dict]:
    """管理后台用户表（不含密码哈希；含建号来源 source 与试用次数 trial_used）。"""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, username, role, display_name, created_at, last_login_at, disabled,"
            " source, trial_used FROM users ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def first_admin() -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE role = 'admin' AND disabled = 0 ORDER BY created_at LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def bootstrap() -> dict | None:
    """首启建管理员：仅当 users 表为空且 ADMIN_USERNAME/ADMIN_PASSWORD 均已配置。"""
    if count() > 0:
        return None
    if not (config.ADMIN_USERNAME and config.ADMIN_PASSWORD):
        return None
    try:
        user = create_user(config.ADMIN_USERNAME, config.ADMIN_PASSWORD,
                           role="admin", display_name="管理员")
        return user
    except ValueError:
        return None


# ---------- 导出（本地备份用） ----------

def dump_users() -> str:
    return json.dumps(list_users(), ensure_ascii=False, indent=2)
