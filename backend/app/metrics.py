"""期刊指标加载与匹配：ISSN/期刊名 -> IF + 分区。缺失降级 unknown。

数据来源：SQLite 单文件（`data/journal_metrics.db`），由 `app/journaldb.py` 提供建表/写入/查询。
构建脚本（`scripts/build_metrics_db.py`）把 SCImago / OpenAlex 两类来源的期刊指标写入该库，
运行时从这里加载进内存字典查询。

口径说明：分区分两类——SCImago 是源方「已发布分区」，OpenAlex 是「按近 2 年篇均被引阈值推算」，
**都不是官方 JCR 分区**；「近 2 年篇均被引」也不是 JCR 影响因子。数据集内不含任何人工录入值。

过渡兼容：若 SQLite 尚未生成，回落到旧 JSON 文件（`data/journal_metrics.json`），
保证「只改了存储层、还没重新构建」的中间状态也能正常启动。
"""
import json
import os
import re

from . import journaldb

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "journal_metrics.json")

_BY_ISSN: dict = {}
_BY_NAME: dict = {}
_META: dict = {}
_LOADED = False


_PAREN = re.compile(r"\([^)]*\)")
_LEAD_ARTICLE = re.compile(r"^(the|a|an)\s+")
# PubMed 里的刊名前缀缩写：'JPMA. The Journal of ...' / 'BMJ. ...'
_LEAD_ABBREV = re.compile(r"^([A-Z][A-Z0-9&\-]{1,5})\.\s+")


def _norm_name(name: str) -> str:
    """归一化刊名，抹平 PubMed 与数据集的常见写法差异。

    PubMed 返回的刊名常带各种修饰，需要统一：
      'Science (New York, N.Y.)'                    -> 'science'
      'Nature reviews. Cancer'                      -> 'nature reviews cancer'
      'The Lancet. Oncology'                        -> 'lancet oncology'
      "Journal of Alzheimer's disease : JAD"        -> 'journal of alzheimer s disease'
      'Biomedicine & pharmacotherapy = Biomedecin..' -> 'biomedicine and pharmacotherapy'
      'JPMA. The Journal of the Pakistan Med..'     -> 'journal of the pakistan medical association'
    """
    if not name:
        return ""
    s = _LEAD_ABBREV.sub("", name.strip())   # 去开头缩写前缀
    s = s.lower()
    s = _PAREN.sub(" ", s)                   # 去括号限定词 (New York, N.Y.)
    s = re.split(r"[:=]", s)[0]              # '主标题 : 缩写' / '标题 = 平行标题' 取主标题
    s = s.replace("&", " and ")              # '&' 统一为 'and'
    s = re.sub(r"[^a-z0-9 ]", " ", s)        # 其余标点（含句点/撇号）转空格
    s = _LEAD_ARTICLE.sub("", s.strip())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _split_issns(raw) -> list[str]:
    """一个期刊可能同时有印刷/电子刊号，支持逗号/分号/空格分隔或列表。"""
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        tokens = [str(x) for x in raw]
    else:
        tokens = re.split(r"[,;/|\s]+", str(raw))
    out = []
    for t in tokens:
        k = t.replace("-", "").strip().upper()
        if len(k) == 8 and k.isalnum():
            out.append(k)
    return out


def _split_names(raw) -> list[str]:
    """支持一个期刊配多个别名（全称 + ISO 缩写），逗号或分号分隔。"""
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        tokens = [str(x) for x in raw]
    else:
        tokens = re.split(r"[;,|]+", str(raw))
    out = []
    for t in tokens:
        n = _norm_name(t)
        if n:
            out.append(n)
    return out


def _norm_issn(issn: str) -> str:
    if not issn:
        return ""
    return issn.replace("-", "").strip().upper()


def load(force: bool = False) -> None:
    global _BY_ISSN, _BY_NAME, _META, _LOADED
    if _LOADED and not force:
        return
    _BY_ISSN, _BY_NAME = {}, {}
    journals, meta = _load_db()
    if journals:
        _META = meta
        _fill(journals)
    else:
        # 过渡兼容：SQLite 还没生成时回落到旧 JSON
        _META, journals = _load_json()
        _fill(journals)
    _load_learned_aliases()
    _LOADED = True


def _load_learned_aliases() -> None:
    """把运行期自学习的 ISO 缩写别名合并进刊名索引（存于 literature.db）。"""
    try:
        from . import literaturedb

        for alias, entry in literaturedb.load_aliases():
            if alias and alias not in _BY_NAME:
                _BY_NAME[alias] = entry
    except Exception:
        pass


