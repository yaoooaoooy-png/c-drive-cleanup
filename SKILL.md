---
name: C盘清理
description: "Windows 磁盘空间清理的安全作业流程，覆盖扫描、分类、风险分级、执行删除与验收。用于「清理C盘」「C盘满了」「磁盘空间不足」「扫描垃圾文件」「释放空间」「这个目录能不能删」这类请求。核心是防止误删：先查证再动手，不可逆动作前必须留退路。含五步流程、六条强制规则、目录性质判定方法、robocopy 快速删除与回收站取证命令、系统级空间回收（休眠文件、页面文件、WinSxS），以及可复用的确认台页面（拖入 JSON 清单、逐项标记删除、生成回执）。当任务涉及磁盘清理、判断目录是否可安全删除、清理缓存或临时文件时使用。"
agent_created: true
---

# C 盘清理

**先查证，再删除。删除前必须有退路。**

本 skill 来自两次真实的 C 盘清理。其中三次操作造成过损失或返工。六条规则不是建议，是这些事故的直接产物。

---

## 快速路径：用户说「清理C盘」时先做这一步

### 第 0 步 · 同步到最新版

如果技能装在 WorkBuddy 技能目录下，并且存在本地仓库副本，先拉一次更新：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync.ps1
```

这条命令从 GitHub 拉最新版 main，再镜像到 `%USERPROFILE%\.workbuddy\skills\C盘清理`。

- 本地仓库副本默认在 `%USERPROFILE%\.workbuddy\skill-src\c-drive-cleanup`。
- 首次安装时没有副本，先在克隆目录里建一次：`git clone https://github.com/yaoooaoooy-png/c-drive-cleanup.git %USERPROFILE%\.workbuddy\skill-src\c-drive-cleanup`。
- 拉取失败不影响使用：脚本会报错并保留现有版本，继续走第 1 步。
- 更新只在下次会话生效。当前会话已加载的流程不变。

### 第 1 步 · 扫描

不要先手工翻目录。跑一条命令，直接得到候选清单和一个可点的确认页：

```bash
python scripts/scan_candidates.py
```

- 默认扫系统盘，深度 2，体积门槛 300 MB，总限时 150 秒。
- 只读：只调 `scandir` / `stat`，不写不删不改名。
- 输出两个文件到当前目录：`C盘清理清单-<时间>.json` 与 `C盘清理-确认台-<时间>.html`。
- HTML 里的清单是内嵌的，**双击即开，不需要拖 JSON**。

拿到 HTML 之后，把路径给用户，让他逐项标记删除、点「生成回执」，把两行回执贴回来。你按回执执行。

常用参数：

| 参数 | 作用 |
|---|---|
| `--drive D` | 换盘符；非系统盘只做发现，不套用系统路径规则 |
| `--depth 2` | 往下找几层。1 更快但会漏掉 `AppData\Local\X\Y` 这类 |
| `--min-mb 300` | 发现项的体积门槛。空间很小的机器可降到 100 |
| `--max-seconds 150` | 时间上限。超时会输出部分结果，并在标题里标注 |
| `--json-only` | 只出 JSON，不生成页面 |

结果口径：

- A 组是系统与临时目录，删了系统能自愈。
- B 组是应用缓存，可能夹带用户数据，逐项看 `ext` 字段。
- C 组是大件，包含页面文件、休眠文件、WinSxS 与程序目录，必须人工判断。
- 程序安装目录只在超过 1 GB 时出现，删了程序就坏，只能卸载回收。

超过 150 秒会截断。机器大、盘满，就设 `--max-seconds 400` 分两次跑，先看 A/B 组。

---

## 六条强制规则

