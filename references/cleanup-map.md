# 目录性质对照表

按「能不能删」分类。**表只是初判，最终以 `scripts/survey.py` 的实际内容为准。** 应用版本更新会改变目录用途，路径对不上时以内容为准。

---

## A · 可直接删，系统或应用会重建

| 路径 | 说明 | 代价 |
|---|---|---|
| `C:\Windows\Temp` | 系统临时文件 | 无 |
| `%LOCALAPPDATA%\Temp` | 用户临时文件 | 无 |
| `C:\Windows\Logs` | 系统日志 | 无（排障时缺历史日志） |
| `C:\Windows\Minidump` | 蓝屏转储 | 无（提交故障分析前不要删） |
| `C:\Windows\LiveKernelReports` | 内核报告 | 无 |
| `C:\ProgramData\Microsoft\Windows\WER` | 错误报告队列 | 无 |
| `%LOCALAPPDATA%\CrashDumps` | 应用崩溃转储 | 无 |
| `C:\Windows\SoftwareDistribution\Download` | 更新包缓存 | 无（删除前停 wuauserv） |
| `C:\Windows\Prefetch` | 预读文件 | 首次启动略慢 |
| 浏览器 `Cache` / `Code Cache` / `GPUCache` | 网页缓存 | 首次加载变慢 |
| `%LOCALAPPDATA%\npm-cache`、`pnpm\store` | 包管理器缓存 | 需重新下载 |
| `%LOCALAPPDATA%\pip\Cache` | pip 缓存 | 需重新下载 |
| `~/.gradle/caches`、`~/.m2/repository` | 构建缓存 | 需重新下载 |
| `%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db` | 缩略图缓存 | 重新生成 |

---

## B · 需确认后删，可能含用户数据

| 路径 | 风险点 | 确认方式 |
|---|---|---|
| `Documents\WPS Cloud Files\*` | **名字带 cachedata 也可能是真实文档**。实测 1736 个 PDF/docx/pptx | 跑 `survey.py`，出现文档扩展名即先备份 |
| `Documents\WeChat Files`、`WeChat Files` | 聊天记录、接收的文件、图片 | 确认用户已在手机端留存，或已迁移 |
| `Documents\Tencent Files` | QQ 聊天记录与文件 | 同上 |
| `%APPDATA%\` 下任意应用目录 | 用户配置、账号登录态 | 删除会导致重新登录、配置丢失 |
| `Downloads` | 用户主动下载的文件 | 逐项看，不要整目录删 |
| `Desktop` | 用户放在桌面的文件 | 不要碰 |
| `Pictures` / `Videos` / `Music` | 用户媒体文件 | 不要碰 |
| `AppData\Local\Packages\*` | UWP 应用数据，含设置与本地库 | 只删 `LocalCache`、`TempState` 子目录 |
| `%LOCALAPPDATA%\Docker\wsl` | `ext4.vhdx` 里是容器与镜像数据 | 删除等于丢掉所有容器 |
| WSL 发行版 `ext4.vhdx` | 整个 Linux 文件系统 | 删除等于清空该发行版 |
| 游戏安装目录 | 存档可能在用户目录，也可能在游戏目录 | 确认存档位置 |
| `%LOCALAPPDATA%\Programs` | 应用安装位置（VS Code、Discord 等） | 不是缓存，删除等于卸载 |

---

## C · 不要删

| 路径 | 原因 |
|---|---|
| `C:\Windows\WinSxS` | 组件库。**手动删除会破坏系统**。只能用 DISM 清理 |
| `C:\Windows\Installer` | MSI 与补丁缓存。删除后无法修复、无法卸载、无法更新 |
| `C:\Windows\System32`、`SysWOW64` | 系统核心 |
| `C:\Windows\Fonts` | 字体 |
| `C:\ProgramData\Microsoft\Crypto` | 证书与密钥 |
| `C:\Users\X\AppData\Roaming\Microsoft\Crypto` | 同上 |
| `C:\Windows\System32\config` | 注册表数据库 |
| `C:\$Recycle.Bin` 以外的 `$` 开头目录 | 系统元数据 |
| `pagefile.sys`、`hiberfil.sys`、`swapfile.sys` | 用系统设置调整，不要手动删文件 |

---

## D · 看着像垃圾，其实不是

| 路径 | 真实身份 |
|---|---|
| `WPS Cloud Files\...\cachedata` | 云文档本地副本，是真实文档 |
| `AppData\Local\Microsoft\OneDrive\cache` | 同步缓存，可能含未上传文件 |
| `AppData\Local\Google\Chrome\User Data\Default\IndexedDB` | 网页应用数据，删了丢本地数据 |
| `AppData\Roaming\Code\User` | VS Code 配置、插件设置、代码片段 |
| `Documents\My Games` | 游戏存档 |
| `%LOCALAPPDATA%\Packages\*\LocalState` | 应用数据库（笔记、账本、聊天库） |
| `C:\Windows\SoftwareDistribution` 整目录 | 消息队列与更新历史，只能删 `Download` 子目录 |

---

## E · 系统空间大户（不是清理对象，但要认识）

| 项 | 典型占用 | 处理方式 |
|---|---|---|
| `pagefile.sys` | 8–16 GB | 虚拟内存设置，改固定大小或移到其他盘 |
| `hiberfil.sys` | ≈ 内存 × 75% | `powercfg /h off` |
| `WinSxS` | 显示 8–12 GB | DISM 清理，真实可回收 1–3 GB |
| 系统还原点 | 3–10 GB | `vssadmin` 管理，删除前告知用户 |
| `C:\Windows\Installer` | 1–5 GB | 不删。用 PatchCleaner 类工具谨慎处理 |
| WSL / Docker 虚拟磁盘 | 10–60 GB | 用 `wsl --manage --set-sparse` 或重建镜像 |
| 休眠与快速启动文件 | 6 GB | 同 hiberfil |

---

## 判定流程

1. 在表里找到路径 → 得到初判。
2. 跑 `python scripts/survey.py "$p" --sample 5` → 得到实测结论。
3. 两者冲突时**以实测为准**，并把冲突记录下来，更新本表。
4. 结论为 `BACKUP` 时，先 robocopy 到其他盘，比对差异为 0，再删。
