"""用 OpenAlex 开放数据扩充期刊指标数据集。

策略（两级）：
  1. 保留 data/journal_metrics.json 里手工整理的 131 本主流刊（JCR 近似值，优先级最高）；
  2. 从 OpenAlex 拉取高产出期刊（按 works_count 排序取前 N 页），
     以及为缺失的策展刊名做定点查询，补齐「全部 ISSN（含电子刊号）+ 近2年篇均被引」。

产出仍写回 data/journal_metrics.json，含 meta 说明来源与分区规则。
运行：.venv/Scripts/python.exe scripts/build_metrics_openalex.py
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.metrics import _norm_name  # noqa: E402

DATA_PATH = os.path.join(ROOT, "data", "journal_metrics.json")
MAILTO = "demo@example.com"
API = "https://api.openalex.org/sources"
PAGES = int(os.getenv("OA_PAGES", "6"))            # works_count 高产出刊页数（每页 200）
CITED_PAGES = int(os.getenv("OA_CITED_PAGES", "5"))  # cited_by_count 高被引刊页数
PER_PAGE = 200
SLEEP = float(os.getenv("OA_SLEEP", "0.4"))          # 请求间隔（秒）

# 分区近似阈值（基于近2年篇均被引；非官方 JCR 分区，仅供演示）
Q_CUTS = [(6.0, "Q1"), (3.0, "Q2"), (1.5, "Q3")]


def http_json(url: str, tries: int = 4):
    """带 429 长退避的 GET。OpenAlex 在共享出口 IP 上会限流，需要耐心等。"""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"pubmed-analytics-demo (mailto:{MAILTO})"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 15 * (i + 1)
                print(f"    ~ 429 rate-limited, backoff {wait}s ({i+1}/{tries})")
                time.sleep(wait)
                continue
            if i == tries - 1:
                print(f"    ! http {e.code}")
                return None
            time.sleep(2.0 * (i + 1))
        except Exception as e:
            if i == tries - 1:
                print(f"    ! request failed: {type(e).__name__} {e}")
                return None
            time.sleep(1.5 * (i + 1))


def quartile_of(citedness):
    if citedness is None:
        return None
    for cut, q in Q_CUTS:
        if citedness >= cut:
            return q
    return "Q4"


def norm_issns(raw):
    out = []
    for t in raw or []:
        k = str(t).replace("-", "").strip().upper()
        if len(k) == 8 and k.isalnum():
            out.append(k)
    return out


def fmt_issns(issns):
    """1044-5803 的形式，逗号分隔（metrics 加载时会拆分）。"""
    return ",".join(f"{k[:4]}-{k[4:]}" for k in issns)


def to_entry(src: dict) -> dict:
    st = src.get("summary_stats") or {}
    cited = st.get("2yr_mean_citedness")
    issns = norm_issns(src.get("issn") or [])
    if src.get("issn_l"):
        issns = norm_issns([src["issn_l"]] + issns)
    return {
        "name": (src.get("display_name") or "").strip(),
        "issn": fmt_issns(issns),
        "if": round(cited, 1) if isinstance(cited, (int, float)) else None,
        "quartile": quartile_of(cited),
        "works_count": src.get("works_count"),
        "source": "openalex",
    }


def main():
    base = {"meta": {}, "journals": []}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            base = json.load(f)
    curated = base.get("journals", [])
    print(f"[1/3] 载入手工策展期刊 {len(curated)} 本")

    by_name = {}
    for j in curated:
        j["source"] = j.get("source") or "curated"
        n = _norm_name(j.get("name", ""))
        if n:
            by_name[n] = j

    print(f"[2/3] 拉取 OpenAlex 期刊（works_count 高产出 {PAGES} 页 + cited_by_count 高被引 {CITED_PAGES} 页）...")
    added, seen_oa, issn_fixed = 0, set(), 0
    pulls = (
        [(f"works_count:desc", p) for p in range(1, PAGES + 1)]
        + [(f"cited_by_count:desc", p) for p in range(1, CITED_PAGES + 1)]
    )
    for sort_key, p in pulls:
        url = (
            f"{API}?filter=type:journal&sort={sort_key}"
            f"&per-page={PER_PAGE}&page={p}&mailto={MAILTO}"
        )
        d = http_json(url)
        if not d:
            continue
        for src in d.get("results", []):
            oid = src.get("id")
            if oid in seen_oa:
                continue
            seen_oa.add(oid)
            n = _norm_name(src.get("display_name", ""))
            if not n:
                continue
            existing = by_name.get(n)
            if existing is not None:
                # 命中的是策展刊：只补 ISSN（含电子刊号），保留策展 IF/分区
                e = to_entry(src)
                old = norm_issns(str(existing.get("issn", "")).replace(",", " ").split())
                new = norm_issns(e.get("issn", "").replace(",", " ").split())
                merged = list(dict.fromkeys(new + old))
                if len(merged) > len(old):
                    existing["issn"] = fmt_issns(merged)
                    issn_fixed += 1
                continue
            e = to_entry(src)
            if not e["name"]:
                continue
            by_name[n] = e
            curated.append(e)
            added += 1
        print(f"    {sort_key} page {p}: 新增 {added} 本 / 补 ISSN {issn_fixed} 本")
        time.sleep(SLEEP)

    known = sum(1 for j in curated if isinstance(j.get("if"), (int, float)))
    out = {
        "meta": {
            "source": "curated(JCR 近似) + OpenAlex sources API（真实引文指标，开放数据）",
            "year": 2025,
            "count": len(curated),
            "if_field": "OpenAlex summary_stats.2yr_mean_citedness（近2年篇均被引，用作影响因子近似）",
            "quartile_rule": "IF>=6 Q1 / 3~6 Q2 / 1.5~3 Q3 / <1.5 Q4（阈值近似，非官方 JCR 分区）",
            "note": "分区为引文指标近似值，仅供演示；缺失期刊在 metrics 中降级为 unknown/None。",
        },
        "journals": curated,
    }
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n完成：{len(curated)} 本期刊，其中带 IF 指标 {known} 本 -> {DATA_PATH}")


if __name__ == "__main__":
    main()
