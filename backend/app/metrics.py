"""期刊指标加载与匹配：ISSN/期刊名 -> IF + JCR 分区。缺失降级 unknown。"""
import json
import os
import re

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
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        _META = {}
        _LOADED = True
        return
    _META = data.get("meta", {})
    for j in data.get("journals", []):
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
    _LOADED = True


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
