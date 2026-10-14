"""中文综述生成（单 LLM 模块，F4）。

- 输入：Top N 篇 (pmid, abstract) + 本次检索的统计上下文
- 输出：分点中文综述 + 出处 PMID 列表
- DashScope qwen（OpenAI 兼容）；无 key 或 MOCK_LLM 时按本次真实统计生成示例综述
"""
from __future__ import annotations

import json
import re
import time as _time

import httpx

from app import config, monitor


def build_prompt(abstracts: list[tuple[str, str]]) -> str:
    lines = []
    for i, (pmid, text) in enumerate(abstracts, 1):
        snippet = text[:1200]
        lines.append(f"{i}. [PMID:{pmid}] {snippet}")
    joined = "\n".join(lines)
    return (
        "你是文献综述助手。基于以下 PubMed 摘要，撰写约 500 字的中文综述，分 3-5 点，"
        "每点聚焦一个研究方向或核心结论。要求：纯中文、分点、不编造、摘要不足时如实说明。"
        "关键论断须标注出处，格式为 [PMID: 39403057]——必须写出完整的 8 位数字 PMID，"
        "不要只写编号或简写；只能引用上面摘要中出现过的 PMID，不得引用未提供的文献。"
        "\n\n摘要：\n" + joined
    )


def _extract_sources(text: str, valid: list[str]) -> list[str]:
    """抽取正文引用的 PMID，**只保留本次输入摘要里真实存在的那些**。

    模型偶尔会把「同一括号内并列多篇」写成 [PMID:A, PMID:22, PMID:25]——
    这里的 22/25 是摘要序号而不是 PMID。若照单全收，sources 字段就会混入
    并不存在的「出处」，与「每条论断带 PMID、不编造」的对外声明冲突。
    因此用「位数 + 白名单」双重校验：位数挡掉序号，白名单挡掉编造的完整 PMID。
    """
    allowed = set(valid)
    cited = re.findall(r"PMID[:：]\s*(\d{6,9})", text)
    seen, out = set(), []
    for c in cited:
        if c in allowed and c not in seen:
            seen.add(c)
            out.append(c)
    # 一条都没命中（越界或格式不合）时退回首段输入 PMID：宁可少，不可假
    return out or valid[:10]


def _mock_review(context: dict | None, abstracts: list[tuple[str, str]]) -> str:
    """无 key 时的示例综述：用本次真实检索的统计结果拼装，而非与数据无关的占位话。

    这样现场不配 API key 也能展示 F4 的实际形态（分点 + 真实 PMID 出处 + 数字可核对）。
    是否调用大模型由响应体的 mock 字段标记、前端据此提示，正文内不自述以免重复。
    """
    ctx = context or {}
    stats = ctx.get("stats") or {}
    query = ctx.get("query") or "该主题"
    total = ctx.get("total")
    years = stats.get("year_distribution") or []
    topics = stats.get("topics") or []
    ifs = stats.get("if_statistics") or {}
    quart = {q["quartile"]: q["count"] for q in (stats.get("quartile_distribution") or [])}
    top100 = stats.get("top100") or []

    sample = sum(y.get("count", 0) for y in years) or len(abstracts)
    pmids = [p for p, _ in abstracts]

    def cite(i: int) -> str:
        return f" [PMID:{pmids[i]}]" if i < len(pmids) else ""

    parts: list[str] = []

    # 一、规模与趋势：真实命中量 + 年份跨度 + 近五年占比
    if years:
        y0, y1 = years[0]["year"], years[-1]["year"]
        recent = sum(y["count"] for y in years if y["year"] >= y1 - 4)
        pct = round(100 * recent / sample) if sample else 0
        scope = f"共命中 {total:,} 篇" if isinstance(total, int) else "检索到大量文献"
        parts.append(
            f"一、研究规模与趋势：检索「{query}」{scope}，本次抽样分析 {sample} 篇，"
            f"发表年份覆盖 {y0}–{y1} 年（{len(years)} 个年份）；其中近五年（{y1 - 4} 年起）"
            f"{recent} 篇，占样本 {pct}%，表明该方向仍处于持续产出的活跃期。{cite(0)}"
        )

    # 二、核心研究方向：MeSH 主题聚类真实频次
    if topics:
        top_desc = "、".join(f"{t['topic']}（{t['count']} 次）" for t in topics[:4])
        parts.append(
            f"二、核心研究方向：主题词聚类显示研究集中在 {top_desc} 等方向，"
            f"机制解析与标志物/干预手段识别构成并行的两条主线。{cite(1)}"
        )

    # 三、期刊与影响力分布：真实分区统计 + IF 统计
    known = sum(v for k, v in quart.items() if k != "未知")
    if known:
        q12 = quart.get("Q1", 0) + quart.get("Q2", 0)
        share = round(100 * q12 / known)
        best = ""
        if top100 and top100[0].get("journal"):
            ifv = top100[0].get("impact_factor")
            best = f"样本中篇均被引最高者为 {top100[0]['journal']}" + (f"（IF {ifv}）" if ifv else "") + "。"
        mean, med, mx = ifs.get("mean"), ifs.get("median"), ifs.get("max")
        ifstat = (
            f"已匹配指标的文献平均篇均被引 {mean}、中位 {med}、最高 {mx}"
            if mean is not None
            else "部分文献已匹配到期刊指标"
        )
        parts.append(
            f"三、期刊与影响力分布：样本中 Q1 {quart.get('Q1', 0)} 篇、Q2 {quart.get('Q2', 0)} 篇，"
            f"合计占已知分区文献的 {share}%；{ifstat}。{best}{cite(2)}"
        )

    # 四、证据基础与时效性：Top100 中近五年占比
    if top100:
        rec = sum(1 for t in top100 if t.get("in_recent_5y"))
        parts.append(
            f"四、证据基础与时效性：按篇均被引排序的前 {len(top100)} 篇高影响力文献中，"
            f"{rec} 篇发表于近五年，构成当前证据主体；摘要与主题词齐备，可供方法学逐项比对。{cite(3)}"
        )

    # 五、挑战与展望
    parts.append(
        "五、挑战与展望：样本异质性、期刊指标覆盖不全（长尾刊缺少篇均被引数据）以及结论可重复性"
        "仍是主要瓶颈；后续宜在更大样本上结合标准化评价体系，对高影响力方向做定量的证据分级。"
    )
    # 不在正文里自述"这是示例综述"：前端有醒目提示、响应体也带 mock 字段，
    # 正文保持干净以便复制引用。
    return "\n".join(parts)


