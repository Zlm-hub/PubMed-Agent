"""历史会话库 v3（sessions.db）：对话线程 + 报告文档，两者可关联。

数据模型（2026-09-19 第三次演进，用户拍板）：
  - **一张表承载两类记录**，用 kind 区分：
      kind='chat'   = 对话线程（正文在 chat_messages，多轮问答）
      kind='report' = 报告文档（正文是该次分析的**全量快照 doc_json**，含 200 篇文献）
    为什么不分两张表：它们在数据上是同一种东西——"一次带主题的分析记录"，
    差别只在呈现形态；一张表让侧栏混排、按时间排序、统计与清理都只写一遍。
  - **报告可关联来源对话**：chat_id 指向产生它的 chat 线程（独立报告为 NULL）。
      · 从属报告：对话里点「生成报告」→ chat_id=<原对话>
      · 独立报告：报告页/首页直接搜索生成 → chat_id=NULL
      · **删除对话时报告不删，只把 chat_id 置 NULL**（SET NULL）——防止误删对话
        把辛苦生成的报告一起带走；报告降级为独立报告。
  - **复用键 = (chat_id, query)**：同一对话的同一主题、或独立报告的同一主题只留一条，
    重复点「生成报告」是更新而非新增（不堆重复，也不会意外改挂到别的对话）。

为什么独立成库（对齐 literature.db / journal_metrics.db 的分库思路）：
  会话数据由前端交互驱动写入、可整体清空、丢了自己能重搜再生；与文献库
  「不可再生的积累」生命周期不同，分开便于各自清理与迁移。

v1 → v2 → v3 迁移：connect() 时先跑 v1→v2（旧 query/result_json 结构），
再对已有库逐列 ADD COLUMN 补 kind/query/chat_id/meta_json/doc_json，
并按首条提问回填 chat 的 query。全程 ADD COLUMN，老数据一条不丢。
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "sessions.db")
)

# 两类记录各自保留的上限（超出挤掉最旧的；对话被挤掉时其报告同样只断链不删）
MAX_CHATS = 12
MAX_REPORTS = 12

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'chat',
    query      TEXT,
    chat_id    TEXT,
    meta_json  TEXT,
    doc_json   TEXT,
    user_id    TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES chat_sessions(id),
    role         TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
"""

# 索引必须等补列完成后再建：已有库的 chat_sessions 上还没有 kind 列，
# 若与建表脚本一起执行会报「no such column: kind」（实测踩过）。
SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS ix_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS ix_sessions_kind ON chat_sessions(kind);
CREATE INDEX IF NOT EXISTS ix_sessions_chat ON chat_sessions(chat_id);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON chat_sessions(user_id);
"""

# 新增列（对已有库逐列 ADD COLUMN，全程老数据一条不丢）。
# user_id（2026-09-20 用户拍板）：会话按用户隔离；NULL = 本地开放模式产生的历史数据，
# 首启时由 main.py 调 claim_orphans() 统一划给管理员。
_V3_COLUMNS: tuple[tuple[str, str], ...] = (
    ("kind", "TEXT NOT NULL DEFAULT 'chat'"),
    ("query", "TEXT"),
    ("chat_id", "TEXT"),
    ("meta_json", "TEXT"),
    ("doc_json", "TEXT"),
    ("user_id", "TEXT"),
)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """v1（问题即会话）→ v2（线程 + 消息）：检测旧列，存在则整体搬迁。"""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()]
    if not cols or "query" not in cols:
        return
    rows = conn.execute(
        "SELECT id, title, query, result_json, elapsed_ms, created_at, updated_at FROM chat_sessions"
    ).fetchall()
    conn.execute("DROP TABLE IF EXISTS chat_sessions_v1_backup")
    conn.execute("ALTER TABLE chat_sessions RENAME TO chat_sessions_v1_backup")
    conn.executescript(SCHEMA)
    conn.executescript(SCHEMA_INDEXES)
    for r in rows:
        conn.execute(
            """INSERT INTO chat_sessions (id, title, created_at, updated_at, kind, query)
               VALUES (?,?,?,?, 'chat', ?)""",
            (r["id"], r["title"], r["created_at"], r["updated_at"], r["query"]),
        )
        try:
            result = json.loads(r["result_json"] or "null")
        except json.JSONDecodeError:
            result = None
        if result:
            conn.execute(
                "INSERT INTO chat_messages (session_id, role, content_json, created_at) VALUES (?,?,?,?)",
                (r["id"], "user", json.dumps({"text": r["query"]}, ensure_ascii=False), r["created_at"]),
            )
            conn.execute(
                "INSERT INTO chat_messages (session_id, role, content_json, created_at) VALUES (?,?,?,?)",
                (
                    r["id"],
                    "assistant",
                    json.dumps({"result": result, "elapsed_ms": r["elapsed_ms"]}, ensure_ascii=False),
                    r["updated_at"],
                ),
            )
    conn.commit()


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """v2（只有 thread/messages）→ v3：补列 + 回填 chat 的 query。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()}
    added = False
    for name, ddl in _V3_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE chat_sessions ADD COLUMN {name} {ddl}")
            added = True
    if added:
        conn.commit()
    # 老对话没有 query：用首条提问回填（展示与关联都要用）
    rows = conn.execute(
        "SELECT id FROM chat_sessions WHERE kind = 'chat' AND (query IS NULL OR query = '')"
    ).fetchall()
    for r in rows:
        m = conn.execute(
            "SELECT content_json FROM chat_messages WHERE session_id = ? AND role = 'user' ORDER BY id LIMIT 1",
            (r["id"],),
        ).fetchone()
        text = ""
        if m:
            try:
                text = (json.loads(m["content_json"]) or {}).get("text") or ""
            except json.JSONDecodeError:
                text = ""
        if text:
            conn.execute("UPDATE chat_sessions SET query = ? WHERE id = ?", (text, r["id"]))
    conn.commit()


