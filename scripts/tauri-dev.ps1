<#
.SYNOPSIS
  LamTools Core 桌面观测环境：一条命令拉起 Tauri dev，并脱离当前会话独立运行。

.DESCRIPTION
  启动 core/desktop 的 Tauri 开发环境（唯一观测环境）。该体系与 dev.ps1 / restart.ps1
  完全隔离：前端由 core/desktop 自己的 vite 固定在 127.0.0.1:5173 提供，后端由 Rust
  自行挑选随机空闲端口拉起 `py -3.14 -m lamtools_core.cli serve --port 随机`（cwd=core/），
  接口地址由 Rust 下发给前端，不走 5172，也不走代理。

  本脚本做的事：
    1. 校验 core/desktop 依赖在位；
    2. 检查 5173 占用情况。占用者是本项目 core/desktop 的旧 vite 时，可用 -CleanStaleVite
       清理（仅在无 lamcore.exe 窗口进程运行时才允许）；其他任何进程一律不动，直接报错
       退出（避免误杀别人的进程，或误杀 Tauri 的 vite）；
    3. 以脱离调用会话的方式启动 `npm run tauri dev`，输出重定向落盘到固定日志位置；
    4. 轮询核验：前端 5173 可服务、后端已监听随机端口且 /api/health 应答、窗口进程已起来；
    5. 打印前端地址、后端随机端口与 pid、窗口 pid、日志路径。

  启动后的进程是独立进程（不是本脚本的子进程），关闭调用它的终端也不会退出。

.PARAMETER CleanStaleVite
  允许清理占用 5173 的本项目旧 vite 残留。仅当该进程命令行同时命中 vite 与
  core/desktop 时才清理，其他进程绝不处理。此外还有一道守卫：只要检测到窗口进程
  lamcore.exe 在运行（观测环境可能正处于使用中），即使带了本开关也不清理，直接退出，
  以免误杀正在服务的 vite。

.PARAMETER LogPath
  日志固定落盘路径。默认 %LOCALAPPDATA%\LamTools\logs\tauri-dev.log，每次启动覆盖重写。

.PARAMETER TimeoutSec
  等待环境就绪的超时秒数，默认 900（首次编译 Rust 较慢）。

.EXAMPLE
  .\scripts\tauri-dev.ps1
  启动观测环境（5173 空闲时）。

.EXAMPLE
  .\scripts\tauri-dev.ps1 -CleanStaleVite
  先清理本项目遗留的旧 vite，再启动。

.EXAMPLE
  .\scripts\tauri-dev.ps1 -LogPath E:\tmp\tauri.log -TimeoutSec 1800
  自定义日志位置与超时。

.NOTES
  含中文，文件以 UTF-8 (BOM) 保存，兼容 Windows PowerShell 5.1。
  观测环境已在本脚本之外运行时，再次运行会因 5173 被占用而直接报错退出，不会重复启动。
#>
[CmdletBinding()]
param(
    [switch]$CleanStaleVite,
    [string]$LogPath = (Join-Path $env:LOCALAPPDATA "LamTools\logs\tauri-dev.log"),
    [int]$TimeoutSec = 900
)

$ErrorActionPreference = "Stop"

$Root       = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DesktopDir = Join-Path $Root "core\desktop"
$FrontendPort = 5173

function Write-Info { param([string]$Msg) Write-Host "[tauri-dev] $Msg" -ForegroundColor Cyan }
function Write-Warn2 { param([string]$Msg) Write-Host "[tauri-dev] $Msg" -ForegroundColor Yellow }
function Write-Err2 { param([string]$Msg) Write-Host "[tauri-dev] $Msg" -ForegroundColor Red }

