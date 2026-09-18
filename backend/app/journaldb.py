"""期刊指标数据库（SQLite）：建表、写入、查询的公共层。

为什么用数据库：
  指标数据集是从外部来源（网站导出的 CSV、开放 API）拉下来的，条目在 3 万量级，
  并且运行时要回答的核心问题是「给定任一 ISSN，这本刊的指标是什么」。
  放进表里并给 ISSN 建索引后，这个查询是一次索引命中，而不是把整份 JSON
  反序列化进内存再查字典；同时每个来源的抓取地址、抓取时间、原始文件校验和
  都留在 dataset_meta 表里，任何时候都能回溯数据是怎么来的。

设计要点：
  1. 只用标准库 sqlite3，不新增第三方依赖（与项目「数据处理走标准库」的约定一致）。
  2. 一个库文件容纳多个数据源，用 source 列区分。**不同来源的指标口径不同，因此分列
     存放、不做合并**：避免「A 源的数值配 B 源的分区」这种静默串味。要对比时按 source 查两行。
  3. ISSN 拆到独立索引表：一本刊常有印刷号 + 电子号，两个来源给出的号码集合也未必相同。
     拆表后 ISSN -> 期刊 是一次索引命中；kind 记下它是印刷号还是电子号。
  4. 刊名归一化复用 app.metrics 的实现（惰性导入，避免与将来改为查库的 metrics.py 形成
     循环依赖），保证「写库时归一化」与「查询时归一化」是同一套规则，不会算法漂移。
"""
import os
import re
import sqlite3

DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "journal_metrics.db")
)

# 来源标识。新增来源时在这里登记，其余代码按字符串透传。
SOURCES = ("scimago", "openalex")

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (
    id              INTEGER PRIMARY KEY,
    source          TEXT    NOT NULL,
    source_id       TEXT,
    name            TEXT    NOT NULL,
    norm_name       TEXT    NOT NULL,
    type            TEXT,
    publisher       TEXT,
    country         TEXT,
    quartile        TEXT,
    quartile_kind   TEXT,
    cites_per_doc_2y REAL,
    sjr             REAL,
    h_index         INTEGER,
    works_count     INTEGER,
    coverage_start  INTEGER,
    coverage_end    INTEGER,
    categories      TEXT,
    areas           TEXT,
    flagged         INTEGER DEFAULT 0,
    retrieved_at    TEXT    NOT NULL,
    UNIQUE (source, source_id)
);

