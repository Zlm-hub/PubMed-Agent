"""文献库（literature.db）：检索词 / 文献 / 命中集 / 分析快照 / 自学习数据的运行时存储。

为什么与 journal_metrics.db 分离（详见 docs/升级设计方案-数据层与中文检索.md）：
  指标库只读、随包发布、年级重建；文献库运行时持续写入、随使用增长。
  两库生命周期不同——合并会让「可再生的指标」和「不可再生的积累」互相绑架。

跨库无外键：article 冗余存 norm_journal + issn，指标匹配放代码层
（metrics.enrich 两级字典），两库各自独立可迁移。

本库还承接两件「自学习」数据的落点（指标库保持只读，不写运行时产物）：
  - learned_alias：PubMed XML 的 ISO 缩写 → 指标条目快照，修缩写匹配缺口
  - term_mapping：中文→英文术语映射（L0），status 两态防幻觉直入正式表
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "literature.db")
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS search_query (
    id             INTEGER PRIMARY KEY,
    term_raw       TEXT NOT NULL,
    term           TEXT NOT NULL,
    retmax         INTEGER NOT NULL DEFAULT 200,
    rewrite_source TEXT,
    last_total     INTEGER,
    first_seen_at  TEXT NOT NULL,
    last_run_at    TEXT NOT NULL,
    UNIQUE (term_raw, retmax)
);

CREATE TABLE IF NOT EXISTS article (
    pmid         INTEGER PRIMARY KEY,
    title        TEXT,
    norm_journal TEXT,
    issn         TEXT,
    year         INTEGER,
    abstract     TEXT,
    pub_types    TEXT,
    fetched_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_article_journal ON article(norm_journal);
CREATE INDEX IF NOT EXISTS ix_article_year ON article(year);

CREATE TABLE IF NOT EXISTS article_mesh (
    pmid      INTEGER NOT NULL REFERENCES article(pmid) ON DELETE CASCADE,
    mesh_term TEXT NOT NULL,
    PRIMARY KEY (pmid, mesh_term)
);

CREATE TABLE IF NOT EXISTS search_hit (
    query_id INTEGER NOT NULL REFERENCES search_query(id) ON DELETE CASCADE,
    pmid     INTEGER NOT NULL REFERENCES article(pmid) ON DELETE CASCADE,
    rank     INTEGER NOT NULL,
    PRIMARY KEY (query_id, pmid)
);
CREATE INDEX IF NOT EXISTS ix_hit_pmid ON search_hit(pmid);

CREATE TABLE IF NOT EXISTS analysis_run (
    id          INTEGER PRIMARY KEY,
    query_id    INTEGER NOT NULL REFERENCES search_query(id),
    params_json TEXT NOT NULL,
    stats_json  TEXT NOT NULL,
    review_text TEXT,
    review_mock INTEGER NOT NULL DEFAULT 0,
    elapsed_ms  INTEGER,
    created_at  TEXT NOT NULL
);

-- 中文→英文术语映射（L0）。candidate 只是候选，护栏（回译/试搜）通过
-- 并人工确认后才置 approved；运行期只查 approved。
CREATE TABLE IF NOT EXISTS term_mapping (
    term_cn     TEXT PRIMARY KEY,
    term_en     TEXT NOT NULL,
    synonyms    TEXT,
    source      TEXT NOT NULL,
    verified_at TEXT,
    status      TEXT NOT NULL DEFAULT 'candidate'
);

-- 运行期自学习的 ISO 缩写别名（指标库只读，学到的别名落这里）
CREATE TABLE IF NOT EXISTS learned_alias (
    alias_norm TEXT PRIMARY KEY,
    if_val     REAL,
    quartile   TEXT,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(path: str = None) -> sqlite3.Connection:
    """打开连接并确保 schema 就绪。WAL + 外键：演示单进程足够，多进程也安全。"""
    p = path or DB_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


def upsert_article(conn: sqlite3.Connection, a: dict) -> int | None:
    """写一篇文献（全量摘要落库）。pmid 缺失或非数字返回 None。"""
    try:
        pmid = int(str(a.get("pmid") or "").strip())
    except (ValueError, TypeError):
        return None
    conn.execute(
        """
        INSERT INTO article (pmid, title, norm_journal, issn, year, abstract, pub_types, fetched_at)
        VALUES (:pmid, :title, :norm_journal, :issn, :year, :abstract, :pub_types, :fetched_at)
        ON CONFLICT(pmid) DO UPDATE SET
            title = excluded.title,
            norm_journal = excluded.norm_journal,
            issn = excluded.issn,
            year = excluded.year,
            abstract = CASE WHEN excluded.abstract != '' THEN excluded.abstract ELSE article.abstract END,
            pub_types = excluded.pub_types,
            fetched_at = excluded.fetched_at
        """,
        {
            "pmid": pmid,
            "title": a.get("title") or "",
            "norm_journal": a.get("norm_journal") or "",
            "issn": a.get("issn") or "",
            "year": a.get("year"),
            "abstract": a.get("abstract") or "",
            "pub_types": "; ".join(a.get("article_types") or []) or None,
            "fetched_at": _now(),
        },
    )
    for mh in a.get("mesh") or []:
        term = str(mh).strip()
        if term:
            conn.execute(
                "INSERT OR IGNORE INTO article_mesh (pmid, mesh_term) VALUES (?, ?)",
                (pmid, term),
            )
    return pmid


def log_run(
    *,
    term_raw: str,
    term: str,
    rewrite_source: str,
    retmax: int,
    total: int,
    articles: list[dict],
    stats: dict,
    review: dict | None,
    elapsed_ms: int,
    norm_fn=None,
) -> int:
    """把一次完整分析落库：检索词 → 文献 → 命中集 → 分析快照。

    norm_fn 由调用方注入（metrics._norm_name），保持本模块与指标匹配规则解耦。
    任何一条文献写失败都不应拖垮整次落库，因此逐篇 try。
    """
    conn = connect()
    try:
        now = _now()
        conn.execute(
            """
            INSERT INTO search_query (term_raw, term, retmax, rewrite_source, last_total,
                                      first_seen_at, last_run_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(term_raw, retmax) DO UPDATE SET
                term = excluded.term,
                rewrite_source = excluded.rewrite_source,
                last_total = excluded.last_total,
                last_run_at = excluded.last_run_at
            """,
            (term_raw, term, retmax, rewrite_source, total, now, now),
        )
        query_id = conn.execute(
            "SELECT id FROM search_query WHERE term_raw = ? AND retmax = ?",
            (term_raw, retmax),
        ).fetchone()["id"]

        rank = 0
        for a in articles:
            norm = (norm_fn(a.get("journal") or "")) if norm_fn else (a.get("journal") or "")
            row = {**a, "norm_journal": norm}
            try:
                pmid = upsert_article(conn, row)
            except Exception:  # noqa: BLE001
                continue
            if pmid is None:
                continue
            rank += 1
            conn.execute(
                "INSERT OR IGNORE INTO search_hit (query_id, pmid, rank) VALUES (?, ?, ?)",
                (query_id, pmid, rank),
            )

        params = {"term_raw": term_raw, "term": term, "retmax": retmax}
        conn.execute(
            """
            INSERT INTO analysis_run (query_id, params_json, stats_json, review_text,
                                      review_mock, elapsed_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query_id,
                json.dumps(params, ensure_ascii=False),
                json.dumps(stats, ensure_ascii=False),
                (review or {}).get("text"),
                int(bool((review or {}).get("mock"))),
                elapsed_ms,
                now,
            ),
        )
        conn.commit()
        return query_id
    finally:
        conn.close()


