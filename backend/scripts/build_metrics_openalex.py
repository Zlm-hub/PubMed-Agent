"""从 OpenAlex 开放数据构建期刊指标数据集（两阶段）。

原则：**数据集里每一条都必须能溯源到一次真实的 API 返回，不接受任何手工录入的指标值。**
- 影响因子字段取 OpenAlex `summary_stats.2yr_mean_citedness`（近 2 年篇均被引，用作 IF 近似）；
- 分区按阈值近似分档（非官方 JCR 分区）；
- 每条都记下 `oa_id`（OpenAlex source id），可逐条回查。

两个阶段：
  阶段 1「榜单拉取」：按 works_count / cited_by_count 取 OpenAlex 高位期刊。
  阶段 2「关键词回填」：光靠榜单补不上长尾专刊——`Ageing research reviews`
  `Alzheimer's research & therapy` 这类 PubMed 常见刊永远进不了前 N 名。
  所以对预设关键词各跑一次真实检索，收集结果里出现、但榜单里没有的刊名，
  再逐个用 OpenAlex 的 display_name.search 查出真值入库（**按归一化刊名精确相等才采纳**，
  避免张冠李戴）。种子只是检索词，值仍然 100% 来自 API。

历史说明：上一版曾把 131 本「手工策展刊」与 90 本「补录刊」写死在
`gen_metrics.py` / `add_curated_extras.py` 里（那是模型凭记忆给出的近似 JCR 值，无官方出处），
并与 OpenAlex 真值混在同一个 `if` 字段里参与排序，污染了 F3 排序。
那两个脚本与本脚本对旧文件的「保留策展值」逻辑已全部删除。

运行：.venv/Scripts/python.exe scripts/build_metrics_openalex.py
可调：OA_PAGES / OA_CITED_PAGES / OA_SLEEP / OA_BACKFILL=0 关闭阶段 2
"""
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import config, pubmed  # noqa: E402
from app.metrics import _norm_name  # noqa: E402

DATA_PATH = os.path.join(ROOT, "data", "journal_metrics.json")
MAILTO = os.getenv("OA_MAILTO", "demo@example.com")
API = "https://api.openalex.org/sources"
PAGES = int(os.getenv("OA_PAGES", "12"))             # works_count 高产出刊页数（每页 200）
CITED_PAGES = int(os.getenv("OA_CITED_PAGES", "8"))  # cited_by_count 高被引刊页数
PER_PAGE = 200
SLEEP = float(os.getenv("OA_SLEEP", "0.4"))
BACKFILL = os.getenv("OA_BACKFILL", "1") != "0"
BACKFILL_MAX = int(os.getenv("OA_BACKFILL_MAX", "200"))  # 每个种子词取多少篇文献找刊名

# 分区近似阈值（基于近 2 年篇均被引；非官方 JCR 分区）
Q_CUTS = [(6.0, "Q1"), (3.0, "Q2"), (1.5, "Q3")]


def http_json(url: str, tries: int = 4):
    """带 429 长退避的 GET。OpenAlex 在共享出口 IP 上会限流，需要耐心等。"""
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"pubmed-analytics-demo (mailto:{MAILTO})"}
            )
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 15 * (i + 1)
                print(f"    ~ 429 rate-limited, backoff {wait}s ({i + 1}/{tries})")
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
    return None


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


def to_entry(src: dict):
    """OpenAlex source -> 数据集条目。无引文指标的刊直接丢弃（保留它不如降级为未知）。"""
    st = src.get("summary_stats") or {}
    cited = st.get("2yr_mean_citedness")
    if not isinstance(cited, (int, float)):
        return None
    name = (src.get("display_name") or "").strip()
    if not name:
        return None

    issns = norm_issns(src.get("issn") or [])
    if src.get("issn_l"):
        issns = norm_issns([src["issn_l"]] + issns)
    return {
        "name": name,
        "issn": fmt_issns(list(dict.fromkeys(issns))),
        "if": round(cited, 1),
        "quartile": quartile_of(cited),
        "works_count": src.get("works_count"),
        "source": "openalex",
        "oa_id": src.get("id"),
    }


class Catalog:
    """按归一化刊名与 ISSN 双键去重，并记录 oa_id 防重复。"""

    def __init__(self):
        self.journals: list[dict] = []
        self.by_name: dict[str, dict] = {}
        self.by_issn: dict[str, dict] = {}
        self.seen_oa: set[str] = set()

    def offers(self, src: dict) -> dict | None:
        if src.get("id") in self.seen_oa:
            return None
        self.seen_oa.add(src.get("id"))
        return to_entry(src)

    def add(self, e: dict) -> bool:
        n = _norm_name(e["name"])
        if not n or n in self.by_name:
            return False
        issns = norm_issns(e["issn"].replace(",", " ").split())
        if any(k in self.by_issn for k in issns):
            return False
        self.by_name[n] = e
        for k in issns:
            self.by_issn[k] = e
        self.journals.append(e)
        return True


