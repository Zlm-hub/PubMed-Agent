#!/usr/bin/env python3
"""SQLite 在线备份：把运行期数据库打成一份带时间戳的 tar.gz，并按份数轮转。

用法（在仓库根或任意位置均可）：
    python3 deploy/backup.py                 # 默认写到 deploy/backups/，保留 7 份
    python3 deploy/backup.py --keep 14       # 保留 14 份
    python3 deploy/backup.py --out /mnt/pa-backup   # 拷到另一块盘/挂载点

为什么不用 `cp *.db`：服务运行中数据库随时可能被写入，直接拷文件可能拿到
**撕裂的中间态**（尤其开了 WAL）。这里用 sqlite3 的在线备份 API（`Connection.backup`），
它对源库加读锁、按页复制，**不阻塞写入也不会拷到半截事务**；备份完还会对副本跑
`PRAGMA integrity_check`，把「备份文件其实坏了」这种情况当场暴露出来。

边界（如实说明）：本脚本只做「本机快照 + 轮转」，不含异地容灾。要真正防灾，
请把 `--out` 指到另一块盘/另一台机器（如挂载的 NAS、对象存储挂载点），并自行监控
脚本退出码与备份目录大小。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import shutil
import sqlite3
import sys
import tarfile
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 需要备份的库：容器里都落在挂载卷 deploy/data/；本机开发另有 backend/data/
CANDIDATE_DIRS = ("deploy/data", "backend/data")
# 随库一起备份的小文件（可重生的指标快照与元数据，带上省得重建）
EXTRA_FILES = ("deploy/data/journal_metrics.json", "backend/data/journal_metrics.json")


def find_dbs() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for d in CANDIDATE_DIRS:
        for p in sorted((ROOT / d).glob("*.db")):
            if p not in out:
                out.append(p)
    return out


def backup_one(src: pathlib.Path, dest: pathlib.Path) -> tuple[bool, str]:
    """在线备份单个库并校验副本；返回 (是否成功, 说明)。"""
    try:
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s:
            with sqlite3.connect(dest) as d:
                s.backup(d)  # 在线备份 API：不需要停服，也不用拷 WAL
        with sqlite3.connect(dest) as d:
            row = d.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0] != "ok":
            return False, f"integrity_check 未通过：{row}"
        size = dest.stat().st_size
        return True, f"{size / 1024:.0f} KB"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def rotate(out_dir: pathlib.Path, keep: int) -> list[str]:
    """按文件名时间戳保留最新 keep 份，其余删除。"""
    archives = sorted(out_dir.glob("pa-backup-*.tar.gz"))
    removed = []
    for old in archives[:-keep] if keep > 0 else []:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            pass
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="PubMed Analytics 数据库备份")
    ap.add_argument("--out", default=str(ROOT / "deploy" / "backups"), help="备份输出目录")
    ap.add_argument("--keep", type=int, default=7, help="保留份数（0 = 不轮转）")
    args = ap.parse_args()

    dbs = find_dbs()
    if not dbs:
        print("!! 没找到任何 .db —— 检查 deploy/data 与 backend/data 是否存在", file=sys.stderr)
        return 2

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = out_dir / f"pa-backup-{stamp}.tar.gz"

    failed = 0
    # ignore_cleanup_errors：Windows 上磁盘文件句柄释放略滞后，清理临时目录可能报
    # PermissionError —— 备份已经完成，不该因此让脚本以异常退出（Linux 上无此问题）。
    with tempfile.TemporaryDirectory(prefix="pa-backup-", ignore_cleanup_errors=True) as tmp:
        stage = pathlib.Path(tmp)
        print(f"==> 备份 {len(dbs)} 个库 → {archive}")
        for db in dbs:
            dest = stage / f"{db.parent.name}__{db.name}"
            ok, note = backup_one(db, dest)
            flag = "OK  " if ok else "FAIL"
            print(f"    [{flag}] {db.relative_to(ROOT)}  {note}")
            failed += 0 if ok else 1
        for extra in EXTRA_FILES:
            p = ROOT / extra
            if p.exists():
                shutil.copy2(p, stage / f"{p.parent.name}__{p.name}")
                print(f"    [OK  ] {extra}  {p.stat().st_size / 1024:.0f} KB")
        with tarfile.open(archive, "w:gz") as tar:
            for f in sorted(stage.iterdir()):
                tar.add(f, arcname=f.name)

    removed = rotate(out_dir, args.keep)
    if removed:
        print("==> 轮转删除：" + "、".join(removed))
    print(f"==> 完成：{archive}（{archive.stat().st_size / 1024:.0f} KB）")
    if failed:
        print(f"!! 有 {failed} 个库备份失败，请检查上面 FAIL 行", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
