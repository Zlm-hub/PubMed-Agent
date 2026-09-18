"""把现有 cache/*.json（真实管线产物）导入 literature.db，历史分析不丢。

注意两点：
1. 响应体里的 articles 是投影后的子集（无摘要/ISSN），因此迁移是**有损**的：
   article 落 title/journal/year/mesh，abstract 留空。全量数据的正规入口是
   重新跑一次 pipeline（新版 build_payload 会自动全量落库）——cache/*.json
   对应的 3 个预设词重跑 precache.py 即可补全。
2. 旧缓存没有 rewrite/search_term 字段，一律按 passthrough 记。

用法：
    .venv/Scripts/python.exe scripts/migrate_cache_to_db.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import literaturedb  # noqa: E402


def migrate(cache_dir: str) -> None:
    paths = sorted(glob.glob(os.path.join(cache_dir, "*.json")))
    if not paths:
        print(f"[migrate] {cache_dir} 下没有可迁移的缓存文件")
        return
    conn = literaturedb.connect()
    migrated = skipped = 0
    try:
        for path in paths:
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
            except (json.JSONDecodeError, OSError):
                skipped += 1
                continue
            query = (d.get("query") or "").strip()
            if not query:
                skipped += 1
                continue
            try:
                literaturedb.log_run(
                    term_raw=query,
                    term=query,                     # 旧缓存无改写字段，按透传记
                    rewrite_source="passthrough",
                    retmax=int(d.get("returned") or 0) or 200,
                    total=int(d.get("total") or 0),
                    articles=d.get("articles") or [],
                    stats=d.get("stats") or {},
                    review=d.get("review"),
                    elapsed_ms=None,
                    norm_fn=None,                   # 投影里无原始刊名可再归一，直接用 journal
                )
                migrated += 1
            except Exception as e:  # noqa: BLE001
                print(f"[migrate] {os.path.basename(path)} 失败: {e}")
                skipped += 1
    finally:
        conn.close()
    print(f"[migrate] 完成：成功 {migrated} 个 · 跳过 {skipped} 个")
    conn = literaturedb.connect()
    try:
        for k, v in literaturedb.stats(conn).items():
            print(f"  {k:<16} {v}")
    finally:
        conn.close()


if __name__ == "__main__":
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(backend_dir, "cache")
    migrate(cache_dir)
