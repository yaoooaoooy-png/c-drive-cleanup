<#
  把本技能从 GitHub 同步到 WorkBuddy 技能目录。

  用法（在仓库根目录或其任意子目录）：
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync.ps1 -Quiet

  行为：
    1. git fetch + reset --hard origin/main，把仓库对齐到远程
    2. robocopy /MIR 镜像到 %USERPROFILE%\.workbuddy\skills\C盘清理
    3. 结果写日志 %USERPROFILE%\.workbuddy\skill-src\sync.log

  安全约束：
    - 目标目录的父级必须是 .workbuddy\skills，否则拒绝执行
    - .git 不参与镜像
    - 同一时刻只允许一个实例运行
#>
param([switch]$Quiet)

$ErrorActionPreference = 'Stop'

function Say($msg) { if (-not $Quiet) { Write-Host $msg } }

$repo   = Split-Path -Parent $PSScriptRoot
$root   = Join-Path $env:USERPROFILE '.workbuddy'
$skills = Join-Path $root 'skills'
$dest   = Join-Path $skills 'C盘清理'
$logDir = Join-Path $root 'skill-src'
$log    = Join-Path $logDir 'sync.log'
$lock   = Join-Path $logDir 'sync.lock'

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }

# 安全闸：目标路径必须在 .workbuddy\skills 之下
$destFull  = [System.IO.Path]::GetFullPath($dest)
$skillsFull = [System.IO.Path]::GetFullPath($skills)
if (-not $destFull.StartsWith($skillsFull + [System.IO.Path]::DirectorySeparatorChar)) {
    throw "目标路径不在技能目录下，已中止：$destFull"
}
if (-not (Test-Path (Join-Path $repo '.git'))) { throw "不是 Git 仓库：$repo" }

# 单实例锁
try {
    $fh = [System.IO.File]::Open($lock, 'OpenOrCreate', 'ReadWrite', 'None')
} catch {
    Say '另一个同步实例正在运行，本次跳过。'
    exit 0
}

function WriteLog($text) {
    Add-Content -Path $log -Value $text -Encoding UTF8
    if ((Get-Item $log).Length -gt 200KB) {
        $tail = Get-Content $log -Tail 200
        Set-Content -Path $log -Value $tail -Encoding UTF8
    }
}

try {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

    $before = (& git -C $repo rev-parse HEAD 2>$null)
    & git -C $repo fetch --quiet origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'git fetch 失败，检查网络或远程地址' }
    & git -C $repo reset --hard --quiet origin/main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'git reset 失败' }
    $after = (& git -C $repo rev-parse HEAD 2>$null)

    robocopy $repo $destFull /MIR /XD ".git" /NFL /NDL /NJH /NJS /NP | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -ge 8) { throw "robocopy 失败，退出码 $rc" }

    $short = { param($h) if ($h) { $h.Substring(0, 7) } else { 'unknown' } }
    if ($before -ne $after) {
        $line = "$stamp  $(& $short $before) -> $(& $short $after)  已更新"
    } else {
        $line = "$stamp  $(& $short $after)  无变化"
    }
    WriteLog $line
    Say $line
    Say "目标：$destFull"
    exit 0
} catch {
    WriteLog "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  失败  $($_.Exception.Message)"
    Say "同步失败：$($_.Exception.Message)"
    exit 1
} finally {
    $fh.Close()
    $fh.Dispose()
}
