#!/usr/bin/env python3
"""回收站取证：解析 $I 元数据文件，列出每一项的原路径、大小、删除时间。

用途：清空回收站之前留一份快照。误删之后靠它找回东西，或者确认删掉的是哪些文件。

用法：
    python recycle_list.py                     # 列出所有盘的回收站
    python recycle_list.py --drive D           # 只看 D 盘
    python recycle_list.py --csv D:\\snap.csv   # 导出 CSV
    python recycle_list.py --limit 20          # 只显示最近 20 条

说明：
    $I 文件是元数据，$R 文件是数据本体。删除 $R 即释放空间，删除 $I 只是删记录。
    清空回收站最快的方式是直接删 $R，不要用 Clear-RecycleBin 处理十万级条目。
"""

import argparse
import csv
import os
import struct
import sys
from datetime import datetime, timedelta

EPOCH = datetime(1601, 1, 1)


def filetime_to_dt(ft):
    try:
        return EPOCH + timedelta(microseconds=ft // 10)
    except (OverflowError, ValueError):
        return None


def parse_i(path):
    """返回 (原路径, 字节大小, 删除时间) 或 None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
            if len(head) < 24:
                return None
            version, size, ft = struct.unpack("<QQQ", head)
            if version == 2:
                raw = f.read(4)
                if len(raw) < 4:
                    return None
                (chars,) = struct.unpack("<I", raw)
                data = f.read(chars * 2)
                original = data.decode("utf-16-le", "replace").rstrip("\x00")
            else:
                data = f.read(520)
                original = data.split(b"\x00")[0].decode("mbcs", "replace")
            return original, size, filetime_to_dt(ft)
    except (OSError, struct.error, UnicodeDecodeError):
        return None


def drive_roots():
    roots = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        base = f"{letter}:\\$Recycle.Bin"
        if os.path.isdir(base):
            roots.append(base)
    return roots


def collect(roots, limit_drive=None):
    items = []
    unreadable = []
    for root in roots:
        if limit_drive and not root.startswith(limit_drive.upper()):
            continue
        try:
            sids = os.listdir(root)
        except PermissionError:
            unreadable.append(root)
            continue
        for sid in sids:
            sid_dir = os.path.join(root, sid)
            if not os.path.isdir(sid_dir):
                continue
            try:
                names = os.listdir(sid_dir)
            except PermissionError:
                unreadable.append(sid_dir)
                continue
            for name in names:
                if not (name.startswith("$I") and len(name) > 2):
                    continue
                info = parse_i(os.path.join(sid_dir, name))
                if not info:
                    continue
                original, size, when = info
                items.append({
                    "original": original,
                    "bytes": size,
                    "deleted_at": when.isoformat(sep=" ", timespec="seconds") if when else "",
                    "meta": os.path.join(sid_dir, name),
                    "data": os.path.join(sid_dir, "$R" + name[2:]),
                })
    items.sort(key=lambda x: x["deleted_at"], reverse=True)
    return items, unreadable


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024


def main():
    ap = argparse.ArgumentParser(description="回收站内容取证")
    ap.add_argument("--drive", help="只看某个盘，如 C 或 D")
    ap.add_argument("--csv", help="导出 CSV 到指定路径")
    ap.add_argument("--limit", type=int, default=0, help="只显示最近 N 条")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    items, unreadable = collect(drive_roots(), args.drive)
    total = sum(i["bytes"] for i in items)
    show = items[: args.limit] if args.limit else items

    print(f"回收站条目 {len(items)} · 合计 {human(total)}")
    if unreadable:
        print(f"无权限读取 {len(unreadable)} 处（用管理员运行可解决）：")
        for p in unreadable[:5]:
            print(f"  {p}")

    for it in show:
        print(f"  {it['deleted_at'] or '未知时间'}  {human(it['bytes']):>10}  {it['original']}")

    if args.csv:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["原路径", "字节", "大小", "删除时间", "元数据文件", "数据文件"])
            for it in items:
                w.writerow([it["original"], it["bytes"], human(it["bytes"]),
                            it["deleted_at"], it["meta"], it["data"]])
        print(f"\n已导出 {len(items)} 条到 {args.csv}")


if __name__ == "__main__":
    main()