| # | 规则 | 拦住什么 |
|---|---|---|
| 1 | **性质判定看内容，不看目录名。** 统计扩展名分布，再抽 3 个文件看实际内容。目录里出现 .docx/.pdf/.xlsx/.jpg 等用户产出物且占比超过 10%，强制降级为「先备份再删」。 | 把 `WPS Cloud Files\...\cachedata` 当缓存删了，实际是 1736 个办公文档 |
| 2 | **删除前建立回滚点。** 同盘先改名为 `.deltmp`（瞬时、可逆）；性质不明的大件用 `robocopy` 复制到其他盘，差异为 0 才删。 | 误删后无法还原 |
| 3 | **回收站清理顺序固定：先删除 → 用户验收 → 后清空。** 禁止在删除前或删除中清空。 | 首轮先清空回收站，切断了误删文件的恢复途径 |
| 4 | **每完成一类报一次数。** 立刻报「C 盘 X→Y，本类释放 Z」，不等全部做完再总结。 | 用户无法在中途叫停 |
| 5 | **不可恢复项单独标注、单独二次确认。** 不混进批量清单。 | 高风险项混入批量操作 |
| 6 | **禁止自证。** 不许只说「我已验证」。必须给出命令原文、输出、文件计数，让用户可以复核。 | 测试文件建在 D 盘却去查 C 盘回收站，得出「绕过回收站生效」的错误结论 |

---

## 五步流程

### 第一步 · 前置验证（约 2 分钟）

在目标盘建 3 个 1 MB 测试文件，确认三个事实。**不要凭推测。**

1. 删除后是否进入回收站。
2. 空间是否立即释放。
3. 删除速率是多少。

```powershell
$t = "C:\_probe"; New-Item -ItemType Directory -Force $t | Out-Null
1..3 | ForEach-Object { fsutil file createnew "$t\p$_.bin" 1048576 }
# 记录回收站计数 → 删除 → 再看计数与剩余空间
```

### 第二步 · 体积测绘（约 2 分钟）

按体积排序，不按目录名排序。**同时算累计曲线**：87 个文件可能占 68% 的体积，只盯目录数会看错重点。

用 `scripts/scan_candidates.py` 一条命令跑完测绘、发现与分级，直接产出确认页。单个目录要看细节时再用 `scripts/survey.py`。

### 第三步 · 安全筛查（约 5 分钟）

对每个候选目录执行规则 1。`scan_candidates.py` 已经跑了扩展名统计与用户产出物判定；对性质不明或体量大的项，再用 `survey.py` 单独复核一遍，并抽 3 个文件看内容。

### 第四步 · 按执行成本排序执行

成本分四档，先做便宜且回收大的：

| 档 | 类型 | 做法 |
|---|---|---|
| 1 | 系统级开关 | `powercfg /h off`、页面文件改固定大小、`DISM /StartComponentCleanup /ResetBase`。一条命令回收数 GB，零数据风险。**优先做这一档。** |
| 2 | 整目录删除 | `robocopy` 镜像空目录，`/MT:64` 多线程 |
| 3 | 大量小文件 | 先改名为 `.deltmp`（O(1) 瞬时），再后台删除 |
| 4 | 回收站 | 直接删 `$R` 文件，不用 `Clear-RecycleBin` |

### 第五步 · 验收

报三个数：清理前可用空间、清理后可用空间、回收站当前大小。附每类实际删除计数与残留（被占用的文件）。

---

## 目录性质判定

**唯一可靠的方法是看扩展名分布加抽样。** 目录名会骗人：`cachedata`、`temp`、`backup` 都可能装着真实文档。

```powershell
Get-ChildItem $p -Recurse -File -EA 0 |
  Group-Object Extension | Sort Count -Desc | Select Count, Name
```

用脚本得到结构化判定：

```bash
python scripts/survey.py "C:\Users\X\AppData\Local\SomeApp" --sample 5
```

输出：文件数、总体积、扩展名 Top 10、用户产出物占比、5 个抽样文件的完整路径与大小、风险结论。

判定口径：

- 用户产出物占比 **> 10%** → 需备份后删除
- 出现 `.doc/.docx/.xls/.xlsx/.ppt/.pptx/.pdf/.jpg/.psd/.ai/.dwg` → 一律先备份
- 只有 `.tmp` / `.log` / `.cache` / `.db-wal` 之类，且目录内无深层子目录 → 可删

---

## 快速删除

```powershell
# 最快：镜像空目录（实测 243 文件/秒）
robocopy "D:\_empty" "C:\target" /MIR /MT:64 /R:0 /W:0 /NFL /NDL /NJH /NJS /NP
```

**先停占用进程再删。** WPS、微信、浏览器会锁文件，也会让删除慢 9 倍（实测 11877 个文件跑了 698 秒）。

```powershell
Stop-Process -Name wps,wpscloudsvr,WeChatAppEx -Force -EA 0
```

## 回收站