def learn(articles: list[dict]) -> int:
    """从真实语料沉淀 ISO 缩写别名（自学习，修缩写匹配缺口）。

    PubMed XML 同时给刊名全称与 ISOAbbreviation：ISSN 已命中指标的文献，
    其缩写大概率指向同一本刊——把「缩写 → 指标条目」也建上索引，后续
    只出现缩写的文献即可命中。内存立即生效，持久化到 literature.db
    （指标库保持只读，运行期产物不进随包文件）。
    返回本轮新学到的别名数；任何失败静默忽略，绝不影响主链路。
    """
    load()
    known = [a for a in articles if a.get("metric_known") and a.get("journal_iso")]
    if not known:
        return 0
    learned = 0
    try:
        from . import literaturedb

        conn = literaturedb.connect()
        try:
            for a in known:
                nm = _norm_name(a["journal_iso"])
                if not nm or nm in _BY_NAME:
                    continue
                entry = {"if": a.get("impact_factor"), "quartile": a.get("quartile")}
                _BY_NAME[nm] = entry
                literaturedb.save_alias(conn, nm, entry)
                learned += 1
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        from . import monitor

        monitor.warning("metrics", "learn.failed", error=str(e))
    return learned


def _load_db() -> tuple[list[dict], dict]:
    """从 SQLite（journaldb）读取期刊与 meta。

    返回的 journals 每条统一成 {name, issn, eissn, if, quartile} 形状，与旧 JSON 加载兼容，
    这样 _fill() 与 enrich() 无需感知底层是 JSON 还是 DB。

    数据源优先级：同一 ISSN 同时存在于 scimago 与 openalex 时，优先取 scimago 的
    「源方已发布分区」；只有 scimago 没有该刊时才用 openalex 的推算分区。
    """
    try:
        conn = journaldb.connect()
    except Exception:
        return [], {}
    try:
        # scimago 优先，openalex 兜底；同一 source_id 只取一次；
        # flagged（离群标记，如停刊旧刊号的 367.0）在 SQL 层直接排除，不进内存字典
        rows = conn.execute(
            """
            SELECT * FROM journal
            WHERE COALESCE(flagged, 0) = 0
            ORDER BY CASE source WHEN 'scimago' THEN 0 ELSE 1 END, id
            """
        ).fetchall()
        by_key: dict = {}
        for r in rows:
            key = (r["source"], r["source_id"])
            if key in by_key:
                continue
            by_key[key] = r

        journals = []
        seen_issn: dict[str, bool] = {}
        for r in by_key.values():
            issn_rows = conn.execute(
                "SELECT issn FROM journal_issn WHERE journal_id = ?", (r["id"],)
            ).fetchall()
            issns = [x["issn"] for x in issn_rows]
            # 已由更高优先级源占用的 ISSN 不再重复给低优先级源
            if any(seen_issn.get(i) for i in issns):
                continue
            for i in issns:
                seen_issn[i] = True
            journals.append(
                {
                    "name": r["name"],
                    "issn": ",".join(issns),
                    "eissn": "",
                    "if": r["cites_per_doc_2y"],
                    "quartile": r["quartile"],
                    "source": r["source"],
                }
            )

        meta = {
            k: v
            for k, v in conn.execute(
                "SELECT key, value FROM dataset_meta WHERE source = 'scimago'"
            )
        }
        if not meta:
            meta = {
                k: v
                for k, v in conn.execute(
                    "SELECT key, value FROM dataset_meta WHERE source = 'openalex'"
                )
            }
        return journals, meta
    finally:
        conn.close()


def _fill(journals: list[dict]) -> None:
    """把期刊列表填充进内存索引（ISSN 与刊名双键）。"""
    for j in journals:
        entry = {"if": j.get("if"), "quartile": j.get("quartile")}
        issns = set(_split_issns(j.get("issn", ""))) | set(_split_issns(j.get("eissn", "")))
        for issn in issns:
            _BY_ISSN.setdefault(issn, entry)
        nm = _norm_name(j.get("name", ""))
        if nm:
            _BY_NAME.setdefault(nm, entry)
        # 备用：ISO 缩写（PubMed 的 ISOAbbreviation，如 'Nat Rev Cancer'）
        for ab in _split_names(j.get("abbrev", "")):
            _BY_NAME.setdefault(ab, entry)


def _load_json() -> tuple[dict, list[dict]]:
    """过渡期从旧 JSON 读取，返回 (meta, journals)。"""
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, []
    return data.get("meta", {}), data.get("journals", [])


def enrich(journal: str = "", issn: str = "") -> dict:
    """返回单个期刊的指标，缺失字段降级为 None。"""
    load()
    for k in _split_issns(issn) or [_norm_issn(issn)]:
        if k and k in _BY_ISSN:
            e = _BY_ISSN[k]
            return {"if": e["if"], "quartile": e["quartile"], "known": e["if"] is not None}
    nm_k = _norm_name(journal)
    if nm_k and nm_k in _BY_NAME:
        e = _BY_NAME[nm_k]
        return {"if": e["if"], "quartile": e["quartile"], "known": e["if"] is not None}
    return {"if": None, "quartile": None, "known": False}


def meta() -> dict:
    load()
    return _META
