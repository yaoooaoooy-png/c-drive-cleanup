#!/usr/bin/env python3
"""扫描磁盘，生成确认台可直接打开的清单。

用途：用户说「清理C盘」之后，一条命令得到一份带真实体积、风险分级、
回滚状态的候选清单，以及一个数据已内嵌、双击即开的确认页面。

用法：
    python scan_candidates.py                          # 扫系统盘，输出 JSON + HTML
    python scan_candidates.py --drive D                # 扫指定盘
    python scan_candidates.py --depth 2 --min-mb 300   # 调整发现深度与体积门槛
    python scan_candidates.py --json-only              # 只出 JSON
    python scan_candidates.py --max-seconds 90         # 限时，超时给部分结果

安全边界：
    本脚本只读：只调用 scandir / stat / disk_usage，不做任何写、删、改名操作。
    输出只写两个文件（清单 JSON 与确认页 HTML），路径由 --out 决定。
"""

import argparse
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

GB = 1024.0 ** 3
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_SPARSE_FILE = 0x200
FILE_ATTRIBUTE_COMPRESSED = 0x800

# 稀疏/压缩文件按实际占用计，否则体积会虚高
_GET_ALLOC = None
if os.name == "nt":
    try:
        import ctypes
        from ctypes import wintypes
        _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _k32.GetCompressedFileSizeW.argtypes = [wintypes.LPCWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
        _k32.GetCompressedFileSizeW.restype = wintypes.DWORD

        def _GET_ALLOC(path, fallback):
            hi = wintypes.DWORD(0)
            lo = _k32.GetCompressedFileSizeW(path, ctypes.byref(hi))
            if lo == 0xFFFFFFFF:
                return fallback
            v = (hi.value << 32) | lo
            return v if v != 0xFFFFFFFFFFFFFFFF else fallback
    except Exception:
        _GET_ALLOC = None

# 用户产出物：出现即视为真实数据
USER_ASSET_EXTS = {
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf",
    ".txt", ".md", ".rtf", ".csv", ".wps", ".et", ".dps",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic",
    ".psd", ".ai", ".eps", ".sketch", ".fig", ".dwg", ".dxf", ".indd",
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".mp3", ".wav", ".flac", ".m4a",
    ".zip", ".rar", ".7z", ".db", ".sqlite", ".accdb", ".mdb",
}

# 不进入发现的目录：系统关键路径或另有专门处理
SKIP_NAMES = {
    "$recycle.bin", "system volume information", "winsxs", "windows",
    "recovery", "boot", "config.msi", "$windows.~bt", "$windows.~ws",
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log.tmp",
}

# ---------------------------------------------------------------- 规则表
# group: A 系统/临时档（低风险）  B 应用缓存档（中风险）  C 大件档（需人工判断）
# backup: none 无回滚点 / rename 可改名回滚 / copy 已复制备份
# paths 支持 %ENV% 与 glob
RULES = [
    # ---------- A 档：低风险，删了系统能自愈 ----------
    dict(name="Windows 更新缓存", group="A", risk=1, backup="none",
         paths=[r"C:\Windows\SoftwareDistribution\Download"],
         ext="更新包 .cab/.esd 为主", note="更新服务会重建此目录"),
    dict(name="系统临时文件", group="A", risk=1, backup="none",
         paths=[r"C:\Windows\Temp"], ext=".tmp/.log 为主"),
    dict(name="用户临时文件", group="A", risk=1, backup="none",
         paths=[r"%LOCALAPPDATA%\Temp"], ext=".tmp/.log 为主"),
    dict(name="预读缓存", group="A", risk=1, backup="none",
         paths=[r"C:\Windows\Prefetch"], ext=".pf 预读文件"),
    dict(name="系统日志", group="A", risk=1, backup="none",
         paths=[r"C:\Windows\Logs"], ext=".etl/.log 为主"),
    dict(name="崩溃转储", group="A", risk=2, backup="none",
         paths=[r"%LOCALAPPDATA%\CrashDumps"], ext=".dmp 转储文件",
         note="需要排查崩溃时先留着"),
    dict(name="缩略图与图标缓存", group="A", risk=1, backup="none",
         paths=[r"%LOCALAPPDATA%\Microsoft\Windows\Explorer"],
         ext="thumbcache/iconcache 数据库"),
    dict(name="IE/系统网页缓存", group="A", risk=1, backup="none",
         paths=[r"%LOCALAPPDATA%\Microsoft\Windows\INetCache"], ext="缓存对象"),
    dict(name="旧系统备份", group="A", risk=2, backup="none",
         paths=[r"C:\Windows.old"], ext="上一版系统文件",
         note="删掉就不能回滚到旧版系统"),
    dict(name="Windows 升级残留", group="A", risk=1, backup="none",
         paths=[r"C:\$WINDOWS.~BT", r"C:\$WINDOWS.~WS"], ext="升级暂存目录"),

    # ---------- B 档：中风险，应用缓存但可能带用户数据 ----------
    dict(name="Edge 浏览器缓存", group="B", risk=1, backup="none",
         paths=[r"%LOCALAPPDATA%\Microsoft\Edge\User Data\*\Cache",
                r"%LOCALAPPDATA%\Microsoft\Edge\User Data\*\Code Cache"],
         ext="缓存块文件"),
    dict(name="Chrome 浏览器缓存", group="B", risk=1, backup="none",
         paths=[r"%LOCALAPPDATA%\Google\Chrome\User Data\*\Cache",
                r"%LOCALAPPDATA%\Google\Chrome\User Data\*\Code Cache"],
         ext="缓存块文件"),
    dict(name="WPS 插件池", group="B", risk=2, backup="none",
         paths=[r"%APPDATA%\kingsoft\wps\addons\pool"],
         ext="js/json/zip 插件包"),
    dict(name="WPS 云文档缓存目录", group="B", risk=3, backup="copy",
         paths=[r"%USERPROFILE%\Documents\WPS Cloud Files\*\cachedata"],
         ext="目录名是缓存，实际常含 pdf/docx/pptx —— 必须先备份",
         irreversible=True,
         note="历史事故：此处 1736 个真实办公文档被当缓存删除，损失 85 个"),
    dict(name="微信聊天与文件", group="B", risk=3, backup="none",
         paths=[r"%USERPROFILE%\Documents\WeChat Files",
                r"%USERPROFILE%\Documents\xwechat_files"],
         ext="聊天记录、接收的文件", irreversible=True,
         note="删掉聊天记录无法恢复，只能迁移不能清理"),
    dict(name="QQ 聊天与文件", group="B", risk=3, backup="none",
         paths=[r"%USERPROFILE%\Documents\Tencent Files"],
         ext="聊天记录、接收的文件", irreversible=True),
    dict(name="下载文件夹", group="B", risk=2, backup="none",
         paths=[r"%USERPROFILE%\Downloads"], ext="用户主动下载的内容",
         note="用户产出物集中地，逐项确认再删"),
    dict(name="npm 缓存", group="B", risk=1, backup="none",
         paths=[r"%LOCALAPPDATA%\npm-cache", r"%APPDATA%\npm-cache"],
         ext="包缓存"),
    dict(name="pip 缓存", group="B", risk=1, backup="none",
         paths=[r"%LOCALAPPDATA%\pip\Cache"], ext="wheel/sdist 缓存"),
    dict(name="应用数据（Packages）", group="B", risk=3, backup="none",
         paths=[r"%LOCALAPPDATA%\Packages"], ext="UWP 应用数据库与设置",
         irreversible=True,
         note="逐个应用判断，删 LocalState 会丢笔记与账本"),

    # ---------- C 档：大件，必须人工判断 ----------
    dict(name="页面文件 pagefile.sys", group="C", risk=1, backup="none",
         paths=[r"C:\pagefile.sys"], single_file=True,
         ext="虚拟内存文件", note="不要直接删；改为固定 4 GB 或移到其他盘"),
    dict(name="休眠文件 hiberfil.sys", group="C", risk=1, backup="none",
         paths=[r"C:\hiberfil.sys"], single_file=True,
         ext="休眠镜像文件", note="用 powercfg /h off 关闭休眠，即刻回收"),
    dict(name="WinSxS 组件库", group="C", risk=2, backup="none",
         paths=[r"C:\Windows\WinSxS"], ext="组件与更新备份，含硬链接重复计数",
         note="用 DISM /AnalyzeComponentStore 看真实可回收量；不要直接删目录"),
    dict(name="Windows Installer 缓存", group="C", risk=3, backup="none",
         paths=[r"C:\Windows\Installer"], ext="msi/msp 安装缓存",
         irreversible=True, note="删掉会导致程序无法卸载或修复"),
    dict(name="WSL 子系统", group="C", risk=3, backup="none",
         paths=[r"%LOCALAPPDATA%\Packages\*WSL*",
                r"%LOCALAPPDATA%\Packages\CanonicalGroupLimited*",
                r"%LOCALAPPDATA%\wsl"],
         ext="虚拟磁盘 ext4.vhdx", irreversible=True,
         note="含 Linux 内所有文件，删前先在 WSL 里导出"),
    dict(name="Docker 镜像", group="C", risk=3, backup="none",
         paths=[r"%LOCALAPPDATA%\Docker", r"%APPDATA%\Docker"],
         ext="镜像层与容器数据", irreversible=True),
    dict(name="虚拟机镜像", group="C", risk=3, backup="none",
         paths=[r"%USERPROFILE%\Documents\Virtual Machines",
                r"%USERPROFILE%\VirtualBox VMs"],
         ext="vhd/vhdx/vdi 磁盘", irreversible=True),
]


def now():
    return time.time()


def is_reparse(entry):
    try:
        st = entry.stat(follow_symlinks=False)
        return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


def dir_size(path, deadline, want_ext=False, ext_limit=4000):
    """递归求体积。返回 (bytes, files, denied, ext_counter 或 None)。"""
    total = 0
    files = 0
    denied = 0
    exts = {} if want_ext else None
    stack = [path]
    while stack:
        if now() > deadline:
            break
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if not is_reparse(e):
                                stack.append(e.path)
                        else:
                            st = e.stat(follow_symlinks=False)
                            sz = st.st_size
                            attr = getattr(st, "st_file_attributes", 0)
                            if _GET_ALLOC and (attr & (FILE_ATTRIBUTE_SPARSE_FILE |
                                                       FILE_ATTRIBUTE_COMPRESSED)):
                                sz = _GET_ALLOC(e.path, sz)
                            total += sz
                            files += 1
                            if exts is not None and len(exts) < ext_limit:
                                dot = e.name.rfind(".")
                                k = e.name[dot:].lower() if dot > 0 else "(无扩展名)"
                                exts[k] = exts.get(k, 0) + 1
                    except OSError:
                        denied += 1
        except PermissionError:
            denied += 1
        except OSError:
            denied += 1
    return total, files, denied, exts


def expand(pattern):
    p = os.path.expandvars(pattern)
    if "*" in p or "?" in p:
        import glob as g
        return [x for x in g.glob(p) if os.path.exists(x)]
    return [p] if os.path.exists(p) else []


def asset_ratio(exts):
    if not exts:
        return 0.0, 0
    total = sum(exts.values())
    hit = sum(v for k, v in exts.items() if k in USER_ASSET_EXTS)
    return (hit / total if total else 0.0), hit


def classify_by_name(lowered, exts):
    """对规则表外的目录做启发式判定。"""
    if asset_ratio(exts)[0] > 0.10:
        return 3, True, "含用户产出物"
    for k in ("cache", "temp", "tmp", "log", "日志", "缓存", "临时"):
        if k in lowered:
            return 1, False, "名称与扩展名都指向缓存"
    for k in ("docker", "wsl", "vm", "virtual", "image", "backup", "备份"):
        return 3, True, "疑似镜像或备份，删了无法重建"
    return 2, False, "性质不明"


def human_ext(exts, top=4):
    if not exts:
        return ""
    items = sorted(exts.items(), key=lambda kv: -kv[1])[:top]
    return " / ".join("%s %d" % (k, v) for k, v in items)


def scan_rule(rule, deadline, drive):
    """测量一条规则的总体积。只统计位于目标盘上的路径。返回 dict 或 None。"""
    total = 0
    files = 0
    denied = 0
    exts = {}
    hit_any = False
    first_path = ""
    drive = drive.rstrip("\\").lower()
    for pat in rule["paths"]:
        for p in expand(pat):
            if os.path.splitdrive(p)[0].lower() != drive:
                continue
            hit_any = True
            if not first_path:
                first_path = p
            if rule.get("single_file"):
                try:
                    st = os.stat(p, follow_symlinks=False)
                    total += st.st_size
                    files += 1
                except OSError:
                    denied += 1
                continue
            b, f, d, ex = dir_size(p, deadline, want_ext=True)
            total += b
            files += f
            denied += d
            for k, v in (ex or {}).items():
                exts[k] = exts.get(k, 0) + v
    if not hit_any:
        return None
    if total <= 0 and denied:
        return dict(rule=rule, gb=0.0, files=0, denied=denied, exts=exts, empty=True,
                    first_path=first_path)
    return dict(rule=rule, gb=total / GB, files=files, denied=denied, exts=exts,
                empty=False, first_path=first_path)


def collect_nodes(roots, depth, deadline, covered_paths, min_bytes):
    """收集候选节点。

    两类节点：
      full   —— 深度正好为 depth 的目录，测量整棵子树
      direct —— 浅层目录里直属文件就超过门槛的，只算直属文件（避免漏掉平铺大目录）
    """
    cand = []
    roots = [r for r in roots if r and os.path.isdir(r)]
    for root in roots:
        others = [r for r in roots if os.path.normcase(r) != os.path.normcase(root)]
        if any(is_covered(root, o) for o in others):
            continue
        level = [(root, 0)]
        while level:
            if now() > deadline:
                break
            nxt = []
            for path, d in level:
                if d == depth:
                    if not any(is_covered(path, c) for c in covered_paths + others):
                        cand.append((path, "full"))
                    continue
                try:
                    with os.scandir(path) as it:
                        entries = list(it)
                except OSError:
                    continue
                direct = 0
                direct_files = 0
                exts = {}
                for e in entries:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if is_reparse(e) or e.name.lower() in SKIP_NAMES:
                                continue
                            nxt.append((e.path, d + 1))
                        else:
                            sz = e.stat(follow_symlinks=False).st_size
                            direct += sz
                            direct_files += 1
                            if len(exts) < 400:
                                dot = e.name.rfind(".")
                                k = e.name[dot:].lower() if dot > 0 else "(无扩展名)"
                                exts[k] = exts.get(k, 0) + 1
                    except OSError:
                        continue
                if direct >= min_bytes and not any(is_covered(path, c) for c in covered_paths + others):
                    cand.append((path, "direct", direct, direct_files, exts))
            level = nxt
    return cand


def measure(path):
    b, f, denied, exts = dir_size(path, now() + 3600, want_ext=True, ext_limit=800)
    return dict(path=path, bytes=b, files=f, denied=denied, exts=exts)


def discover(roots, depth, min_bytes, deadline, covered_paths):
    """收集 + 测量，返回超过体积门槛的目录。"""
    cand = collect_nodes(roots, depth, deadline, covered_paths, min_bytes)
    full = [p for p, kind, *_ in cand if kind == "full"]
    direct = [(p, b, f, e) for p, kind, b, f, e in
              [c for c in cand if c[1] == "direct"]]
    found = [dict(path=p, bytes=b, files=f, denied=0, exts=e) for p, b, f, e in direct]

    workers = min(8, max(1, len(full)))
    if full:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for r in pool.map(measure, full):
                if now() > deadline:
                    break
                if r["bytes"] >= min_bytes:
                    found.append(r)
    return found


def is_covered(path, other):
    p = path.rstrip("\\").lower()
    o = other.rstrip("\\").lower()
    return p == o or p.startswith(o + "\\") or o.startswith(p + "\\")


def build(scan, disk, drive="C:"):
    items = []
    covered = []
    for r in scan["rules"]:
        rule = r["rule"]
        covered.extend([p for pat in rule["paths"] for p in expand(pat)])
        if r["empty"]:
            continue
        gb = round(r["gb"], 2)
        if gb < 0.05:
            continue
        note = rule.get("note", "")
        if r["denied"]:
            note = (note + "；" if note else "") + "%d 个文件无法读取，需管理员权限" % r["denied"]
        ext = rule.get("ext", "")
        if r["exts"] and rule["group"] != "A":
            ext = human_ext(r["exts"]) + (" · " + ext if ext else "")
        items.append(dict(name=rule["name"], group=rule["group"], risk=rule["risk"],
                          backup=rule["backup"], irreversible=rule.get("irreversible", False),
                          gb=gb, files=r["files"], path=r.get("first_path") or rule["paths"][0],
                          ext=ext, note=note))

    for d in scan["discovered"]:
        gb = round(d["bytes"] / GB, 2)
        if gb < 0.05:
            continue
        low = d["path"].lower()
        # 程序安装目录不是清理对象：只在体积明显时才列出来，供用户判断是否卸载
        is_prog = ("\\program files" in low or "\\programdata\\" in low
                   or "\\windowsapps\\" in low or "\\common files\\" in low)
        if is_prog and gb < 1.0:
            continue
        risk, irr, why = classify_by_name(low, d["exts"])
        base = os.path.basename(d["path"].rstrip("\\"))
        parent = os.path.basename(os.path.dirname(d["path"].rstrip("\\")))
        generic = ("users", "program files", "program files (x86)", "programdata",
                   "appdata", "local", "roaming", "documents")
        label = base if parent.lower() in generic else "%s / %s" % (parent, base)
        if len(label) > 34:
            label = label[:33] + "…"
        items.append(dict(name=label,
                          group=("A" if risk == 1 else ("B" if risk == 2 else "C")),
                          risk=risk, backup="none", irreversible=irr,
                          gb=gb, files=d["files"], path=d["path"],
                          ext=human_ext(d["exts"]) + (" · " + why if why else ""),
                          note=why if irr else ""))

    # 去重：同一路径只留一条
    seen = set()
    uniq = []
    for it in items:
        k = it["path"].lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)

    # 分组排序、编号
    out = []
    for g in ("A", "B", "C"):
        group = sorted([i for i in uniq if i["group"] == g], key=lambda x: -x["gb"])
        if g == "C":
            group = group[:12]
        for n, it in enumerate(group, 1):
            it["id"] = "%s%d" % (g, n)
            out.append(it)

    total = sum(i["gb"] for i in out)
    truncated = scan.get("truncated")
    title = "%s 盘清理清单 · 自动扫描 · %d 项 / %.2f GB" % (drive[0], len(out), total)
    if truncated:
        title += " · 扫描超时，结果不完整"
    used = (disk or {}).get("used") or 0
    if used and total > used * 1.08:
        # 合计超过磁盘已用量：说明有压缩/稀疏分配，实际释放量会小于标注
        title += " · 体积为文件大小口径，实际释放略少"
    return {
        "title": title,
        "generatedAt": datetime.now().strftime("%Y-%m-%d"),
        "disk": disk,
        "items": out,
    }


