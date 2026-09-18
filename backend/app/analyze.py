"""聚合分析：年份分布 / 分区分布 / IF 统计 / 词频 / 主题 / 近5年Top100。"""
import datetime
import re
from collections import Counter

from . import metrics

STOPWORDS = set("""
a an and the of to in on for with from by as at is are be been being was were
this that these those their our your his her its their we you they i he she it
not no nor or but if then than so such can may might will would could should
into out over under between within without about against during before after
study studies using used use based analysis results showed show shows found
find findings method methods approach approaches data patients cases case group
groups control vs compared comparison effect effects impact role function model
human humans mouse mice cell cells cells protein proteins gene genes expression
level levels high low significant significantly associated association related
recently however thus therefore also more most other others two three one new
review article articles research clinical molecular biological via per among
""".split())

# 泛化 MeSH 主题词（无方向区分度，过滤以免刷屏研究方向标签）
GENERIC_MESH = set("""
humans animals male female rats mice adolescent adult aged child infant
middle aged young adult male female animals humans neoplasm neoplasms disease
diseases cell cells cells cells tissue tissues tissues blood treatment therapies
therapy therapeutics diagnosis diagnostic methods mechanism mechanisms model
models signal signaling pathway pathways expression gene genes protein proteins
risk factors prognosis outcome outcomes incidence prevalence mortality
""".split())

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]{2,}")


def _tokenize(text: str) -> list[str]:
    toks = []
    for m in TOKEN_RE.findall(text or ""):
        w = m.lower()
        if w in STOPWORDS or len(w) < 3:
            continue
        toks.append(w)
    return toks


def enrich_articles(articles: list[dict]) -> list[dict]:
    for a in articles:
        m = metrics.enrich(a.get("journal", ""), a.get("issn", ""))
        a["impact_factor"] = m["if"]
        a["quartile"] = m["quartile"]
        a["metric_known"] = m["known"]
    return articles


def year_distribution(articles: list[dict]) -> list[dict]:
    c = Counter(a["year"] for a in articles if a.get("year"))
    return [{"year": y, "count": c[y]} for y in sorted(c)]


def quartile_distribution(articles: list[dict]) -> list[dict]:
    c = Counter(a.get("quartile") or "未知" for a in articles)
    order = ["Q1", "Q2", "Q3", "Q4", "未知"]
    return [{"quartile": q, "count": c.get(q, 0)} for q in order if c.get(q, 0) > 0]


def if_statistics(articles: list[dict]) -> dict:
    vals = [a["impact_factor"] for a in articles if isinstance(a.get("impact_factor"), (int, float))]
    if not vals:
        return {"known_count": 0, "mean": None, "median": None, "max": None, "min": None}
    vals_sorted = sorted(vals)
    n = len(vals_sorted)
    median = vals_sorted[n // 2] if n % 2 else (vals_sorted[n // 2 - 1] + vals_sorted[n // 2]) / 2
    return {
        "known_count": n,
        "mean": round(sum(vals) / n, 2),
        "median": round(median, 2),
        "max": max(vals),
        "min": min(vals),
    }


def word_frequency(articles: list[dict], top: int = 80) -> list[dict]:
    counter = Counter()
    for a in articles:
        text = " ".join([
            a.get("title", ""),
            a.get("abstract", ""),
            " ".join(a.get("mesh", [])),
            " ".join(a.get("keywords", [])),
        ])
        counter.update(_tokenize(text))
    return [{"word": w, "count": c} for w, c in counter.most_common(top)]


def research_topics(articles: list[dict], top: int = 6) -> list[dict]:
    """用 MeSH 主题词频次作为研究方向标签（纯聚类，不用 LLM）。"""
    c = Counter()
    for a in articles:
        for mh in a.get("mesh", []):
            term = mh.split("/")[0].strip()  # 去掉限定词
            if term and term.lower() not in GENERIC_MESH:
                c[term] += 1
    if len(c) < top:
        # 退回用高频词补足（同样排除泛词）
        for w in word_frequency(articles, top * 3):
            if w["word"] not in GENERIC_MESH and w["word"] not in c:
                c[w["word"]] += w["count"]
    return [{"topic": t, "count": n} for t, n in c.most_common(top)]


def top100_by_impact(articles: list[dict], current_year: int | None = None) -> list[dict]:
    """近 5 年按影响因子降序取前 100。

    若近 5 年文献不足 100 篇（如 Alzheimer 这类经典主题，relevance 排序会带回较多旧文献），
    则按年份就近回补至 100 篇，并在 top100_meta 里如实标注补足情况——保证 F3 的"前 100"始终可交付。
    """
    if current_year is None:
        current_year = datetime.date.today().year
    cutoff = current_year - 5
    recent = [a for a in articles if isinstance(a.get("year"), int) and a["year"] >= cutoff]
    others = [a for a in articles if a not in recent]

    def sort_key(a):
        ifv = a.get("impact_factor")
        known = isinstance(ifv, (int, float))
        return (0 if known else 1, -(ifv if known else 0), -(a.get("year") or 0))

    recent.sort(key=sort_key)
    others.sort(key=sort_key)

    picked = recent[:100]
    extended = 0
    if len(picked) < 100:
        # 近 5 年不够，按年份就近（新→旧）回补
        others.sort(key=lambda a: -(a.get("year") or 0))
        need = 100 - len(picked)
        picked += others[:need]
        extended = min(need, len(others))

    out = []
    for a in picked:
        out.append({
            "pmid": a.get("pmid"),
            "title": a.get("title", ""),
            "journal": a.get("journal", ""),
            "year": a.get("year"),
            "impact_factor": a.get("impact_factor"),
            "quartile": a.get("quartile"),
            "url": a.get("url", ""),
            "in_recent_5y": bool(isinstance(a.get("year"), int) and a["year"] >= cutoff),
        })
    return out


def top100_meta(articles: list[dict], current_year: int | None = None) -> dict:
    if current_year is None:
        current_year = datetime.date.today().year
    cutoff = current_year - 5
    recent = [a for a in articles if isinstance(a.get("year"), int) and a["year"] >= cutoff]
    return {
        "window_years": 5,
        "cutoff_year": cutoff,
        "recent_count": len(recent),
        "total_count": len(articles),
        "extended": len(recent) < 100,
    }


def analyze(articles: list[dict], current_year: int | None = None) -> dict:
    articles = enrich_articles(articles)
    return {
        "year_distribution": year_distribution(articles),
        "quartile_distribution": quartile_distribution(articles),
        "if_statistics": if_statistics(articles),
        "wordcloud": word_frequency(articles),
        "topics": research_topics(articles),
        "top100": top100_by_impact(articles, current_year),
        "top100_meta": top100_meta(articles, current_year),
    }
