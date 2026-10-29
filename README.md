# c-drive-cleanup · Windows 磁盘清理

一个面向 AI 代理的清理作业规程，核心目标只有一条：**别把用户的文件删掉。**

这个技能不教你「哪些文件夹能删」。它给出一套带强制检查点的流程：先查证目录的实际内容，再决定动不动手；动手之前先建回滚点；删完等用户验收，最后才清回收站。

技能来自两次真实的 C 盘清理（合计释放约 23 GB），其中三次操作造成过损失或返工。所有规则都是这些事故的直接产物，不是凭空写的最佳实践。

---

## 它长什么样

装好之后，对代理说一句「清理C盘」。它执行一条扫描命令，得到一份带真实体积、风险分级、回滚状态的候选清单，以及一个数据已内嵌的确认页。双击打开就是自己的磁盘，不需要准备任何数据。

页面是这个样子：顶部是磁盘占用条与「将删除 N 项 / X GB」，中间按 A / B / C 三段列出候选项，每项带路径、体积、文件数、风险徽章与回滚状态。点一行即标记删除，名称与体积划红线，再点一次撤销。点「生成回执」得到两行文本：

```
删：A1 A3 B7（12 项 / 21.40 GB）
留：C4（1 项 / 1.14 GB）
```

代理按回执执行，不再逐项问你。

扫描是只读的：只调 `scandir` 与 `stat`，不写、不删、不改名。产出的两个文件是唯一写操作。

---

## 为什么需要它

名称带 `cache`、`temp`、`backup` 的目录，经常装着真实文档。典型例子：

- `WPS Cloud Files\.22134046\cachedata` —— 名字是缓存，实际是 1736 个 PDF、docx、pptx。
- `AppData\Local\Packages\*\LocalState` —— 应用数据库，删了丢笔记和账本。
- `Windows\SoftwareDistribution` —— 只能删 `Download` 子目录，整目录删会破坏更新组件。

依赖目录名判断，一定会删错。所以流程的第一步永远是把内容摊开看。

---

## 安装

### 作为 WorkBuddy 技能

```bash
git clone https://github.com/yaoooaoooy-png/c-drive-cleanup.git \
  ~/.workbuddy/skills/C盘清理
```

Windows 路径为 `C:\Users\<你>\.workbuddy\skills\C盘清理`。装好后新开会话，说「清理C盘」或「这个目录能不能删」即会加载。

技能名是 `C盘清理`，仓库名是 `c-drive-cleanup`。两者不同：仓库名受 Git 命名限制，技能名面向中文使用场景。

### 跟随上游自动更新

技能目录本身是 Git 仓库，更新只需一条命令：

```bash
git -C ~/.workbuddy/skills/C盘清理 pull --ff-only
```

要让系统定期自动拉取，把仓库放在独立目录、再用镜像同步，可以避免 `.git` 混进技能扫描范围：

```powershell
$src  = "$env:USERPROFILE\.workbuddy\skill-src\c-drive-cleanup"
$dest = "$env:USERPROFILE\.workbuddy\skills\C盘清理"

git clone https://github.com/yaoooaoooy-png/c-drive-cleanup.git $src
robocopy $src $dest /MIR /XD ".git" /NFL /NDL /NJH /NJS /NP
```

之后每次更新，`git -C $src pull --ff-only` 加一次 `robocopy` 即可。脚本 `scripts/sync.ps1` 已封装这两步，挂到 Windows 计划任务（登录时 + 每小时）就实现自动同步。

**注意：改内容要改仓库，不要直接改技能目录。** 技能目录是镜像，下次同步会被覆盖。

### 只使用脚本

三个脚本是纯 Python 标准库，无依赖，可单独使用：

```bash
python scripts/scan_candidates.py                      # 一条命令出清单与确认页
python scripts/scan_candidates.py --drive D --depth 2  # 换盘、换深度
python scripts/survey.py "C:\Users\X\AppData\Local\SomeApp" --sample 5
python scripts/recycle_list.py --limit 20
python scripts/recycle_list.py --csv D:\recycle_snapshot.csv
```

---

## 六条强制规则

| # | 规则 | 拦住什么 |
|---|---|---|
| 1 | 性质判定看内容，不看目录名。统计扩展名，再抽样看文件 | 把 1736 个办公文档当缓存删掉 |
| 2 | 删除前建回滚点。同盘改名为 `.deltmp`，跨盘 robocopy 后比对 | 误删后无法还原 |
| 3 | 回收站顺序固定：先删除 → 用户验收 → 后清空 | 删前清空，切断了恢复途径 |
| 4 | 每完成一类报一次数：盘符 X→Y，本类释放 Z | 用户无法中途叫停 |
| 5 | 不可恢复项单独标注、单独确认，不混入批量清单 | 高风险项被批量执行 |
| 6 | 禁止自证。必须给命令原文、输出、文件计数 | 跨盘测试得出假阳性结论 |