def emit_html(data, out_dir, drive="C:"):
    tpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "确认台.html")
    tpl = os.path.normpath(tpl)
    if not os.path.isfile(tpl):
        return None
    with open(tpl, encoding="utf-8") as f:
        html = f.read()
    marker = "var EMBEDDED = null; /* EMIT_CANDIDATES_HERE */"
    if marker not in html:
        return None
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace(marker, "var EMBEDDED = %s;" % payload)
    name = "%s盘清理-确认台-%s.html" % (drive[0], datetime.now().strftime("%Y%m%d-%H%M"))
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    return path


def main():
    ap = argparse.ArgumentParser(description="扫描磁盘，生成确认台可打开的清单")
    ap.add_argument("--drive", default=os.environ.get("SystemDrive", "C:"),
                    help="盘符，默认系统盘")
    ap.add_argument("--depth", type=int, default=2, help="发现大目录的深度，默认 2")
    ap.add_argument("--min-mb", type=int, default=300, help="发现项的体积门槛（MB），默认 300")
    ap.add_argument("--max-seconds", type=int, default=150, help="总时间上限，默认 150 秒")
    ap.add_argument("--max-items", type=int, default=45, help="清单最大项数")
    ap.add_argument("--out", default=os.getcwd(), help="输出目录，默认当前目录")
    ap.add_argument("--json-only", action="store_true", help="只输出 JSON")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    drive = args.drive.rstrip("\\")
    if len(drive) == 1:
        drive += ":"
    root = drive + "\\"
    if not os.path.isdir(root):
        print("盘符不存在：%s" % root, file=sys.stderr)
        return 2

    deadline = now() + args.max_seconds
    t0 = now()
    # 时间预算：规则表占 55%，发现阶段拿剩下的
    rule_deadline = t0 + args.max_seconds * 0.55
    deadline = t0 + args.max_seconds
    if not args.quiet:
        print("扫描 %s  深度 %d  门槛 %d MB  限时 %d 秒" %
              (root, args.depth, args.min_mb, args.max_seconds))

    rules = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(scan_rule, rule, rule_deadline, drive) for rule in RULES]
        for rule, fut in zip(RULES, futures):
            try:
                r = fut.result()
            except Exception:
                continue
            if r:
                rules.append(r)
                if not args.quiet:
                    print("  %-24s %8.2f GB  %d 个文件" % (rule["name"], r["gb"], r["files"]))
    if not args.quiet and now() > rule_deadline:
        print("  （规则表限时用完，未测到的规则不在清单里）")

    covered = [p for rule in RULES for pat in rule["paths"] for p in expand(pat)]
    sysdrive = os.environ.get("SystemDrive", "C:")
    if os.path.normcase(drive) == os.path.normcase(sysdrive):
        roots = [os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA"),
                 os.environ.get("USERPROFILE"), r"C:\ProgramData",
                 r"C:\Program Files", r"C:\Program Files (x86)"]
    else:
        roots = [root]
    if not args.quiet:
        print("发现大目录…")
    discovered = discover(roots, args.depth, args.min_mb * 1024 * 1024, deadline, covered)

    truncated = now() > deadline
    usage = shutil.disk_usage(root)
    disk = {"total": round(usage.total / GB, 2), "used": round(usage.used / GB, 2),
            "free": round(usage.free / GB, 2)}

    data = build({"rules": rules, "discovered": discovered, "truncated": truncated}, disk, drive)

    # 截断：保留体积最大的若干项，其余丢弃，然后按分组重新编号
    if len(data["items"]) > args.max_items:
        keep = sorted(data["items"], key=lambda x: -x["gb"])[:args.max_items]
        ids = {i["id"] for i in keep}
        data["items"] = [i for i in data["items"] if i["id"] in ids]
        counter = {"A": 0, "B": 0, "C": 0}
        for it in data["items"]:
            g = it["group"]
            counter[g] = counter.get(g, 0) + 1
            it["id"] = "%s%d" % (g, counter[g])

    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    jpath = os.path.join(args.out, "%s盘清理清单-%s.json" % (drive[0], stamp))
    with open(jpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    hpath = None
    if not args.json_only:
        hpath = emit_html(data, args.out, drive)

    if not args.quiet:
        total = sum(i["gb"] for i in data["items"])
        print("\n清单 %d 项 / %.2f GB，用时 %.0f 秒%s" %
              (len(data["items"]), total, now() - t0, "（超时截断）" if truncated else ""))
        print("磁盘 %s 已用 %.2f / %.2f GB，剩余 %.2f GB" %
              (drive, disk["used"], disk["total"], disk["free"]))
        print("JSON: %s" % jpath)
        if hpath:
            print("确认页: %s" % hpath)
        else:
            print("确认页未生成（模板缺少内嵌标记，请更新 assets/确认台.html）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