def connect(path: str = None) -> sqlite3.Connection:
    """打开连接：schema 就绪 + 逐级迁移（v1→v2→v3）。迁移失败不阻塞启动。"""
    p = path or DB_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        _migrate_v1(conn)
    except Exception:  # noqa: BLE001
        conn.rollback()
    conn.executescript(SCHEMA)
    try:
        _migrate_v3(conn)
    except Exception:  # noqa: BLE001
        conn.rollback()
    # 索引放在补列之后建（已有库此时才有 kind 列）
    conn.executescript(SCHEMA_INDEXES)
    return conn


# ---------- 通用 ----------

def _light(row: sqlite3.Row, exchanges: int = 0) -> dict:
    """列表轻量行：不含 doc_json（一份几百 KB）。"""
    meta = None
    if row["meta_json"]:
        try:
            meta = json.loads(row["meta_json"])
        except json.JSONDecodeError:
            meta = None
    return {
        "id": row["id"],
        "kind": row["kind"] or "chat",
        "title": row["title"],
        "ts": row["updated_at"],
        "query": row["query"],
        "chat_id": row["chat_id"],
        "meta": meta,
        "exchanges": exchanges,
        "user_id": row["user_id"] if "user_id" in row.keys() else None,
    }


def _trim(conn: sqlite3.Connection, user_id: str | None = None) -> None:
    """两类各自限量；被挤掉的对话，其报告只断链不删除。

    2026-09-20 起上限按**用户**各自计算（每个用户自己的 12 条对话 / 12 条报告）；
    user_id=None（本地开放模式）时退化为全局限量，与旧行为一致。
    """
    for kind, cap in (("chat", MAX_CHATS), ("report", MAX_REPORTS)):
        sql = "SELECT id FROM chat_sessions WHERE kind = ?"
        args: list = [kind]
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        sql += " ORDER BY updated_at DESC LIMIT -1 OFFSET ?"
        args.append(cap)
        old_ids = [r["id"] for r in conn.execute(sql, args)]
        for sid in old_ids:
            if kind == "chat":
                conn.execute("UPDATE chat_sessions SET chat_id = NULL WHERE chat_id = ?", (sid,))
                conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM chat_sessions WHERE id = ?", (sid,))


# ---------- 对话（kind='chat'） ----------

def create_thread(
    query: str,
    result: dict,
    elapsed_ms: int | None = None,
    title: str | None = None,
    ask: str | None = None,
    user_id: str | None = None,
) -> dict:
    """新建对话线程并写入第一轮问答，返回轻量行。

    ask = 用户原话（未经关键词提取）。**用户消息气泡必须存原话**：
    query 只是实际检索词（提取/改写后的），若用它当提问文本，历史还原时
    会给用户"我的问题被改成了关键词"的错觉（2026-09-19 用户实测反馈）。

    user_id：会话归属（2026-09-20 起按用户隔离）；None = 本地开放模式（暂无归属）。
    """
    conn = connect()
    try:
        now = _now()
        sid = uuid.uuid4().hex[:12]
        conn.execute(
            """INSERT INTO chat_sessions (id, title, created_at, updated_at, kind, query, user_id)
               VALUES (?,?,?,?, 'chat', ?, ?)""",
            (sid, title or query, now, now, query, user_id),
        )
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content_json, created_at) VALUES (?,?,?,?)",
            (sid, "user", json.dumps({"text": ask or title or query}, ensure_ascii=False), now),
        )
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content_json, created_at) VALUES (?,?,?,?)",
            (sid, "assistant", json.dumps({"result": result, "elapsed_ms": elapsed_ms}, ensure_ascii=False), now),
        )
        _trim(conn, user_id)
        conn.commit()
        row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (sid,)).fetchone()
        return _light(row, exchanges=1)
    finally:
        conn.close()