# 5173 上处于 LISTENING 的进程 pid 列表（用 netstat，避免依赖 NetTCPIP 模块）。
function Get-ListenerPids {
    param([int]$Port)
    $ids = New-Object System.Collections.Generic.List[int]
    foreach ($line in @(netstat -ano)) {
        if ($line -match "^\s*TCP\s+127\.0\.0\.1:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            $ids.Add([int]$Matches[1])
        }
    }
    return $ids
}

function Get-ProcessInfo { param([int]$ProcessId)
    Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

# 是否为「本项目的旧 vite 残留」：node 进程且命令行同时命中 vite 与 core/desktop。
function Test-IsProjectVite { param([int]$ProcessId)
    $p = Get-ProcessInfo $ProcessId
    if (-not $p) { return $false }
    if ($p.Name -notmatch '^node(\.exe)?$') { return $false }
    $cl = [string]$p.CommandLine
    return ($cl -match 'vite' -and $cl -match 'core[\\/]desktop')
}

function Get-LamcorePids {
    return @(Get-Process -Name lamcore -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
}

# 后端随机端口从命令行 `--port <n>` 解析。
function Get-PortFromCommandLine { param([string]$CommandLine)
    if ($CommandLine -match '--port\s+(\d+)') { return [int]$Matches[1] }
    return 0
}

# 从 lamcore 的子进程里找后端 python 及其端口。
function Get-BackendForLamcore { param([int]$LamcorePid)
    $kids = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$LamcorePid" -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -match '^python(w)?\.exe$' })
    foreach ($k in $kids) {
        $port = Get-PortFromCommandLine ([string]$k.CommandLine)
        if ($port -gt 0) {
            return [pscustomobject]@{ Pid = [int]$k.ProcessId; Port = $port }
        }
    }
    return $null
}

function Test-HttpOk { param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

# 轮询直到前端可服务 + 后端监听随机端口且健康应答。返回状态对象（Ok 标记成功），
# 超时也返回已探测到的部分信息，便于诊断。
function Wait-Environment {
    param([int[]]$PreExistingLamcore, [int]$TimeoutSec)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $state = [pscustomobject]@{ Ok = $false; FrontendOk = $false; LamcorePid = 0; BackendPid = 0; BackendPort = 0 }
    while ((Get-Date) -lt $deadline) {
        if (-not $state.FrontendOk) {
            $state.FrontendOk = ((Get-ListenerPids $FrontendPort).Count -gt 0)
        }
        if ($state.LamcorePid -eq 0) {
            $cand = @(Get-LamcorePids | Where-Object { $PreExistingLamcore -notcontains $_ })
            if ($cand.Count -gt 0) { $state.LamcorePid = [int]$cand[0] }
        }
        if ($state.LamcorePid -ne 0 -and $state.BackendPort -eq 0) {
            $b = Get-BackendForLamcore $state.LamcorePid
            if ($b) { $state.BackendPid = $b.Pid; $state.BackendPort = $b.Port }
        }
        if ($state.FrontendOk -and $state.BackendPort -ne 0) {
            if (Test-HttpOk "http://127.0.0.1:$($state.BackendPort)/api/health") {
                $state.Ok = $true
                return $state
            }
        }
        Start-Sleep -Seconds 2
    }
    return $state
}

function Invoke-Main {
    Write-Info "仓库根目录: $Root"

    # -- 依赖在位检查 --
    if (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
        Write-Err2 "core/desktop/node_modules 缺失，请先在该目录执行 npm install。"
        exit 1
    }
    if (-not (Test-Path (Join-Path $DesktopDir "src-tauri\tauri.conf.json"))) {
        Write-Err2 "找不到 core/desktop/src-tauri/tauri.conf.json，请确认仓库结构完整。"
        exit 1
    }

    # -- 5173 占用检查 --
    $owners = @(Get-ListenerPids $FrontendPort)
    if ($owners.Count -gt 0) {
        $stale = @()
        $foreign = @()
        foreach ($o in $owners) {
            if (Test-IsProjectVite $o) { $stale += $o } else { $foreign += $o }
        }
        if ($foreign.Count -gt 0) {
            Write-Err2 "端口 $FrontendPort 被非本项目进程占用，已停止（不会动它）："
            foreach ($o in $foreign) {
                $p = Get-ProcessInfo $o
                Write-Err2 ("  pid={0} name={1}" -f $o, $p.Name)
                Write-Err2 ("    cmd={0}" -f [string]$p.CommandLine)
            }
            Write-Err2 "请先自行处理该进程后重试。"
            exit 1
        }
        if (-not $CleanStaleVite) {
            Write-Err2 "端口 $FrontendPort 被本项目旧 vite 占用（pid: $($stale -join ', ')）。"
            Write-Err2 "若观测环境已在运行，则无需重复启动；若确实是残留，请加 -CleanStaleVite 重跑。"
            exit 1
        }
        # 守卫：窗口进程在跑说明观测环境可能正被使用，此时绝不清理，避免误杀正在服务的 vite。
        $liveLamcore = @(Get-LamcorePids)
        if ($liveLamcore.Count -gt 0) {
            Write-Err2 "检测到窗口进程 lamcore.exe 正在运行（pid: $($liveLamcore -join ', ')），观测环境可能正处于使用中。"
            Write-Err2 "即使带了 -CleanStaleVite 也不清理，已退出，以免误杀正在服务的 vite。"
            Write-Err2 "请先完全退出观测环境（关闭窗口并结束相关进程）后再重跑。"
            exit 1
        }
        Write-Warn2 "清理本项目旧 vite 残留: pid=$($stale -join ', ')"
        foreach ($s in $stale) { Stop-Process -Id $s -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1
        if ((Get-ListenerPids $FrontendPort).Count -gt 0) {
            Write-Err2 "端口 $FrontendPort 仍被占用，放弃启动。"
            exit 1
        }
    }

    # -- 脱离会话启动 --
    $logDir = Split-Path -Parent $LogPath
    if ($logDir -and -not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
    $preExisting = @(Get-LamcorePids)

    Write-Info "脱离当前会话启动: npm run tauri dev  (cwd=$DesktopDir)"
    Write-Info "日志: $LogPath"
    $cmdLine = 'npm run tauri dev 1> "' + $LogPath + '" 2>&1'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmdLine -WorkingDirectory $DesktopDir -WindowStyle Hidden | Out-Null

    Write-Info "等待环境就绪（前端 5173 + 后端健康，最多 $TimeoutSec 秒；首次需编译 Rust，较慢）..."
    $state = Wait-Environment -PreExistingLamcore $preExisting -TimeoutSec $TimeoutSec

    if (-not $state.Ok) {
        Write-Err2 "环境在 $TimeoutSec 秒内未就绪。已探测：前端=$($state.FrontendOk) 窗口pid=$($state.LamcorePid) 后端端口=$($state.BackendPort)"
        if (Test-Path $LogPath) {
            Write-Err2 "日志末尾 30 行："
            Get-Content -LiteralPath $LogPath -Tail 30 | ForEach-Object { Write-Host "  $_" }
        }
        exit 1
    }

    # -- 就绪打印 --
    Write-Host ""
    Write-Host "观测环境就绪：" -ForegroundColor Green
    Write-Host ("  前端 : http://127.0.0.1:{0}" -f $FrontendPort)
    Write-Host ("  后端 : http://127.0.0.1:{0}  (pid {1})" -f $state.BackendPort, $state.BackendPid)
    Write-Host ("  窗口 : lamcore.exe pid {0}" -f $state.LamcorePid)
    Write-Host ("  日志 : {0}" -f $LogPath)
    Write-Host ""
    Write-Info "环境为独立进程，关闭本终端不影响运行。"
    exit 0
}

# 被 dot-source 时只载入函数，不执行启动（便于单测）。
if ($MyInvocation.InvocationName -ne '.') { Invoke-Main }
