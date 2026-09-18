"""中文查询改写（L0 映射表 → L1 LLM → 透传）。

解决实测断点：PubMed 是英文语料库，中文词 esearch 必 0 命中（渐冻症实测 0 篇）。
只对含中文的输入生效（决策 D4：中文词先搜原文是纯浪费一跳）；
纯英文输入直通，不多花任何延迟。

设计要点（详见 docs/升级设计方案-数据层与中文检索.md）：
  - L0 查 term_mapping（仅 approved）：高频词 0ms，交付期人工审核固化
  - L1 LLM 改写：输出结构化 JSON（检索式而非整句），esearch 试搜做护栏——
    命中数 > 0 才采纳；通过后落 term_mapping 候选（回流），同词只翻一次
  - 任何失败静默透传原文：改写层绝不阻塞、绝不弄垮主链路
"""
from __future__ import annotations

import json
import re

import httpx

from . import config, monitor

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 口语后缀：渐冻症的最新治疗方法 → 渐冻症（L0 子串匹配前的规整）
_TRAILING_RE = re.compile(
    r"(的最新|的进展|的研究|的治疗|疗法|的综述|综述|的诊断|机制|指南|进展|研究)+$"
)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _variants(term: str) -> list[str]:
    """L0 查找用的规整变体：原词 + 反复剥口语后缀。"""
    t = term.strip()
    out = [t]
    cur = t
    while True:
        nxt = _TRAILING_RE.sub("", cur).strip()
        if not nxt or nxt == out[-1]:
            break
        out.append(nxt)
        cur = nxt
    return out


def _lookup_mapping(conn, term: str):
    """两级查表：变体精确 → 子串（渐冻症 ⊂ 渐冻症的最新治疗方法）。"""
    from . import literaturedb

    for v in _variants(term):
        row = literaturedb.lookup_mapping(conn, v)
        if row:
            return row
    for row in literaturedb.all_approved(conn):
        cn = row["term_cn"]
        if (cn in term) or (term in cn):
            return row
    return None


def _parse_llm_json(text: str) -> dict | None:
    """容忍 ```json 围栏与前后杂讯，解析失败返回 None。"""
    m = _JSON_FENCE_RE.search(text)
    raw = m.group(1) if m else text
    try:
        start, end = raw.index("{"), raw.rindex("}")
        data = json.loads(raw[start : end + 1])
    except (ValueError, KeyError):
        return None
    term = str(data.get("term") or "").strip()
    if not term or not re.fullmatch(r"[A-Za-z][A-Za-z0-9\s\-\(\)\[\]]{1,120}", term):
        return None
    try:
        conf = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "term": term,
        "synonyms": [str(s) for s in (data.get("synonyms") or [])][:3],
        "confidence": conf,
    }


async def _llm_rewrite(term: str) -> dict | None:
    """调 DashScope 改写为检索式；无 key / MOCK / 失败一律返回 None。"""
    if config.MOCK_LLM or not config.DASHSCOPE_API_KEY:
        return None
    prompt = (
        "你是医学文献检索专家。把用户的中文检索意图改写为 PubMed 英文检索词。"
        "要求：\n"
        '1. 输出严格 JSON：{"term": "核心英文检索词", "synonyms": ["同义英文检索词，最多3个"], '
        '"back_translation": "把 term 回译成中文", "confidence": 0.0到1.0}\n'
        "2. term 用医学规范术语（优先 MeSH 规范名，2-4 个英文词），禁止字面直译，"
        "禁止输出整句或加任何解释，除 JSON 外不要输出任何内容。\n"
        f"用户输入：{term}"
    )
    headers = {
        "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 300,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{config.DASHSCOPE_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        return _parse_llm_json(text)
    except Exception:  # noqa: BLE001
        return None


async def _probe(term: str) -> int:
    """护栏：改写词拿去 esearch 试搜，返回命中数（一次 1 篇的小请求）。"""
    from . import pubmed

    try:
        total, _ = await pubmed.search_pubmed(term, 1)
        return int(total)
    except Exception:  # noqa: BLE001
        return -1


async def rewrite(term_raw: str) -> dict:
    """改写入口。返回 {raw, term, source, synonyms}，永不抛异常。

    source：passthrough（未改写）| mapping（L0 查表）| llm（L1 改写）
    """
    base = {"raw": term_raw, "term": term_raw, "source": "passthrough", "synonyms": []}
    if not config.QUERY_REWRITE or not has_cjk(term_raw):
        return base

    try:
        from . import literaturedb

        conn = literaturedb.connect()
        try:
            row = _lookup_mapping(conn, term_raw)
            if row:
                try:
                    synonyms = json.loads(row["synonyms"] or "[]")
                except (ValueError, TypeError):
                    synonyms = []
                monitor.step("rewrite", "mapping.hit", raw=term_raw,
                             term=row["term_en"], ms=None)
                return {
                    **base,
                    "term": row["term_en"],
                    "source": "mapping",
                    "synonyms": synonyms,
                }
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        monitor.warning("rewrite", "mapping.lookup.failed", raw=term_raw, error=str(e))

    monitor.step("rewrite", "mapping.miss", raw=term_raw)

    # L1：LLM 改写 + esearch 试搜护栏
    llm = await _llm_rewrite(term_raw)
    if llm is None:
        monitor.warning("rewrite", "llm.unavailable", raw=term_raw,
                        reason="no-key-or-parse-failed")
    candidates = []
    if llm:
        candidates.append(llm["term"])
        candidates.extend(s for s in llm.get("synonyms") or [] if s)
    for cand in candidates:
        total = await _probe(cand)
        monitor.step("rewrite", "probe", candidate=cand, hit=total)
        if total > 0:
            # 回流为候选词条：护栏已过（试搜有命中），status 仍留 candidate，
            # 人工/回译复核后升级 approved，避免未复核的自动条目直接进正式表
            try:
                from . import literaturedb

                conn = literaturedb.connect()
                try:
                    literaturedb.upsert_mapping(
                        conn, term_raw.strip(), cand,
                        llm.get("synonyms") if llm else [],
                        source="llm-reflow", status="candidate",
                    )
                finally:
                    conn.close()
            except Exception:  # noqa: BLE001
                pass
            monitor.step("rewrite", "llm.accepted", raw=term_raw, term=cand,
                         confidence=(llm or {}).get("confidence"))
            return {**base, "term": cand, "source": "llm", "synonyms": llm.get("synonyms") or []}

    # 全部失败：透传原文，把候选同义词交给前端引导（L2）
    monitor.warning("rewrite", "passthrough.cjk", raw=term_raw, candidates=candidates)
    return {**base, "synonyms": candidates}
