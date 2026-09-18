"""分析流水线编排：检索结果 -> 聚合统计 -> 中文综述 -> 统一响应体。

供 main.py（在线请求）与 scripts/precache.py（离线预生成）共用，避免重复构建逻辑。
"""
import datetime

from . import analyze, config, review


async def build_payload(
    query: str,
    total: int,
    articles: list[dict],
    include_review: bool = True,
    current_year: int | None = None,
) -> dict:
    if current_year is None:
        current_year = datetime.date.today().year

    stats = analyze.analyze(articles, current_year)

    review_result = None
    if include_review:
        abstracts = [
            (a.get("pmid"), a.get("abstract", ""))
            for a in articles
            if a.get("abstract")
        ][: config.REVIEW_TOP_N]
        if abstracts:
            review_result = await review.generate_review(
                abstracts,
                context={"query": query, "total": total, "stats": stats},
            )
        else:
            review_result = {
                "text": "未检索到含摘要的文献，无法生成综述。",
                "sources": [],
                "mock": config.MOCK_LLM or not config.DASHSCOPE_API_KEY,
            }

    return {
        "query": query,
        "total": total,
        "returned": len(articles),
        "stats": stats,
        "review": review_result,
        "articles": [
            {
                k: a.get(k)
                for k in ("pmid", "title", "journal", "year", "url", "mesh", "impact_factor", "quartile")
            }
            for a in articles
        ],
    }