def append_exchange(
    session_id: str,
    query: str,
    result: dict,
    elapsed_ms: int | None = None,
    ask: str | None = None,
    user_id: str | None = None,
) -> dict | None:
    """向已有对话线程追加一轮问答。线程不存在（或不是对话）返回 None。

    ask = 用户原话：用户消息气泡存原话，query 只作检索词（同 create_thread 的口径）。
    user_id 非空时做**归属校验**：只允许追加到自己的线程（防止拿到别人的线程 id
    就能往里塞内容——隔离不只管读，也管写）。
    """
    conn = connect()
    try:
        sql = "SELECT id, title FROM chat_sessions WHERE id = ? AND kind = 'chat'"
        args: list = [session_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        row = conn.execute(sql, args).fetchone()
        if row is None:
            return None
        now = _now()
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content_json, created_at) VALUES (?,?,?,?)",
            (session_id, "user", json.dumps({"text": ask or query}, ensure_ascii=False), now),
        )
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content_json, created_at) VALUES (?,?,?,?)",
            (session_id, "assistant", json.dumps({"result": result, "elapsed_ms": elapsed_ms}, ensure_ascii=False), now),
        )
        conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        count = conn.execute(
            "SELECT COUNT(*) c FROM chat_messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()["c"]
        _trim(conn, user_id)
        conn.commit()
        row2 = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        return _light(row2, exchanges=count)
    finally:
        conn.close()


# ---------- 报告（kind='report'） ----------

def save_report(
    query: str,
    doc: dict,
    meta: dict | None = None,
    chat_id: str | None = None,
    title: str | None = None,
    user_id: str | None = None,
) -> dict:
    """新建/复用报告记录（全量快照）。

    复用键 = (user_id, chat_id, query)：同一用户、同一对话的同一主题（或独立报告的
    同一主题）只留一条——两个用户各搜「肺癌」应各自成文，不能互相覆盖。
    重复点「生成报告」是更新而非新增，且不会把报告从原对话改挂到别处。
    """
    conn = connect()
    try:
        now = _now()
        owner_sql = "user_id = ?" if user_id is not None else "user_id IS NULL"
        if chat_id:
            existing = conn.execute(
                f"SELECT id, created_at FROM chat_sessions WHERE kind='report' AND query=?"
                f" AND chat_id=? AND {owner_sql}",
                (query, chat_id, user_id) if user_id is not None else (query, chat_id),
            ).fetchone()
        else:
            existing = conn.execute(
                f"SELECT id, created_at FROM chat_sessions WHERE kind='report' AND query=?"
                f" AND chat_id IS NULL AND {owner_sql}",
                (query, user_id) if user_id is not None else (query,),
            ).fetchone()
        sid = existing["id"] if existing else uuid.uuid4().hex[:12]
        created = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT INTO chat_sessions (id, title, created_at, updated_at, kind, query, chat_id, meta_json, doc_json, user_id)
            VALUES (?,?,?,?, 'report', ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                updated_at = excluded.updated_at,
                meta_json = excluded.meta_json,
                doc_json = excluded.doc_json
            """,
            (
                sid,
                title or query,
                created,
                now,
                query,
                chat_id,
                json.dumps(meta or {}, ensure_ascii=False),
                json.dumps(doc, ensure_ascii=False),
                user_id,
            ),
        )
        _trim(conn, user_id)
        conn.commit()
        row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (sid,)).fetchone()
        return _light(row)
    finally:
        conn.close()


# ---------- 查询 ----------

def list_threads(limit: int = MAX_CHATS, kind: str = "all", user_id: str | None = None) -> list[dict]:
    """侧栏列表（两类混排，按更新时间倒序）。kind 可选 all/chat/report。

    user_id 非空 = 只看该用户的（普通用户侧栏）；None = 不过滤（admin 全局视图 /
    本地开放模式的历史行为）。
    """
    conn = connect()
    try:
        where, args = [], []
        if kind in ("chat", "report"):
            where.append("s.kind = ?")
            args.append(kind)
        if user_id is not None:
            where.append("s.user_id = ?")
            args.append(user_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = conn.execute(
            f"""
            SELECT s.*, (SELECT COUNT(*) FROM chat_messages m
                          WHERE m.session_id = s.id AND m.role = 'user') AS exchanges
            FROM chat_sessions s {clause}
            ORDER BY s.updated_at DESC LIMIT ?
            """,
            (*args, max(1, min(limit, 50))),
        ).fetchall()
        return [_light(r, r["exchanges"]) for r in rows]
    finally:
        conn.close()


def get_thread(session_id: str, user_id: str | None = None) -> dict | None:
    """详情：对话给消息数组；报告给 query/meta/快照(=doc)。不存在返回 None。

    user_id 非空时做归属校验：别人的会话按「不存在」处理（不泄露存在性）。
    """
    conn = connect()
    try:
        sql = "SELECT * FROM chat_sessions WHERE id = ?"
        args: list = [session_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        s = conn.execute(sql, args).fetchone()
        if s is None:
            return None
        out = _light(s)
        if (s["kind"] or "chat") == "chat":
            msgs = conn.execute(
                "SELECT role, content_json FROM chat_messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            messages = []
            for m in msgs:
                try:
                    content = json.loads(m["content_json"])
                except json.JSONDecodeError:
                    continue
                messages.append({"role": m["role"], "content": content})
            out["messages"] = messages
        else:
            try:
                out["doc"] = json.loads(s["doc_json"] or "null")
            except json.JSONDecodeError:
                out["doc"] = None
        return out
    finally:
        conn.close()


# ---------- 删除 ----------

def delete(session_id: str, user_id: str | None = None) -> bool:
    """删单条。删对话 → 其报告只断链（chat_id 置 NULL）不删除；删报告 → 只删自己。

    user_id 非空时只允许删自己的记录（普通用户）；None = 不过滤（admin / 开放模式）。
    """
    conn = connect()
    try:
        sql = "SELECT kind FROM chat_sessions WHERE id = ?"
        args: list = [session_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        row = conn.execute(sql, args).fetchone()
        if row is None:
            return False
        if (row["kind"] or "chat") == "chat":
            conn.execute("UPDATE chat_sessions SET chat_id = NULL WHERE chat_id = ?", (session_id,))
            conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        cur = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear(user_id: str | None = None) -> int:
    """清空。user_id 非空 = 只清该用户自己的（侧栏「清空」按钮）；None = 全部（admin 面板）。"""
    conn = connect()
    try:
        if user_id is None:
            conn.execute("DELETE FROM chat_messages")
            cur = conn.execute("DELETE FROM chat_sessions")
        else:
            conn.execute(
                "DELETE FROM chat_messages WHERE session_id IN"
                " (SELECT id FROM chat_sessions WHERE user_id = ?)",
                (user_id,),
            )
            cur = conn.execute("DELETE FROM chat_sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ---------- 归属迁移与管理统计（2026-09-20 用户体系） ----------

def claim_orphans(owner_user_id: str) -> int:
    """把 user_id 为 NULL 的存量会话划给指定用户（首启时划给管理员，用户拍板）。"""
    conn = connect()
    try:
        cur = conn.execute(
            "UPDATE chat_sessions SET user_id = ? WHERE user_id IS NULL", (owner_user_id,)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def reassign(from_user_id: str, to_user_id: str) -> int:
    """把某用户的全部会话划给另一用户（删除用户时保数据：转给操作的管理员）。"""
    conn = connect()
    try:
        cur = conn.execute(
            "UPDATE chat_sessions SET user_id = ? WHERE user_id = ?",
            (to_user_id, from_user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def counts_by_user() -> dict:
    """按用户聚合会话/报告数与最近活跃时间。键为 user_id（NULL 归到字符串 'None' 桶）。"""
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT user_id, kind, COUNT(*) AS n, MAX(updated_at) AS last
               FROM chat_sessions GROUP BY user_id, kind"""
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict] = {}
    for r in rows:
        key = r["user_id"] if r["user_id"] is not None else "_orphan"
        bucket = out.setdefault(key, {"chats": 0, "reports": 0, "last_active": None})
        if (r["kind"] or "chat") == "chat":
            bucket["chats"] = r["n"]
        else:
            bucket["reports"] = r["n"]
        if r["last"] and (bucket["last_active"] is None or r["last"] > bucket["last_active"]):
            bucket["last_active"] = r["last"]
    return out
