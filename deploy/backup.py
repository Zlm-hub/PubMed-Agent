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

# 备份目标目录，按优先级：部署形态下容器实际读写的是 deploy/data（挂载卷），
# 本机开发才用 backend/data。**两者存在同名库，不能都备**——既会撞名，也是白占体积
# （2026-10-14 在服务器上实测：两份 journal_metrics.db 打进了同一个归档条目）。
DATA_DIRS = ("deploy/data", "backend/data")


def collect() -> tuple[list[pathlib.Path], list[pathlib.Path]]:
    """按优先级选一个数据目录，返回 (数据库列表, 附带的小文件列表)。"""
    for rel in DATA_DIRS:
        d = ROOT / rel
        if not d.is_dir():
            continue
        dbs = sorted(d.glob("*.db"))
        if not dbs:
            continue
        extras = [p for p in (d / "journal_metrics.json",) if p.exists()]
        return dbs, extras
    return [], []


def staged_name(p: pathlib.Path) -> str:
    """归档内的文件名 = 完整相对路径拍平（`deploy__data__users.db`）。

    带目录前缀是为了「恢复时一眼知道该放回哪儿」，也避免不同目录同名库互相覆盖。
    """
    return str(p.relative_to(ROOT)).replace("\\", "__").replace("/", "__")


def backup_one(src: pathlib.Path, dest: pathlib.Path) -> tuple[bool, str]:
    """在线备份单个库并校验副本；返回 (是否成功, 说明)。"""
    try:
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s:
            with sqlite3.connect(dest) as d:
                s.backup(d)  # 在线备份 API：不需要停服，也不用拷 WAL
        # 副本切回 DELETE 日志模式：源库是 WAL，副本会继承 WAL 语义并生成 -wal/-shm
        # 伴生文件（2026-10-14 在服务器上实测踩到：归档时那对文件已被 SQLite 删掉 →
        # FileNotFoundError，还留下半截归档）。切回 DELETE 后副本自包含、恢复更简单。
        # 顺带在同一个连接里做完整性校验（避免开只读连接又触发 sidecar）。
        with sqlite3.connect(dest) as d:
            d.execute("PRAGMA journal_mode=DELETE")
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

    dbs, extras = collect()
    if not dbs:
        print(f"!! 没找到任何 .db —— 检查 {' 与 '.join(DATA_DIRS)} 是否存在", file=sys.stderr)
        return 2
    used_dir = dbs[0].parent.relative_to(ROOT)

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = out_dir / f"pa-backup-{stamp}.tar.gz"

    failed = 0
    staged: list[pathlib.Path] = []
    # ignore_cleanup_errors：Windows 上磁盘文件句柄释放略滞后，清理临时目录可能报
    # PermissionError —— 备份已经完成，不该因此让脚本以异常退出（Linux 上无此问题）。
    with tempfile.TemporaryDirectory(prefix="pa-backup-", ignore_cleanup_errors=True) as tmp:
        stage = pathlib.Path(tmp)
        print(f"==> 数据目录：{used_dir}（另一处同名目录按优先级跳过，避免撞名与重复体积）")
        print(f"==> 备份 {len(dbs)} 个库 → {archive}")
        for db in dbs:
            dest = stage / staged_name(db)
            ok, note = backup_one(db, dest)
            flag = "OK  " if ok else "FAIL"
            print(f"    [{flag}] {db.relative_to(ROOT)}  {note}")
            failed += 0 if ok else 1
            if ok:
                staged.append(dest)
        for extra in extras:
            dest = stage / staged_name(extra)
            shutil.copy2(extra, dest)
            staged.append(dest)
            print(f"    [OK  ] {extra.relative_to(ROOT)}  {extra.stat().st_size / 1024:.0f} KB")

        if failed:
            # 有库没备成功就**不生成归档**：一份"少了个库"的备份比没有备份更危险，
            # 因为恢复时才发现缺失已经太晚。直接以非零退出码让 cron / 监控报警。
            print(f"!! 有 {failed} 个库备份失败，已放弃本次归档（不做半截备份）", file=sys.stderr)
            return 1

        # 只归档**明确收集到的**文件（不要 iterdir 后逐个 add：目录内容随时可能被
        # SQLite 增删，列目录与打包之间会打架 —— 服务器实测踩到的 FileNotFoundError）
        try:
            with tarfile.open(archive, "w:gz") as tar:
                for f in staged:
                    tar.add(f, arcname=f.name)
        except Exception as e:  # noqa: BLE001
            # 打包中途失败会留下**半截归档**——比没有更坏（看起来像有备份）。
            # 立刻删掉并以非零退出，让 cron / 监控看见。
            try:
                archive.unlink(missing_ok=True)
            except OSError:
                pass
            print(f"!! 归档失败（已删除半截文件）：{type(e).__name__}: {e}", file=sys.stderr)
            return 1

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
