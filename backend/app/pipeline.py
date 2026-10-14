"""分析流水线：查询改写 → 检索 → 聚合统计 → 中文综述 → 统一响应体 → 文献落库。

**唯一编排入口**：main.py（在线请求）与 scripts/precache.py（离线预生成）都只调这里，
不再各自拼接阶段，保证在线与离线两条路径的行为完全一致。

每阶段的真实耗时记入 trace 随响应体返回，供前端按真实数据展示进度
（而非用固定时长的动画模拟）。

v2 新增（docs/升级设计方案-数据层与中文检索.md）：
  - 阶段 0：中文查询改写（QUERY_REWRITE 开关；纯英文直通零开销）
  - 收尾：文献落库 literature.db（best effort，失败只记 trace 不阻塞主链路）
  - 响应体新增 rewrite（改写透明化）与 suggestions（0 命中时前端引导）
"""
import datetime
import time

from . import analyze, config, monitor, pubmed, query_translate, review


async def build_payload(
    query: str,
    max_results: int,
    include_review: bool = True,
    current_year: int | None = None,
    on_event=None,
) -> dict:
    """唯一编排入口。on_event 为可选回调（SSE 流式用）：传入后每个阶段发
    {"type":"stage", key/label/status/ms/detail} 事件、综述逐字发
    {"type":"review_delta", text}；默认 None 时行为与旧版完全一致（不产生任何事件）。"""
    if current_year is None:
        current_year = datetime.date.today().year

    trace: list[dict] = []
    t_all = time.perf_counter()

    def stage_running(key: str, label: str) -> None:
        if on_event:
            on_event({"type": "stage", "key": key, "label": label, "status": "running"})

    def mark(stage: str, label: str, started: float, ok: bool = True, detail: str = "") -> None:
        ms = round((time.perf_counter() - started) * 1000)
        trace.append({
            "stage": stage,
            "label": label,
            "ms": ms,
            "ok": ok,
            "detail": detail,
        })
        # 同源写监控日志：trace 给前端回放，monitor 给文件排障（设计见监控日志设计方案）
        monitor.step("pipeline", stage, ok=ok, ms=ms, label=label, detail=detail)
        if on_event:
            on_event({
                "type": "stage",
                "key": stage,
                "label": label,
                "status": "done" if ok else "error",
                "ms": ms,
                "detail": detail,
            })

    # 阶段 0：中文查询改写（渐冻症 → ALS）。纯英文输入在 rewrite 内部直通，零开销
    stage_running("rewrite", "查询改写")
    t = time.perf_counter()
    rewrite = await query_translate.rewrite(query)
    search_term = rewrite["term"]
    mark(
        "rewrite",
        "查询改写",
        t,
        detail=(
            f"「{query}」→「{search_term}」（{rewrite['source']}）"
            if rewrite["source"] != "passthrough"
            else "英文/透传，无需改写"
        ),
    )

    # 阶段 1/3：NCBI 检索
    stage_running("search", "PubMed 检索")
    t = time.perf_counter()
    total, articles = await pubmed.search_pubmed(search_term, max_results, config.NCBI_API_KEY)
    mark("search", "PubMed 检索", t, detail=f"命中 {total:,} 篇 · 取回 {len(articles)} 篇")

    # 阶段 2/3：聚合统计（纯本地计算）
    stage_running("stats", "聚合统计")
    t = time.perf_counter()
    stats = analyze.analyze(articles, current_year)
    known = stats["if_statistics"]["known_count"]
    mark(
        "stats",
        "聚合统计",
        t,
        detail=(
            f"年份 {len(stats['year_distribution'])} 段 · 词云 {len(stats['wordcloud'])} 词 · "
            f"IF 命中 {known}/{len(articles)} · Top100 {len(stats['top100'])} 条"
        ),
    )

    # 阶段 3/3：中文综述
    review_result = None
    if include_review:
        abstracts = [
            (a.get("pmid"), a.get("abstract", ""))
            for a in articles
            if a.get("abstract")
        ][: config.REVIEW_TOP_N]
        if abstracts:
            stage_running("review", "中文综述")
            t = time.perf_counter()
            if on_event is not None:
                # 流式路径：逐字透传增量，同时累积成与 generate_review 相同的返回契约
                text_buf: list[str] = []
                review_result: dict = {}
                async for ev in review.generate_review_stream(
                    abstracts,
                    context={"query": query, "total": total, "stats": stats},
                ):
                    if ev["type"] == "delta":
                        text_buf.append(ev["text"])
                        on_event(ev)
                    elif ev["type"] == "done":
                        review_result = {
                            "text": ev["text"],
                            "sources": ev["sources"],
                            **({"mock": True} if ev.get("mock") else {}),
                        }
                if not review_result:
                    # 生成器没给出 done 就结束（异常中断）——与旧路径一致抛错，由上层转错误
                    raise RuntimeError("综述流式生成提前结束")
            else:
                review_result = await review.generate_review(
                    abstracts,
                    context={"query": query, "total": total, "stats": stats},
                )
            mark(
                "review",
                "中文综述",
                t,
                detail=(
                    f"{len(review_result.get('text') or '')} 字 · "
                    f"{len(review_result.get('sources') or [])} 处 PMID"
                ),
            )
        else:
            review_result = {
                "text": "未检索到含摘要的文献，无法生成综述。",
                "sources": [],
                "mock": config.MOCK_LLM or not config.DASHSCOPE_API_KEY,
            }
            mark("review", "中文综述", t, ok=False, detail="无可用于综述的摘要")

    # 真实大模型链路下 generate_review() 返回体里没有 mock 字段，这里统一补齐，
    # 保证「review.mock 恒存在」这一响应契约稳定（前端用 !!review.mock 判断是否示例模式）。
    # include_review=False 时 review_result 仍是 None，不介入。
    if isinstance(review_result, dict):
        review_result.setdefault("mock", config.MOCK_LLM or not config.DASHSCOPE_API_KEY)

    # 文献落库（v2 新增，best effort）：检索词 → 文献全量 → 命中集 → 分析快照。
    # 失败只记 trace，绝不阻塞主链路——落库是增量能力，不是检索的前置条件。
    t_lit = time.perf_counter()
    try:
        from . import literaturedb

        literaturedb.log_run(
            term_raw=query,
            term=search_term,
            rewrite_source=rewrite["source"],
            retmax=max_results,
            total=total,
            articles=articles,
            stats=stats,
            review=review_result,
            elapsed_ms=round((time.perf_counter() - t_all) * 1000),
            norm_fn=analyze.metrics._norm_name,
        )
        mark("litlog", "文献落库", t_lit, detail="已写入 literature.db")
    except Exception as e:  # noqa: BLE001
        trace.append({
            "stage": "litlog",
            "label": "文献落库",
            "ms": 0,
            "ok": False,
            "detail": f"落库失败（不影响结果）: {e}"[:120],
        })
        monitor.warning("litlog", "log_run.failed", query=query, error=str(e))

    # 0 命中时的前端引导（L2）：给出英文候选词，避免「干等一场空」
    suggestions: list[str] = []
    if total == 0 and query_translate.has_cjk(query):
        seen: set[str] = set()
        for cand in [rewrite["term"], *rewrite.get("synonyms", [])]:
            if cand and cand != query and cand not in seen:
                seen.add(cand)
                suggestions.append(cand)

    return {
        "query": query,
        "total": total,
        "returned": len(articles),
        "search_term": search_term,
        "rewrite": rewrite,
        "stats": stats,
        "review": review_result,
        "trace": trace,
        "cached": False,
        "suggestions": suggestions,
        "articles": [
            {
                k: a.get(k)
                for k in ("pmid", "title", "journal", "year", "url", "mesh", "impact_factor", "quartile")
            }
            for a in articles
        ],
    }