完整版含每次事故的过程与根因：`references/safety-rules.md`。

---

## 五步流程

1. **前置验证**（2 分钟）—— 在目标盘建 3 个 1 MB 测试文件，确认删除是否进回收站、空间是否立即释放、速率多少。
2. **体积测绘**（2 分钟）—— 按体积排序，同时算累计曲线。87 个文件可能占 68% 的体积。
3. **安全筛查**（5 分钟）—— 对每个候选跑 `survey.py`，用户产出物占比超 10% 就转「先备份」。
4. **按成本排序执行** —— 系统级开关（休眠、页面文件、WinSxS）优先；其次整目录 robocopy；再次改名后异步删；最后清回收站。
5. **验收** —— 报清理前可用空间、清理后可用空间、回收站当前大小。

---

## 目录内容

```
c-drive-cleanup/
├── SKILL.md                      流程、规则、判定口径、已知陷阱
├── references/
│   ├── safety-rules.md           六条规则完整版 + 三次事故复盘
│   ├── commands.md               命令配方：测绘、删除、取证、系统回收、收尾
│   └── cleanup-map.md            目录性质五分类对照表
├── scripts/
│   ├── scan_candidates.py        扫盘出清单 + 生成内嵌数据的确认页（只读）
│   ├── survey.py                 单个目录的体检与风险判定
│   ├── recycle_list.py           回收站取证（解析 $I 元数据）
│   └── sync.ps1                  从 GitHub 拉取并镜像到技能目录
└── assets/
    ├── 确认台.html               单文件确认页：导入清单、逐项标记、生成回执
    └── candidates.example.json   清单数据格式
```

### scan_candidates.py

一次扫盘，产出两份文件：清单 JSON 与确认页 HTML。页面数据已内嵌，双击即开。

```bash
python scripts/scan_candidates.py --drive C --depth 2 --min-mb 300 --max-seconds 150
```

分级口径：

| 组 | 内容 | 处理 |
|---|---|---|
| A | 系统临时、更新缓存、日志、缩略图缓存 | 低风险，系统能自愈 |
| B | 浏览器缓存、插件池、应用数据、下载目录 | 可能夹带用户数据，看 `ext` 字段 |
| C | 页面文件、休眠文件、WinSxS、程序目录 | 大件，必须人工判断 |

程序安装目录只在超过 1 GB 时列出，因为删了程序就坏，只能靠卸载回收。窗口体积按文件大小统计；稀疏与压缩文件按实际占用计算。

### survey.py 输出

```
=== C:\Users\X\AppData\Local\SomeApp ===
文件数 1736 · 体积 6.78 GB · 子目录 12

扩展名分布（按体积）
  .pdf            685  3.12 GB   39.5%
  .docx           597  2.01 GB   34.4%

用户产出物 1736 / 1736 = 100.0%（阈值 10%）

结论：BACKUP — 需备份后删除（含用户产出物或性质不明）

抽样文件（先看这些再决定）
    2.31 MB  C:\Users\X\...\合同模板.pdf
```

结论三档：`SAFE` 可删、`BACKUP` 需备份后删、`EMPTY` 空目录。判定按用户产出物占比，口径写在 `SKILL.md`。

### recycle_list.py

清空回收站之前留快照。解析 `$I` 元数据文件，输出原路径、字节数、删除时间，可导 CSV。实测读取 265 条、767 MB，时间精确到秒。

```bash
python scripts/recycle_list.py --drive C --limit 20
```

### 确认台.html

单文件、零依赖、离线可用。把清单 JSON 拖进页面，逐项点一行标记删除，再点一次撤销。支持搜索、按体积/风险/编号排序、按 A/B/C 分组筛选。点「生成回执」得到两行文本：

```
删：A1 A3 B7（12 项 / 21.40 GB）
留：C4（1 项 / 1.14 GB）
```

页面会为 `irreversible: true` 的项标红「不可恢复」，混入高风险项时弹警示条。数据格式见 `assets/candidates.example.json`。

---

## 实测数据

这些数字来自本机的两次清理，可以当作量级参考。

| 项 | 数值 |
|---|---|
| robocopy 镜像删除 | 243 文件/秒 |
| 清空回收站（直删 `$R`） | 188 秒 / 13.3 万文件 |
| `Clear-RecycleBin` 处理 28 万条目 | 卡死，不可用 |
| 被 WPS 占用的目录删除耗时 | 普通目录的 9 倍（11877 文件 / 698 秒） |
| `pagefile.sys` | 12.36 GB，峰值实际用量 2.2 GB |
| `hiberfil.sys` | 6.08 GB |
| `WinSxS` | 显示 10.19 GB，真实可回收 1–3 GB（含硬链接重复计数） |

---

## 授权

MIT。见 [LICENSE](LICENSE)。

使用前请读完 `references/safety-rules.md`。这套流程能降低误删概率，但不能替代备份。对没有备份的数据，先备份再谈清理。
