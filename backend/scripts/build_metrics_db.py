"""把外部来源的期刊指标数据集拉下来，写进 SQLite（backend/data/journal_metrics.db）。

两个来源，口径不同，因此在库里分列存放、不合并（原因见 app/journaldb.py 的模块说明）：

  scimago   SCImago Journal Rank 网站导出的 CSV。
            它提供源方**已发布的分区**（SJR Best Quartile）、SJR、近 2 年篇均被引，
            以及期刊类型（Type）与活跃区间（Coverage）——后两者正好能识别
            非期刊条目（会议录、书系）与已停刊期刊。
  openalex  OpenAlex sources API 的 2yr_mean_citedness（近 2 年篇均被引）。
            抓取逻辑复用既有的 scripts/build_metrics_openalex.py，本脚本只负责把它产出的
            JSON 导入库中。注意该 API 会按出口 IP 长时限流（实测 Retry-After ≈ 16 小时），
            限流期间 --live 会失败，此时直接导入磁盘上已有的快照即可。

用法：
    .venv/Scripts/python.exe scripts/build_metrics_db.py scimago
    .venv/Scripts/python.exe scripts/build_metrics_db.py scimago --year 2025
    .venv/Scripts/python.exe scripts/build_metrics_db.py scimago --csv path/to/scimagojr.csv

    .venv/Scripts/python.exe scripts/build_metrics_db.py openalex
    .venv/Scripts/python.exe scripts/build_metrics_db.py openalex --live

    .venv/Scripts/python.exe scripts/build_metrics_db.py all
    .venv/Scripts/python.exe scripts/build_metrics_db.py stats
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import journaldb
from app.journaldb import add_journal, connect, parse_coverage, parse_num, replace_source, set_meta, split_issns

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPENALEX_JSON = os.path.join(BACKEND_DIR, "data", "journal_metrics.json")

SJR_URL = "https://www.scimagojr.com/journalrank.php"
# 网站前置 Cloudflare，裸 User-Agent 会被 403；带上完整浏览器头实测可用（HTTP 200 / 11 MB / ~6s）
SJR_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": SJR_URL,
    "Connection": "keep-alive",
}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _colkey(name: str) -> str:
    """列名归一化：'Citations / Doc. (2years)' -> 'citationsdoc2years'。

    用归一化后的键去认列，不依赖列顺序，也不怕来源改标点写法。
    """
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def fetch_scimago(year=None, timeout=120) -> tuple:
    url = SJR_URL + "?out=xls" + (f"&year={year}" if year else "")
    req = urllib.request.Request(url, headers=SJR_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return url, r.read()


def ingest_scimago(conn, raw: bytes, url: str, year=None) -> dict:
    text = raw.decode("utf-8-sig", "replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";", quotechar='"')
    kmap = {_colkey(k): k for k in (reader.fieldnames or [])}

    def col(row, name):
        real = kmap.get(_colkey(name))
        return (row.get(real) or "").strip() if real else ""

    # 版本年份藏在 'Total Docs. (2025)' 这类列名里
    edition = str(year or "")
    if not edition:
        for k in kmap:
            m = re.search(r"totaldocs(\d{4})", k)
            if m:
                edition = m.group(1)
                break

    retrieved_at = _now()
    replace_source(conn, "scimago")
    counts = Counter()
    for row in reader:
        name = col(row, "Title")
        if not name:
            counts["skipped_no_name"] += 1
            continue
        q = col(row, "SJR Best Quartile")
        if q in {"", "-"}:
            q = None
        h = parse_num(col(row, "H index"))
        cs, ce = parse_coverage(col(row, "Coverage"))
        add_journal(
            conn,
            source="scimago",
            source_id=col(row, "Sourceid") or None,
            name=name,
            type=col(row, "Type") or None,
            publisher=col(row, "Publisher") or None,
            country=col(row, "Country") or None,
            quartile=q,
            quartile_kind="published" if q else None,
            cites_per_doc_2y=parse_num(col(row, "Citations / Doc. (2years)")),
            sjr=parse_num(col(row, "SJR")),
            h_index=int(h) if h is not None else None,
            coverage_start=cs,
            coverage_end=ce,
            categories=col(row, "Categories") or None,
            areas=col(row, "Areas") or None,
            retrieved_at=retrieved_at,
            # SCImago 同时给印刷号与电子号，但不标明哪个是哪个 -> 如实记为 unknown，不猜
            issn_spec=[(i, "unknown") for i in split_issns(col(row, "Issn"))],
        )
        counts["rows"] += 1
        counts[f"type:{col(row, 'Type') or 'unknown'}"] += 1
        if q:
            counts[f"quartile:{q}"] += 1

    set_meta(
        conn,
        "scimago",
        source_name="SCImago Journal Rank (SJR)",
        source_url=url,
        edition_year=edition or None,
        retrieved_at=retrieved_at,
        raw_bytes=len(raw),
        raw_sha256=_sha256(raw),
        rows=counts["rows"],
        quartile_kind="published（源方已发布分区，非本项目推算）",
        metric_field="Citations / Doc. (2years) —— 近 2 年篇均被引。"
        "注意分母含新闻/社论/letters 等非可引用项，因此系统性低于 JCR 影响因子，不可等同于 IF",
        license_note="SCImago 声明：数据可用于非商业用途，需注明出处（SCImago, scimagojr.com）",
    )
    conn.commit()
    return {"rows": counts["rows"], "edition": edition, "counts": counts}


def ingest_openalex(conn, json_path: str) -> dict:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    meta = data.get("meta") or {}
    retrieved_at = meta.get("retrieved_at") or _now()
    journals = data.get("journals") or []

    replace_source(conn, "openalex")
    n_oaid = 0
    for j in journals:
        if not j.get("name"):
            continue
        q = j.get("quartile")
        if j.get("oa_id"):
            n_oaid += 1
        # 离群标记：0 或 >100 的篇均被引对 OpenAlex 兜底条目属明显异常
        #（如停刊旧刊号的 367.0），入库即标，metrics 加载时 SQL 层过滤
        cites = j.get("if")
        flagged = 1 if (cites is None or cites == 0 or (isinstance(cites, (int, float)) and cites > 100)) else 0
        add_journal(
            conn,
            source="openalex",
            source_id=j.get("oa_id"),
            name=j["name"],
            type=None,  # OpenAlex 的这份导出里没有期刊类型字段
            quartile=q,
            quartile_kind="derived" if q else None,
            cites_per_doc_2y=cites,
            works_count=j.get("works_count"),
            flagged=flagged,
            retrieved_at=retrieved_at,
            issn_spec=[(i, "unknown") for i in split_issns(j.get("issn"))],
        )

    set_meta(
        conn,
        "openalex",
        source_name="OpenAlex sources API",
        source_url="https://api.openalex.org/sources",
        imported_from=os.path.relpath(json_path, BACKEND_DIR),
        retrieved_at=retrieved_at,
        rows=len(journals),
        rows_with_oa_id=n_oaid,
        quartile_kind="derived（按近 2 年篇均被引的阈值推算，非官方分区）",
        metric_field=meta.get("if_field") or "summary_stats.2yr_mean_citedness",
        quality_note=meta.get("note") or "",
        limit_note="OpenAlex 会对出口 IP 长时限流；若本次为快照导入，"
                   "请待限流解除后以 --live 重新生成。",
    )
    conn.commit()
    return {"rows": len(journals), "with_oa_id": n_oaid, "retrieved_at": retrieved_at}


def do_scimago(conn, args) -> None:
    if args.csv:
        path = os.path.abspath(os.path.expanduser(args.csv))
        print(f"[scimago] 读取本地 CSV: {path}")
        with open(path, "rb") as f:
            raw = f.read()
        url = f"file://{path}"
    else:
        print(f"[scimago] 下载 {SJR_URL} ...")
        try:
            url, raw = fetch_scimago(args.year)
        except urllib.error.HTTPError as e:
            print(f"[scimago] 下载失败 HTTP {e.code}。")
            print("          该站前置 Cloudflare，可能拦截了本机出口 IP。")
            print("          处理办法：浏览器打开 "
                  f"{SJR_URL}?year={args.year or ''}&out=xls 下载 CSV，")
            print("          再用 --csv <文件路径> 导入。")
            raise SystemExit(1)
        except Exception as e:  # noqa: BLE001
            print(f"[scimago] 下载失败 {type(e).__name__}: {e}")
            raise SystemExit(1)
        print(f"[scimago] 已下载 {len(raw):,} 字节")

    info = ingest_scimago(conn, raw, url, year=args.year)
    print(f"[scimago] 落库 {info['rows']:,} 条（版本年份 {info['edition'] or '未知'}）")
    for k, v in sorted(info["counts"].items()):
        print(f"          {k:<28} {v:,}")


def do_openalex(conn, args) -> None:
    json_path = os.path.abspath(os.path.expanduser(args.json or OPENALEX_JSON))
    if args.live:
        script = os.path.join(BACKEND_DIR, "scripts", "build_metrics_openalex.py")
        print(f"[openalex] 运行抓取脚本 {os.path.relpath(script, BACKEND_DIR)} ...")
        rc = subprocess.call([sys.executable, script])
        if rc != 0:
            print(f"[openalex] 抓取脚本退出码 {rc}，改为导入磁盘上已有快照。")
    if not os.path.exists(json_path):
        print(f"[openalex] 找不到 {json_path}，无法导入。")
        raise SystemExit(1)
    info = ingest_openalex(conn, json_path)
    print(f"[openalex] 落库 {info['rows']:,} 条，其中带 oa_id 的 {info['with_oa_id']:,} 条")
    print(f"[openalex] 数据取自快照 {os.path.relpath(json_path, BACKEND_DIR)}"
          f"（retrieved_at={info['retrieved_at']}）")


def do_stats(conn) -> None:
    s = journaldb.stats(conn)
    if not s:
        print("库里还没有数据，先跑 scimago / openalex。")
        return
    for src, d in s.items():
        print(f"\n=== {src} ===")
        print(f"  期刊条数      {d['journals']:,}")
        print(f"  ISSN 索引行   {d['issn_rows']:,}")
        print(f"  有指标值      {d['with_metric']:,}")
        print(f"  类型分布      {d['by_type']}")
        print(f"  分区分布      {d['by_quartile']}")
        print("  元数据:")
        for k, v in journaldb.get_meta(conn, src).items():
            print(f"    {k} = {str(v)[:110]}")


def do_verify(conn, args) -> None:
    print("\n=== 抽样核对（按 ISSN） ===")
    probes = [
        ("15424863", "CA Cancer J Clin"),
        ("00224936", "JCS Chem Commun（老 OpenAlex 数据里为 367.0）"),
        ("09598146", "BMJ"),
        ("00280836", "Nature"),
        ("10959203", "Science"),
    ]
    for issn, label in probes:
        rows = journaldb.query_by_issn(conn, issn)
        if not rows:
            print(f"  {label:<44} ({issn}) -> 未收录")
            continue
        for r in rows:
            print("  %-44s (%s) -> %-38s 2yr=%-8s %-4s src=%s"
                  % (label, issn, r["name"][:38], r["cites_per_doc_2y"],
                     r["quartile"] or "-", r["source"]))


def main():
    ap = argparse.ArgumentParser(description="把期刊指标数据集拉取并写入 SQLite")
    ap.add_argument("command", choices=["scimago", "openalex", "all", "stats", "verify"])
    ap.add_argument("--year", help="SCImago 版本年份，默认取网站当前版本")
    ap.add_argument("--csv", help="改用人工下载的 SCImago CSV，而不是联网抓取")
    ap.add_argument("--json", help="OpenAlex 快照 JSON 路径，默认 data/journal_metrics.json")
    ap.add_argument("--live", action="store_true", help="OpenAlex 先跑抓取脚本再导入")
    ap.add_argument("--db", help="数据库路径，默认 backend/data/journal_metrics.db")
    args = ap.parse_args()

    conn = connect(args.db or journaldb.DB_PATH)
    print(f"数据库: {args.db or journaldb.DB_PATH}")

    if args.command == "scimago":
        do_scimago(conn, args)
    elif args.command == "openalex":
        do_openalex(conn, args)
    elif args.command == "all":
        do_scimago(conn, args)
        do_openalex(conn, args)
    elif args.command == "stats":
        do_stats(conn)
    elif args.command == "verify":
        do_verify(conn, args)

    if args.command in {"scimago", "openalex", "all"}:
        do_stats(conn)
    conn.close()


if __name__ == "__main__":
    main()