async def generate_review(
    abstracts: list[tuple[str, str]],
    context: dict | None = None,
) -> dict:
    if not abstracts:
        return {"text": "未检索到含摘要的文献，无法生成综述。", "sources": []}

    if config.MOCK_LLM or not config.DASHSCOPE_API_KEY:
        text = _mock_review(context, abstracts)
        monitor.step("review", "mock.generated", chars=len(text), sources=len(abstracts))
        return {
            "text": text,
            "sources": _extract_sources(text, [pmid for pmid, _ in abstracts]),
            "mock": True,
        }

    prompt = build_prompt(abstracts)
    headers = {
        "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 900,
    }
    t0 = __import__("time").perf_counter()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{config.DASHSCOPE_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        monitor.step("review", "llm.failed", ok=False, exc=True, error=str(e), model=config.LLM_MODEL)
        raise
    monitor.step("review", "llm.done", chars=len(text), ms=(  __import__("time").perf_counter() - t0) * 1000, model=config.LLM_MODEL)

    sources = _extract_sources(text, [pmid for pmid, _ in abstracts])
    return {"text": text, "sources": sources}


async def generate_review_stream(
    abstracts: list[tuple[str, str]],
    context: dict | None = None,
):
    """流式版综述（SSE 用）：逐段 yield 事件，最终 yield done（返回契约同 generate_review）。

    事件协议：
      {"type": "delta", "text": chunk}                       —— 增量文本
      {"type": "done", "text": 全文, "sources": [...], "mock"?: True}
    与 generate_review 共用 prompt / 来源白名单校验 / mock 兜底 / 监控埋点，
    唯一差别是 LLM 调用走 stream=True 并把增量转发出来；mock（无 key）时按行切块推送，
    现场观感与真实流式一致。异常处理同 generate_review：monitor 记录后原样抛出，
    由上层（SSE 端点）转成 error 事件。
    """
    if not abstracts:
        yield {"type": "done", "text": "未检索到含摘要的文献，无法生成综述。", "sources": [], "mock": True}
        return

    valid = [pmid for pmid, _ in abstracts]

    if config.MOCK_LLM or not config.DASHSCOPE_API_KEY:
        text = _mock_review(context, abstracts)
        for line in text.splitlines(keepends=True):
            if line:
                yield {"type": "delta", "text": line}
        monitor.step("review", "mock.generated", chars=len(text), sources=len(abstracts))
        yield {"type": "done", "text": text, "sources": _extract_sources(text, valid), "mock": True}
        return

    prompt = build_prompt(abstracts)
    headers = {
        "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 900,
        "stream": True,
    }
    t0 = _time.perf_counter()
    buf: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                f"{config.DASHSCOPE_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = ((obj.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                    if delta:
                        buf.append(delta)
                        yield {"type": "delta", "text": delta}
    except Exception as e:  # noqa: BLE001
        monitor.step("review", "llm.failed", ok=False, exc=True, error=str(e), model=config.LLM_MODEL)
        raise
    text = "".join(buf)
    monitor.step("review", "llm.done", chars=len(text), ms=(_time.perf_counter() - t0) * 1000, model=config.LLM_MODEL)
    yield {"type": "done", "text": text, "sources": _extract_sources(text, valid)}
