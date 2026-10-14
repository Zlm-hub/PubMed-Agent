"""词云 / MeSH 主题词中文化（英文原词 → 中文译名辅助）。

背景：词云来自英文标题/摘要分词、研究方向标签来自 MeSH 英文受控词，中文客户读不懂。
方案（2026-09-19 用户拍板，见当日工作日志）：
  - **本地词典优先**（word_zh 表，命中 0ms）→ 未命中**一次性批量**交给大模型 → 结果落库，
    下次同词直接命中；预缓存词预热一次后，现场演示零延迟。
  - 人工译名（source='manual'）**永不被机翻覆盖**——术语不准时可直接改表。
  - best-effort：超时/失败只返回已命中的部分，**绝不阻塞分析主链路**（与文献落库同款思路）。
  - 诚实性：翻译只是阅读辅助，统计口径不变；前端负责「中文为主 + 悬停英文原词」并
    标注「机翻辅助」，不让人误以为原文就是中文。

数据契约（只加可选字段，向后兼容，老缓存缺 zh 时前端自动回退英文）：
  stats.wordcloud[i] = {word, count, zh?}
  stats.topics[i]    = {topic, count, zh?}
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import httpx

from app import config, literaturedb, monitor

# 一次最多翻这么多词（防御异常大的 payload；正常词云 80 + 主题词 6）
MAX_TERMS = 400
# 单次请求的词数上限：实测一次性塞几百个词会把模型输出撑爆（JSON 被截断 → 解析失败），
# 因此分块请求，每块独立成败、各自落库——某块失败不影响其它块。
CHUNK = 60
# 允许翻译的词形：字母开头，可含数字/连字符/逗号/空格。
# 必须允许数字——`COVID-19`、`SARS-CoV-2`、`cas9`、`bnt162b2`、`sepsis-3` 这类词
# 都带数字，早期版本把它们整体过滤掉，导致这些高频词一直翻不出来（实测踩过）。
_TERM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-\s,]*$")

_PROMPT = (
    "你是医学术语翻译助手。把下面给出的英文医学词汇译成简洁规范的中文术语"
    "（名词短语，2~6 字为宜；只给译名本身，不要解释、不要标点、不要拼音）。"
    "只返回一个 JSON 对象：键为原英文词（原样保留），值为对应中文译名。\n\n词汇：\n"
)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_cached(keys: list[str]) -> dict[str, str]:
    """按小写键批量查词典（分块，避免 SQLite 变量数上限）。"""
    out: dict[str, str] = {}
    if not keys:
        return out
    conn = literaturedb.connect()
    try:
        for i in range(0, len(keys), 200):
            chunk = keys[i : i + 200]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT term_en, term_zh FROM word_zh WHERE term_en IN ({marks})", chunk
            ).fetchall()
            for r in rows:
                out[r["term_en"]] = r["term_zh"]
    finally:
        conn.close()
    return out


def save_pairs(pairs: dict[str, str], source: str = "llm") -> None:
    """写词典；人工译名（manual）优先，机翻不覆盖。"""
    if not pairs:
        return
    conn = literaturedb.connect()
    try:
        now = _now()
        for en, zh in pairs.items():
            conn.execute(
                """
                INSERT INTO word_zh (term_en, term_zh, source, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(term_en) DO UPDATE SET
                    term_zh = excluded.term_zh,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                WHERE word_zh.source != 'manual'
                """,
                (en, zh, source, now),
            )
        conn.commit()
        monitor.step("wordzh", "dict.saved", n=len(pairs), source=source)
    finally:
        conn.close()


# 译名必须含中文才算数：模型对纯缩写词（bnt162b2）常原样抄回来，那不叫翻译，回退英文即可。
# 但**允许中文里夹拉丁缩写**——「COVID-19疫苗」「CRISPR技术」「Cas9蛋白」正是这些术语的规范写法。
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _sanitize(obj: dict) -> dict[str, str]:
    """只收「像中文译名」的键值对：键非空、值含中文（纯英文=原样抄回，丢弃）。"""
    out: dict[str, str] = {}
    for k, v in obj.items():
        key = str(k).strip().lower()
        val = str(v).strip() if isinstance(v, str) else ""
        if key and val and _CJK_RE.search(val):
            out[key] = val
    return out


def _parse_pairs(text: str) -> dict[str, str]:
    """解析模型返回的 {英文: 中文}。先按整体 JSON 解；被截断时退化为逐条抓 "k": "v"，尽力抢救。"""
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return _sanitize(json.loads(m.group(0)))
        except json.JSONDecodeError:
            pass
    salvaged = {k: v for k, v in re.findall(r'"([^"]{1,80})"\s*:\s*"([^"]{1,40})"', text)}
    return _sanitize(salvaged)


async def _llm_translate(terms: list[str]) -> dict[str, str]:
    """一批词的翻译（单请求）。返回 {小写原词: 中文}；解析失败返回空 dict。"""
    headers = {
        "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.WORD_ZH_MODEL,
        "messages": [
            {"role": "user", "content": _PROMPT + json.dumps(terms, ensure_ascii=False)}
        ],
        "temperature": 0.0,
        # 每个词约需 10~14 token 输出，留足余量避免 JSON 被截断
        "max_tokens": min(4000, 400 + 14 * len(terms)),
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{config.DASHSCOPE_BASE_URL}/chat/completions", headers=headers, json=payload
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
    return _parse_pairs(text)


async def translate_terms(terms: list[str]) -> dict[str, str]:
    """返回 {原词: 中文}（未翻到的词不出现在结果里）。异常一律吞掉并记日志。

    大小写同源处理：MeSH 主题词是首字母大写（`Asthma`），词云分词是小写（`asthma`），
    二者是同一个词——内部统一按小写去重与查询，对外**按调用方传入的每个原词逐条映射**，
    保证两种写法都能取到译名（否则小写词会静默回退成英文）。
    """
    if not config.WORD_ZH or not config.DASHSCOPE_API_KEY:
        return {}

    # 小写 → 首次出现的原写法（送给模型时用，保留可读性）
    norm: dict[str, str] = {}
    for t in terms[:MAX_TERMS]:
        k = (t or "").strip()
        if not k or not _TERM_RE.match(k):
            continue
        low = k.lower()
        if low not in norm:
            norm[low] = k
    if not norm:
        return {}

    cached = _load_cached(list(norm.keys()))
    zh_low: dict[str, str] = {}
    missing: list[str] = []
    for low, orig in norm.items():
        if cached.get(low):
            zh_low[low] = cached[low]
        else:
            missing.append(orig)

    # 分块翻译：每块独立成败、各自落库；某块失败不影响其它块，也不影响主链路
    for i in range(0, len(missing), CHUNK):
        chunk = missing[i : i + CHUNK]
        try:
            fresh = await _llm_translate(chunk)
        except Exception as e:  # noqa: BLE001
            monitor.step("wordzh", "llm.failed", ok=False, exc=True, error=str(e), batch=len(chunk))
            continue
        if not fresh:
            continue
        save_pairs(fresh)
        monitor.step("wordzh", "translated", n=len(fresh), batch=len(chunk), model=config.WORD_ZH_MODEL)
        for low, zh in fresh.items():
            zh_low.setdefault(low, zh)

    # 按调用方原词逐条映射（含大小写变体），不丢任何一个能命中的写法
    out: dict[str, str] = {}
    for t in terms[:MAX_TERMS]:
        k = (t or "").strip()
        zh = zh_low.get(k.lower()) if k else None
        if zh:
            out[k] = zh
    return out


def payload_terms(payload: dict) -> list[str]:
    """从响应体里取出需要翻译的词（词云词 + MeSH 主题词）。"""
    stats = payload.get("stats") or {}
    words = [w.get("word", "") for w in (stats.get("wordcloud") or [])]
    topics = [t.get("topic", "") for t in (stats.get("topics") or [])]
    return [t for t in (*words, *topics) if t]


async def translate_payload(payload: dict) -> dict[str, str]:
    return await translate_terms(payload_terms(payload))


def attach(zh: dict[str, str], payload: dict) -> None:
    """把译名写回 payload（原地，只加 zh 字段，不动任何原有字段/统计值）。"""
    if not zh:
        return
    stats = payload.get("stats") or {}
    for key, field in (("wordcloud", "word"), ("topics", "topic")):
        for item in stats.get(key) or []:
            zhv = zh.get(str(item.get(field, "")))
            if zhv:
                item["zh"] = zhv
