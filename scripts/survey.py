#!/usr/bin/env python3
"""目录体检：统计体积与扩展名分布，抽样看真实内容，给出删除风险结论。

用途：在删除任何目录之前，确认它到底是什么。目录名会骗人。

用法：
    python survey.py "C:\\path\\to\\dir" [更多路径...]
    python survey.py "C:\\path" --sample 5 --top 12
    python survey.py "C:\\path" --json > survey.json

结论口径：
    SAFE    无用户产出物，且都是临时/缓存类扩展名
    BACKUP  含用户产出物超过 10%，或含文档/图片/设计稿类文件
    EMPTY   没有文件
"""

import argparse
import json
import os
import random
import sys

# 用户产出物：出现即视为真实数据，必须备份后再删
USER_ASSET_EXTS = {
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf",
    ".txt", ".md", ".rtf", ".csv", ".wps", ".et", ".dps",
    ".html", ".htm", ".svg", ".indd", ".key", ".numbers", ".pages",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff",
    ".psd", ".ai", ".eps", ".sketch", ".fig", ".dwg", ".dxf",
    ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".flac",
    ".zip", ".rar", ".7z", ".db", ".sqlite", ".mdb",
}

# 明确的临时/缓存类：只有它们时可以放心删
JUNK_EXTS = {
    ".tmp", ".temp", ".log", ".cache", ".bak", ".old",
    ".dmp", ".etl", ".evtx", ".pf", ".db-wal", ".db-shm",
    ".crdownload", ".part", ".partial",
}

THRESHOLD = 0.10  # 用户产出物占比阈值


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024


def walk(root):
    """返回 (文件数, 总体积, 扩展名统计, 文件样本, 子目录数)。"""
    count = 0
    total = 0
    by_ext = {}
    files = []
    dirs = 0
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            entries = list(os.scandir(cur))
        except (PermissionError, OSError):
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    dirs += 1
                    stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    size = e.stat(follow_symlinks=False).st_size
                    count += 1
                    total += size
                    ext = os.path.splitext(e.name)[1].lower()
                    slot = by_ext.setdefault(ext, [0, 0])
                    slot[0] += 1
                    slot[1] += size
                    files.append((e.path, size))
            except OSError:
                continue
    return count, total, by_ext, files, dirs


def judge(by_ext, count):
    asset_files = sum(v[0] for k, v in by_ext.items() if k in USER_ASSET_EXTS)
    asset_bytes = sum(v[1] for k, v in by_ext.items() if k in USER_ASSET_EXTS)
    junk_files = sum(v[0] for k, v in by_ext.items() if k in JUNK_EXTS)
    ratio = asset_files / count if count else 0.0
    if count == 0:
        return "EMPTY", asset_files, asset_bytes, ratio
    if ratio > THRESHOLD:
        return "BACKUP", asset_files, asset_bytes, ratio
    if junk_files >= count * 0.5:
        return "SAFE", asset_files, asset_bytes, ratio
    # 既无用户产出物，也不是明确的垃圾：保守归入 BACKUP
    return "BACKUP", asset_files, asset_bytes, ratio


def report(path, sample, top, as_json):
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        print(f"[跳过] 路径不存在：{path}", file=sys.stderr)
        return None

    count, total, by_ext, files, dirs = walk(path)
    verdict, asset_files, asset_bytes, ratio = judge(by_ext, count)
    ranked = sorted(by_ext.items(), key=lambda kv: kv[1][1], reverse=True)[:top]

    picks = []
    if files:
        rnd = random.Random(7)  # 固定种子，结果可复现
        picks = rnd.sample(files, min(sample, len(files)))
        picks.sort(key=lambda x: -x[1])

    result = {
        "path": path,
        "files": count,
        "bytes": total,
        "dirs": dirs,
        "verdict": verdict,
        "asset_files": asset_files,
        "asset_bytes": asset_bytes,
        "asset_ratio": round(ratio, 4),
        "threshold": THRESHOLD,
        "by_ext": [
            {"ext": k or "(无扩展名)", "files": v[0], "bytes": v[1]}
            for k, v in ranked
        ],
        "samples": [{"path": p, "bytes": s} for p, s in picks],
    }

    if as_json:
        return result

    print(f"\n=== {path} ===")
    print(f"文件数 {count} · 体积 {human(total)} · 子目录 {dirs}")

    if count:
        print("\n扩展名分布（按体积）")
        for k, v in ranked:
            share = v[1] / total if total else 0
            print(f"  {(k or '(无扩展名)'):<12} {v[0]:>7} 个  {human(v[1]):>10}  {share:>6.1%}")
        if len(by_ext) > top:
            print(f"  …… 另有 {len(by_ext) - top} 种")

        print(f"\n用户产出物 {asset_files} / {count} = {ratio:.1%}（阈值 {THRESHOLD:.0%}）")
        if asset_bytes:
            print(f"其中体积 {human(asset_bytes)}")

    label = {
        "SAFE": "可删（未发现用户产出物）",
        "BACKUP": "需备份后删除（含用户产出物或性质不明）",
        "EMPTY": "空目录",
    }[verdict]
    print(f"\n结论：{verdict} — {label}")

    if picks:
        print("\n抽样文件（先看这些再决定）")
        for p, s in picks:
            print(f"  {human(s):>10}  {p}")
    return result


def main():
    ap = argparse.ArgumentParser(description="目录体检与删除风险判定")
    ap.add_argument("paths", nargs="+", help="要检查的目录")
    ap.add_argument("--sample", type=int, default=3, help="抽样文件数（默认 3）")
    ap.add_argument("--top", type=int, default=10, help="扩展名显示条数（默认 10）")
    ap.add_argument("--json", action="store_true", help="输出 JSON，不打印报告")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    out = []
    for p in args.paths:
        r = report(p, args.sample, args.top, args.json)
        if r:
            out.append(r)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif out:
        risky = [r for r in out if r["verdict"] == "BACKUP"]
        print("\n" + "-" * 52)
        print(f"共 {len(out)} 个路径，{len(risky)} 个需备份后删除。")
        if risky:
            print("删除前请先复制到其他盘，并用 diff 确认差异为 0。")


if __name__ == "__main__":
    main()