```powershell
# 直接删 $R 数据文件，比 Clear-RecycleBin 快一个数量级
robocopy "D:\_empty" "C:\`$Recycle.Bin\<SID>" /MIR /MT:64 /R:0 /W:0 /NFL /NDL /NJH /NJS /NP
```

**禁止用 `Clear-RecycleBin` 处理十万级条目**，实测 28 万条目时进度条不动、进程卡死。

清空之前先取证。`scripts/recycle_list.py` 解析 `$I` 元数据文件，列出每一项的原路径、大小、删除时间：

```bash
python scripts/recycle_list.py --csv D:\recycle_snapshot.csv
```

## 系统级空间回收

这三项通常回收 15–25 GB，零数据风险。**每次清理都应先看这一档。**

| 项 | 典型占用 | 命令 | 代价 |
|---|---|---|---|
| 休眠文件 | 6 GB（≈内存 75%） | `powercfg /h off` | 关闭休眠与快速启动 |
| 页面文件 | 12 GB（峰值用量仅 2 GB） | 系统属性 → 高级 → 性能 → 虚拟内存 → 固定 4 GB 或移至其他盘 | 需重启；内存 8 GB 以下不建议压到 4 GB |
| WinSxS 组件库 | 10 GB（含硬链接重复计数） | `DISM /Online /Cleanup-Image /StartComponentCleanup /ResetBase` | 无法卸载已安装的更新 |

WinSxS 的目录大小含硬链接，真实占用远小于显示值。用 `DISM /Online /Cleanup-Image /AnalyzeComponentStore` 看真实可回收量。

---

## 确认台页面

`assets/确认台.html` 是单文件零依赖的确认页。两种用法：

**自动（推荐）**：`scan_candidates.py` 已经把数据注入页面，用户双击打开就是自己的清单，直接标记即可。

**手工**：把候选清单写成 JSON（格式见 `assets/candidates.example.json`），打开 `assets/确认台.html`，把 JSON 拖进页面。

标记方式：逐项点一行标记删除，再点一次撤销。支持搜索、按体积/风险/编号排序、按 A/B/C 类筛选。

回执格式固定，编号由页面生成，不需要人工对齐：

```
删：A1 A3 B7（12 项 / 21.40 GB）
留：C4（1 项 / 1.14 GB）
风险：C4（不可恢复）
```

页面把「不可恢复」「已备份」显示成徽章。混入高风险项时弹红色警示条。

数据字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 编号，如 `A1` |
| `name` | 是 | 名称 |
| `gb` | 是 | 体积（GB） |
| `group` | 否 | 分组，A/B/C |
| `risk` | 否 | 1 低 / 2 中 / 3 高 |
| `path` | 否 | 完整路径 |
| `backup` | 否 | `none` / `rename` / `copy`，表示回滚点状态 |
| `irreversible` | 否 | `true` 表示删了无法还原 |

---

## 已知陷阱

| 现象 | 真实原因 | 对策 |
|---|---|---|
| 删除后空间没变 | 文件进了回收站，仍占原盘空间 | 先验回收站，再清空 |
| 测试「绕过回收站」成功了 | 测试文件建在别的盘，却查目标盘的回收站 | 测试文件必须与目标同盘 |
| 删除慢得异常 | 进程占用（WPS、微信） | 先停进程 |
| `Clear-RecycleBin` 卡死 | 条目过多 | 直接删 `$R` |
| 目录显示 10 GB，清完只回收 1 GB | 硬链接重复计数 | 用 DISM 看真实值 |
| 用「内存优化」软件腾空间 | 它清的是物理内存，只会降低性能 | 不要做。清理磁盘与清理内存是两件事 |

---

## 参考文件

- `references/safety-rules.md` —— 六条规则完整版，含三次事故的过程与根因
- `references/commands.md` —— 命令配方全集（扫描、删除、取证、系统回收、服务恢复）
- `references/cleanup-map.md` —— 常见目录性质对照表，可信删除对象与不确定对象
- `scripts/scan_candidates.py` —— 一条命令出清单与确认页，只读
- `scripts/survey.py` —— 单个目录的体检与风险判定
- `scripts/recycle_list.py` —— 回收站取证
- `scripts/sync.ps1` —— 从 GitHub 拉最新版并镜像到技能目录
- `assets/确认台.html` —— 确认页模板；`scan_candidates.py` 往里注入数据
- `assets/candidates.example.json` —— 手工编写清单时的数据格式
