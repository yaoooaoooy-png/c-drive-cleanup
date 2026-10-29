<#
  从 GitHub 同步本技能到 WorkBuddy 技能目录。

  用法：
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync.ps1 -Quiet
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync.ps1 -SkipFetch   # 只做镜像

  1. fetch 远程 main（先 HTTPS 后 SSH，任一成功即可）
  2. reset --hard 到 FETCH_HEAD
  3. robocopy /MIR 镜像到 %USERPROFILE%\.workbuddy\skills\C盘清理
  4. 结果写 %USERPROFILE%\.workbuddy\skill-src\sync.log
#>
param(
  [switch]$Quiet,
  [switch]$SkipFetch
)

$ErrorActionPreference = 'Stop'

$repo   = Split-Path -Parent $PSScriptRoot
$root   = Join-Path $env:USERPROFILE '.workbuddy'
$skills = Join-Path $root 'skills'
$dest   = Join-Path $skills 'C盘清理'
$logDir = Join-Path $root 'skill-src'
$log    = Join-Path $logDir 'sync.log'
$lock   = Join-Path $logDir 'sync.lock'

function Say($m) { if (-not $Quiet) { Write-Host $m } }
function Short($h) { if ($h) { $h.Substring(0, 7) } else { 'unknown' } }
function Stamp { Get-Date -Format 'yyyy-MM-dd HH:mm:ss' }

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }

# 安全闸：目标必须在技能目录之下
$destFull   = [System.IO.Path]::GetFullPath($dest)
$skillsFull = [System.IO.Path]::GetFullPath($skills)
if (-not $destFull.StartsWith($skillsFull + [System.IO.Path]::DirectorySeparatorChar)) {
  throw "目标不在技能目录下，已中止：$destFull"
}
if (-not $SkipFetch -and -not (Test-Path (Join-Path $repo '.git'))) {
  throw "不是 Git 仓库：$repo"
}

function WriteLog($t) {
  Add-Content -Path $log -Value $t -Encoding UTF8
  if ((Get-Item $log).Length -gt 200KB) {
    $tail = Get-Content $log -Tail 200 -Encoding UTF8
    Set-Content -Path $log -Value $tail -Encoding UTF8
  }
}

# 单实例锁
try { $fh = [System.IO.File]::Open($lock, 'OpenOrCreate', 'ReadWrite', 'None') }
catch { Say '另一个同步实例正在运行，本次跳过。'; exit 0 }

try {
  $before = if ($SkipFetch) { $null } else { (& git -C $repo rev-parse HEAD 2>$null) }

  if (-not $SkipFetch) {
    # SSH 私钥列表：非标准文件名（如 id_ed25519_github）也要能用
    $keyArgs = @()
    $sshDir = Join-Path $env:USERPROFILE '.ssh'
    if (Test-Path $sshDir) {
      $keys = Get-ChildItem $sshDir -Filter 'id_*' -File -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -notlike '*.pub' }
      foreach ($k in $keys) { $keyArgs += "-i `"$($k.FullName)`"" }
    }
    $sshCmd = "ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new " + ($keyArgs -join ' ')

    $remotes = @(
      @{ Url = 'https://github.com/yaoooaoooy-png/c-drive-cleanup.git'; Opt = @() },
      @{ Url = 'git@github.com:yaoooaoooy-png/c-drive-cleanup.git'; Opt = @('-c', "core.sshCommand=$sshCmd") }
    )
    if ($keyArgs.Count -eq 0) { $remotes = @($remotes[0]) }

    $ok = $false
    $fails = @()
    foreach ($r in $remotes) {
      $opt = $r.Opt
      & git -C $repo -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=25 @opt fetch --quiet --no-tags $r.Url main 2>&1 | Out-Null
      if ($LASTEXITCODE -eq 0) { $ok = $true; break }
      $fails += $r.Url
    }
    if (-not $ok) { throw ('fetch 失败，两个通道都不可用：' + ($fails -join ' / ')) }

    & git -C $repo reset --hard --quiet FETCH_HEAD 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'reset --hard 失败' }
  }

  $after = (& git -C $repo rev-parse HEAD 2>$null)

  robocopy $repo $destFull /MIR /XD ".git" /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy 失败，退出码 $LASTEXITCODE" }

  if ($SkipFetch) {
    $line = "$(Stamp)  $(Short $after)  仅镜像（未拉取）"
  } elseif ($before -ne $after) {
    $line = "$(Stamp)  $(Short $before) -> $(Short $after)  已更新"
  } else {
    $line = "$(Stamp)  $(Short $after)  无变化"
  }
  WriteLog $line
  Say $line
  Say "目标：$destFull"
  exit 0
} catch {
  WriteLog "$(Stamp)  失败  $($_.Exception.Message)"
  Say "同步失败：$($_.Exception.Message)"
  exit 1
} finally {
  if ($fh) { $fh.Close(); $fh.Dispose() }
}