def pull_top_sources(cat: Catalog) -> int:
    pulls = [(f"works_count:desc", p) for p in range(1, PAGES + 1)] + [
        (f"cited_by_count:desc", p) for p in range(1, CITED_PAGES + 1)
    ]
    print(f"[阶段 1] 榜单拉取：works_count {PAGES} 页 + cited_by_count {CITED_PAGES} 页…")
    ok = 0
    for sort_key, p in pulls:
        url = (
            f"{API}?filter=type:journal&sort={sort_key}"
            f"&per-page={PER_PAGE}&page={p}&mailto={MAILTO}"
        )
        d = http_json(url)
        if not d:
            continue
        ok += 1
        for src in d.get("results", []):
            e = cat.offers(src)
            if e:
                cat.add(e)
        print(f"    {sort_key} page {p}: 累计 {len(cat.journals)} 本")
    return ok


def collect_missing_journals(cat: Catalog) -> list[str]:
    """对每个预设关键词跑真实检索，收集「结果里出现但本次构建未覆盖」的刊名。

    覆盖判断直接看本次构建的 Catalog，而不是磁盘上的旧文件——
    否则「回填哪些刊」会取决于上一次构建的产物，不可复现。
    """
    missing: dict[str, int] = {}
    for q in config.PRESETS:
        try:
            _total, articles = asyncio.run(pubmed.search_pubmed(q, BACKFILL_MAX))
        except Exception as e:
            print(f"    ! 检索 {q!r} 失败：{type(e).__name__} {e}")
            continue
        before = len(missing)
        for a in articles:
            j = (a.get("journal") or "").strip()
            if not j or _norm_name(j) in cat.by_name:
                continue          # 本次构建已覆盖，省一次 API 调用
            missing[j] = missing.get(j, 0) + 1
        print(f"    {q!r}: {len(articles)} 篇 -> 新增待查刊名 {len(missing) - before} 个")
    return sorted(missing, key=lambda k: -missing[k])


def resolve_one(name: str) -> dict | None:
    """用 OpenAlex 检索该刊名，只采纳「归一化后精确相等」的候选，避免张冠李戴。"""
    url = (
        f"{API}?filter=display_name.search:{urllib.parse.quote(name)}"
        f"&per-page=5&mailto={MAILTO}"
    )
    d = http_json(url)
    if not d:
        return None
    target = _norm_name(name)
    for src in d.get("results", []):
        if _norm_name(src.get("display_name", "")) == target:
            return src
    return None


def backfill_from_presets(cat: Catalog) -> tuple[int, int]:
    print(f"[阶段 2] 关键词回填：种子词 {config.PRESETS}（每词取 {BACKFILL_MAX} 篇）")
    missing = collect_missing_journals(cat)
    print(f"    合计待查刊名 {len(missing)} 个，逐个走 OpenAlex 检索…")
    hit, miss = 0, 0
    for i, name in enumerate(missing, 1):
        src = resolve_one(name)
        if src is not None:
            e = cat.offers(src)
            if e and cat.add(e):
                hit += 1
                print(f"    [{i}/{len(missing)}] ✓ {name} -> IF={e['if']} {e['quartile']}")
            else:
                miss += 1
        else:
            miss += 1
            print(f"    [{i}/{len(missing)}] ✗ {name}（OpenAlex 无同名刊，保持未知）")
        time.sleep(SLEEP)
    return hit, miss


def main():
    print("[1/3] 从零构建（不读取任何既存的策展值）")
    cat = Catalog()

    ok_pages = pull_top_sources(cat)
    print(f"    榜单阶段完成：{len(cat.journals)} 本（成功页 {ok_pages}）")

    backfill_hit = backfill_miss = 0
    if BACKFILL:
        backfill_hit, backfill_miss = backfill_from_presets(cat)
        print(f"    回填阶段完成：命中 {backfill_hit}，未查到 {backfill_miss}")
    else:
        print("[阶段 2] 已通过 OA_BACKFILL=0 关闭")

    out = {
        "meta": {
            "source": "OpenAlex sources API（api.openalex.org/sources，开放数据）",
            "source_detail": "全部条目由 scripts/build_metrics_openalex.py 逐条取自 API，无手工录入值；"
            "每条带 oa_id，可回查",
            "retrieved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "count": len(cat.journals),
            "if_field": "OpenAlex summary_stats.2yr_mean_citedness（近 2 年篇均被引，用作影响因子近似）",
            "quartile_rule": "IF>=6 Q1 / 3~6 Q2 / 1.5~3 Q3 / <1.5 Q4（阈值近似，非官方 JCR 分区）",
            "build_stages": (
                f"榜单拉取（works_count {PAGES} 页 + cited_by_count {CITED_PAGES} 页）"
                f" + 关键词回填（种子 {config.PRESETS}，归一化刊名精确匹配，命中 {backfill_hit}）"
            ),
            "note": "口径唯一：所有条目的 if 字段同为 2yr_mean_citedness。"
            "未收录的期刊在 metrics 中降级为 unknown/None，不做任何猜测。",
        },
        "journals": cat.journals,
    }
    # 只写 JSON 快照。落库（SQLite）由 scripts/build_metrics_db.py 的 `openalex` 子命令负责，
    # 它读取本 JSON 并写入 journal_metrics.db，职责单一。
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    from collections import Counter

    q = Counter(j["quartile"] for j in cat.journals)
    print(f"\n完成：{len(cat.journals)} 本")
    print(f"分区分布：{dict(sorted(q.items()))}")
    print(f"写出 JSON 快照 -> {DATA_PATH}（落库请跑 scripts/build_metrics_db.py openalex）")


if __name__ == "__main__":
    main()
