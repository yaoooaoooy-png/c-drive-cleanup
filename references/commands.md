# 命令配方

全部为 Windows PowerShell。涉及变量时用单引号包裹路径，避免 `$Recycle.Bin` 被当成变量。

---

## 一、测绘

### 各目录体积（只看一级）

```powershell
Get-ChildItem 'C:\Users\X\AppData\Local' -Directory -EA 0 |
  ForEach-Object {
    $s = (Get-ChildItem $_.FullName -Recurse -File -EA 0 |
          Measure-Object Length -Sum).Sum
    [pscustomobject]@{ Path = $_.FullName; GB = [math]::Round($s / 1GB, 2) }
  } | Sort GB -Desc | Select -First 25
```

大目录先测一级，找到目标再逐层下钻。全盘递归一次要几十分钟，不要一开始就全盘扫。

### 最大的文件

```powershell
Get-ChildItem 'C:\' -Recurse -File -EA 0 |
  Sort Length -Desc | Select -First 30 FullName, @{n='GB';e={[math]::Round($_.Length/1GB,2)}}
```

### 磁盘可用空间

```powershell
Get-PSDrive C | Select @{n='GB可用';e={[math]::Round($_.Free/1GB,2)}}
```

### 扩展名分布

```powershell
Get-ChildItem $p -Recurse -File -EA 0 |
  Group-Object Extension | Sort Count -Desc | Select Count, Name
```

### 结构化体检

```bash
python scripts/survey.py "$p" --sample 5 --top 12
python scripts/survey.py "$p" --json > survey.json
```

---

## 二、删除

### 整目录删除（最快）

```powershell
$empty = 'D:\_empty'; New-Item -ItemType Directory -Force $empty | Out-Null
robocopy $empty 'C:\target' /MIR /MT:64 /R:0 /W:0 /NFL /NDL /NJH /NJS /NP
```

实测 243 文件/秒。参数含义：

| 参数 | 作用 |
|---|---|
| `/MIR` | 镜像，目标多出来的文件会被删 |
| `/MT:64` | 64 线程 |
| `/R:0 /W:0` | 不重试、不等待，跳过锁定文件 |
| `/NFL /NDL /NJH /NJS /NP` | 不输出文件、目录、表头、摘要、进度，减少 IO |

`$empty` 必须是空目录。**不要把 `/MIR` 的源写反**，否则会清空源目录。

### 改名后删除（瞬时生效）

```powershell
Rename-Item 'C:\target' 'C:\target.deltmp'
# 确认无误后再删
robocopy $empty 'C:\target.deltmp' /MIR /MT:64 /R:0 /W:0 /NFL /NDL /NJH /NJS /NP
```

### 先停占用进程

```powershell
Get-Process wps,wpscloudsvr,WeChatAppEx,WXWork,msedge,chrome -EA 0 |
  Stop-Process -Force -EA 0
```

实测：被 WPS 占用的目录，删除耗时是普通目录的 9 倍（11877 个文件 698 秒）。停进程后回到正常速率。

### 删除前后计数

```powershell
(Get-ChildItem 'C:\target' -Recurse -File -EA 0).Count
```

残留文件通常是锁定文件。报数时把残留数量报出来。

---

## 三、回收站

### 取证

```bash
python scripts/recycle_list.py --limit 20
python scripts/recycle_list.py --csv D:\recycle_snapshot.csv
python scripts/recycle_list.py --drive C
```

### 清空（快）

```powershell
$sid = (Get-ChildItem 'C:\$Recycle.Bin' -Force -EA 0 | Select -First 1).FullName
robocopy $empty "$sid" /MIR /MT:64 /R:0 /W:0 /NFL /NDL /NJH /NJS /NP
```

实测 188 秒清掉 13.3 万个文件。

### 不要用 Clear-RecycleBin 处理十万级条目

```powershell
# 条目超过 1 万时不要用
Clear-RecycleBin -DriveLetter C -Force -EA 0
```

实测 28 万条目时进度条不动，进程长时间无响应，只能中止。

### 查看回收站大小

```powershell
$size = (Get-ChildItem 'C:\$Recycle.Bin' -Recurse -File -Force -EA 0 |
         Measure-Object Length -Sum).Sum
[math]::Round($size / 1GB, 2)
```

`$Recycle.Bin` 需要 `-Force` 才能列出，因为它是隐藏目录。

---

## 四、系统级回收

**每次清理都先做这一档。** 通常回收 15–25 GB，零数据风险。

### 休眠文件

```powershell
powercfg /h off          # 关闭休眠，回收约 6 GB（≈内存 75%）
powercfg /h on           # 需要时恢复
```

代价：关闭休眠与快速启动。

### 页面文件

命令行修改需要管理员权限，且必须重启。图形界面更稳：

```
系统属性 → 高级 → 性能设置 → 高级 → 虚拟内存 → 更改
```

选择「自定义大小」，初始值与最大值都设 4096 MB；或选择「无分页文件」后在其他盘设置。

实测：12.36 GB 的 `pagefile.sys`，峰值实际用量只有 2.2 GB。修改后回收约 8 GB。

内存小于 8 GB 的机器不要压到 4 GB，否则可能触发内存不足。

### WinSxS 组件库

```powershell
Dism /Online /Cleanup-Image /AnalyzeComponentStore
Dism /Online /Cleanup-Image /StartComponentCleanup /ResetBase
```

先分析，再清理。`/ResetBase` 之后无法卸载已安装的更新。

注意：WinSxS 的目录大小包含硬链接。同一份系统文件被多个组件引用时会被重复计数。实测显示 10.19 GB，真实可回收 1–3 GB。**用 `AnalyzeComponentStore` 的输出为准，不要用目录大小。**

### Windows Update 缓存

```powershell
Stop-Service wuauserv,bits -Force -EA 0
Remove-Item 'C:\Windows\SoftwareDistribution\Download\*' -Recurse -Force -EA 0
Start-Service wuauserv,bits
```

停服务是必须的。服务不停，文件被占用，删不掉。

### 交付优化缓存

```powershell
Delete-DeliveryOptimizationCache -Force
```

### 系统还原点

```powershell
vssadmin list shadowstorage
vssadmin delete shadows /for=C: /oldest
```

删还原点会失去回滚能力。执行前必须告知用户。

---

## 五、收尾

### 恢复被停掉的服务

```powershell
Start-Service wuauserv,bits,DoSvc -EA 0
Get-Service wuauserv,bits,DoSvc | Select Name, Status
```

清理完必须检查一遍。停掉不恢复，系统更新会失效。

### 恢复回收站配额设置

若为测试改过注册表 `NukeOnDelete`，务必改回：

```powershell
$k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume'
Get-ChildItem $k -EA 0 | ForEach-Object {
  Set-ItemProperty $_.PSPath -Name NukeOnDelete -Value 0 -Type DWord -EA 0
}
```

**不建议使用 NukeOnDelete。** 它让删除不可逆，与规则 2 直接冲突。省下的只是清空回收站的时间。

### 验收

```powershell
Get-PSDrive C | Select @{n='GB可用';e={[math]::Round($_.Free/1GB,2)}}
# 回收站当前大小
# 每类的删除计数与残留
```

报三个数：清理前可用、清理后可用、回收站当前大小。