def lookup_mapping(conn: sqlite3.Connection, term_cn: str) -> sqlite3.Row | None:
    """查正式映射（仅 approved——candidate 尚未过护栏，不作数）。"""
    return conn.execute(
        "SELECT * FROM term_mapping WHERE term_cn = ? AND status = 'approved'",
        (term_cn,),
    ).fetchone()


def all_approved(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM term_mapping WHERE status = 'approved' ORDER BY LENGTH(term_cn) DESC"
    ).fetchall()


def upsert_mapping(
    conn: sqlite3.Connection,
    term_cn: str,
    term_en: str,
    synonyms: list[str] | None,
    source: str,
    status: str = "candidate",
) -> None:
    conn.execute(
        """
        INSERT INTO term_mapping (term_cn, term_en, synonyms, source, verified_at, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(term_cn) DO UPDATE SET
            term_en = excluded.term_en,
            synonyms = excluded.synonyms,
            source = excluded.source,
            status = excluded.status
        """,
        (term_cn, term_en, json.dumps(synonyms or [], ensure_ascii=False), source,
         _now() if status == "approved" else None, status),
    )
    conn.commit()


def save_alias(conn: sqlite3.Connection, alias_norm: str, entry: dict) -> None:
    conn.execute(
        """
        INSERT INTO learned_alias (alias_norm, if_val, quartile, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(alias_norm) DO UPDATE SET
            if_val = excluded.if_val,
            quartile = excluded.quartile,
            updated_at = excluded.updated_at
        """,
        (alias_norm, entry.get("if"), entry.get("quartile"), _now()),
    )


def load_aliases() -> list[tuple[str, dict]]:
    """启动时把自学习别名读回内存（metrics.load 合并进 _BY_NAME）。"""
    try:
        conn = connect()
    except Exception:  # noqa: BLE001
        return []
    try:
        rows = conn.execute("SELECT alias_norm, if_val, quartile FROM learned_alias").fetchall()
        return [(r["alias_norm"], {"if": r["if_val"], "quartile": r["quartile"]}) for r in rows]
    except Exception:  # noqa: BLE001
        return []
    finally:
        conn.close()


def stats(conn: sqlite3.Connection) -> dict:
    out = {}
    for table in ("search_query", "article", "analysis_run", "term_mapping", "learned_alias"):
        try:
            n = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
        except Exception:  # noqa: BLE001
            n = -1
        out[table] = n
    return out
