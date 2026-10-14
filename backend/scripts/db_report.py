"""盘点四个 SQLite 库的真实结构与体量（只读，不写任何东西）。

运行：backend/.venv/Scripts/python.exe scripts/db_report.py
"""
import os
import sqlite3
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
DBS = [
    ("journal_metrics.db", "期刊指标库（只读，构建期生成）"),
    ("literature.db", "文献库（运行期实时写入）"),
    ("sessions.db", "会话库（前端交互驱动）"),
    ("users.db", "用户库（2026-09-20 新增）"),
]


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} B"


for name, desc in DBS:
    p = DATA / name
    print("=" * 68)
    if not p.is_file():
        print(f"{name}  —— 不存在（{desc}）")
        continue
    size = human(p.stat().st_size)
    wal = p.with_name(p.name + "-wal")
    print(f"{name}  —— {desc}")
    print(f"  文件大小 {size}" + (f"  (+WAL {human(wal.stat().st_size)})" if wal.is_file() else ""))
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    tables = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for t in tables:
        try:
            n = conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
        except sqlite3.Error as e:
            n = f"err({e})"
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({t})")]
        idx = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? AND name NOT LIKE 'sqlite_%'",
                (t,),
            )
        ]
        print(f"  - {t}: {n} 行 / {len(cols)} 列")
        print(f"      列: {', '.join(cols)}")
        if idx:
            print(f"      索引: {', '.join(idx)}")
    conn.close()
print("=" * 68)