-- 别名索引（ISO 缩写 / 别名 → 期刊）：修「只给缩写的文献匹配不上」缺口。
-- 构建期无缩写数据源时保持空表；运行期学到的别名落 literature.db（指标库只读）。
CREATE TABLE IF NOT EXISTS journal_alias (
    alias_norm TEXT PRIMARY KEY,
    journal_id INTEGER NOT NULL REFERENCES journal(id) ON DELETE CASCADE,
    alias_kind TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_issn (
    issn       TEXT    NOT NULL,
    journal_id INTEGER NOT NULL REFERENCES journal(id) ON DELETE CASCADE,
    kind       TEXT,
    PRIMARY KEY (issn, journal_id)
);

CREATE INDEX IF NOT EXISTS ix_issn      ON journal_issn(issn);
CREATE INDEX IF NOT EXISTS ix_norm_name ON journal(norm_name);
CREATE INDEX IF NOT EXISTS ix_source    ON journal(source, type);

CREATE TABLE IF NOT EXISTS dataset_meta (
    source TEXT NOT NULL,
    key    TEXT NOT NULL,
    value  TEXT,
    PRIMARY KEY (source, key)
);
"""

_YEAR_RE = re.compile(r"\b(1[89]\d{2}|2[01]\d{2})\b")


def norm_name(name: str) -> str:
    """归一化刊名。复用 app.metrics 的实现（惰性导入，规避循环依赖）。"""
    from app.metrics import _norm_name

    return _norm_name(name)


def split_issns(raw) -> list[str]:
    """拆出 8 位 ISSN（去连字符、转大写）。复用 app.metrics 的实现。"""
    from app.metrics import _split_issns

    return _split_issns(raw)


def parse_num(raw):
    """解析来源里的数值。SCImago 用逗号做小数点（104,065 表示 104.065）。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s in {"-", "n/a", "N/A"}:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_coverage(raw) -> tuple:
    """从 Coverage 字段解析出活跃区间 (start, end)。

    该字段写法不规整，实测有 '1857-2026' / '2010-2025' / ', 2021, 2023' / '1, 1883-2026'。
    统一做法是抽出其中所有四位年份，取最小与最大；抽不到则返回 (None, None)。
    """
    if not raw:
        return None, None
    years = [int(y) for y in _YEAR_RE.findall(str(raw))]
    if not years:
        return None, None
    return min(years), max(years)


def connect(path: str = None) -> sqlite3.Connection:
    """打开连接并确保 schema 就绪。外键打开，保证删期刊时 ISSN 索引一并清掉。"""
    p = path or DB_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """老库文件的结构演进：CREATE TABLE IF NOT EXISTS 不会补列，这里显式补。

    flagged（离群标记）只标 openalex 兜底条目：篇均被引为 0 或 >100 属明显离群
    （如停刊旧刊号的 367.0），metrics 加载时过滤，防止极端值透出进 Top100。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(journal)")}
    if "flagged" not in cols:
        conn.execute("ALTER TABLE journal ADD COLUMN flagged INTEGER DEFAULT 0")
        conn.execute(
            """
            UPDATE journal SET flagged = 1
            WHERE source = 'openalex'
              AND (cites_per_doc_2y IS NULL OR cites_per_doc_2y = 0 OR cites_per_doc_2y > 100)
            """
        )
        conn.commit()


def replace_source(conn: sqlite3.Connection, source: str) -> None:
    """清空某个来源的全部条目，用于整源重建（保证脚本可重复执行、结果幂等）。"""
    conn.execute("DELETE FROM journal WHERE source = ?", (source,))
    conn.execute("DELETE FROM dataset_meta WHERE source = ?", (source,))


def add_journal(conn: sqlite3.Connection, **f) -> int:
    """写入一本刊及其所有 ISSN。issn_spec 传 [(issn, kind), ...]。flagged 标记离群条目。"""
    cur = conn.execute(
        """
        INSERT INTO journal (source, source_id, name, norm_name, type, publisher, country,
                             quartile, quartile_kind, cites_per_doc_2y, sjr, h_index,
                             works_count, coverage_start, coverage_end, categories, areas,
                             flagged, retrieved_at)
        VALUES (:source, :source_id, :name, :norm_name, :type, :publisher, :country,
                :quartile, :quartile_kind, :cites_per_doc_2y, :sjr, :h_index,
                :works_count, :coverage_start, :coverage_end, :categories, :areas,
                :flagged, :retrieved_at)
        """,
        {
            "source": f["source"],
            "source_id": f.get("source_id"),
            "name": f["name"],
            "norm_name": f.get("norm_name") or norm_name(f["name"]),
            "type": f.get("type"),
            "publisher": f.get("publisher"),
            "country": f.get("country"),
            "quartile": f.get("quartile"),
            "quartile_kind": f.get("quartile_kind"),
            "cites_per_doc_2y": f.get("cites_per_doc_2y"),
            "sjr": f.get("sjr"),
            "h_index": f.get("h_index"),
            "works_count": f.get("works_count"),
            "coverage_start": f.get("coverage_start"),
            "coverage_end": f.get("coverage_end"),
            "categories": f.get("categories"),
            "areas": f.get("areas"),
            "flagged": int(f.get("flagged") or 0),
            "retrieved_at": f["retrieved_at"],
        },
    )
    jid = cur.lastrowid
    conn.executemany(
        "INSERT OR IGNORE INTO journal_issn (issn, journal_id, kind) VALUES (?, ?, ?)",
        [(i, jid, k) for i, k in f.get("issn_spec") or []],
    )
    return jid


def set_meta(conn: sqlite3.Connection, source: str, **kv) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO dataset_meta (source, key, value) VALUES (?, ?, ?)",
        [(source, k, None if v is None else str(v)) for k, v in kv.items()],
    )


def get_meta(conn: sqlite3.Connection, source: str) -> dict:
    rows = conn.execute(
        "SELECT key, value FROM dataset_meta WHERE source = ? ORDER BY key", (source,)
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def query_by_issn(conn: sqlite3.Connection, issn: str, source: str = None) -> list:
    """按 ISSN 查期刊。返回可能是多行（多来源，或多来源下同名不同刊）。"""
    keys = split_issns(issn) or [''.join(c for c in (issn or '') if c.isalnum()).upper()]
    if not keys:
        return []
    ph = ",".join("?" * len(keys))
    sql = f"""
        SELECT j.*, ji.issn AS matched_issn, ji.kind AS issn_kind
        FROM journal_issn ji JOIN journal j ON j.id = ji.journal_id
        WHERE ji.issn IN ({ph})
    """
    params = list(keys)
    if source:
        sql += " AND j.source = ?"
        params.append(source)
    sql += " ORDER BY j.source, j.quartile IS NULL, j.quartile"
    return conn.execute(sql, params).fetchall()


def query_by_name(conn: sqlite3.Connection, name: str, source: str = None) -> list:
    nm = norm_name(name)
    if not nm:
        return []
    sql = "SELECT * FROM journal WHERE norm_name = ?"
    params = [nm]
    if source:
        sql += " AND source = ?"
        params.append(source)
    return conn.execute(sql + " ORDER BY source", params).fetchall()


def stats(conn: sqlite3.Connection) -> dict:
    """汇总每个来源的条目数、类型分布、分区分布、ISSN 覆盖情况。"""
    out = {}
    for (src,) in conn.execute("SELECT DISTINCT source FROM journal ORDER BY source"):
        total = conn.execute(
            "SELECT COUNT(*) c FROM journal WHERE source = ?", (src,)
        ).fetchone()["c"]
        by_type = {r["t"]: r["c"] for r in conn.execute(
            "SELECT COALESCE(type, '(未提供)') t, COUNT(*) c FROM journal "
            "WHERE source = ? GROUP BY t ORDER BY c DESC", (src,))}
        by_q = {r["q"]: r["c"] for r in conn.execute(
            "SELECT COALESCE(quartile, '(无)') q, COUNT(*) c FROM journal "
            "WHERE source = ? GROUP BY q ORDER BY q", (src,))}
        n_issn = conn.execute(
            "SELECT COUNT(*) c FROM journal_issn ji JOIN journal j ON j.id = ji.journal_id "
            "WHERE j.source = ?", (src,)
        ).fetchone()["c"]
        n_metric = conn.execute(
            "SELECT COUNT(*) c FROM journal WHERE source = ? AND cites_per_doc_2y IS NOT NULL",
            (src,),
        ).fetchone()["c"]
        out[src] = {
            "journals": total,
            "issn_rows": n_issn,
            "with_metric": n_metric,
            "by_type": by_type,
            "by_quartile": by_q,
        }
    return out
