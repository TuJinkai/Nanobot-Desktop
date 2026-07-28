# 构建 Pake 桌面窗口（带 VS MSVC 环境）。
#
# 做三件事：
#   1. 走 vcvars64.bat 配好 MSVC 环境（link.exe + Windows SDK）
#   2. 临时启动前端路由 onboard_server.py（:24691），供 pake-cli 构建时抓取页面
#   3. 用 pake-cli 构建 → output/nanobot.exe（含中文 locale 注入）
#
# 前置：Rust (rustup)、VS 2022 Build Tools (VCTools)、Node + pake-cli (npm i -g pake-cli)。
#
# 用法：powershell -ExecutionPolicy Bypass -File desktop/scripts/build_pake_env.ps1

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = Split-Path -Parent $here
$repo = Split-Path -Parent $desktop
$output = Join-Path $desktop "output"
$assets = Join-Path $desktop "assets"
$backend = Join-Path $desktop "backend"
$inject = Join-Path $assets "inject-locale.js"
$icon = Join-Path $assets "nanobot_icon.png"

# --- 0. 确认 Pake 烘焙端口空闲（不可漂移）--------------------------------
# Pake 入口 URL 在构建时烘焙进 nanobot.exe，运行时无法漂移，所以构建/运行都
# 必须能用这个端口。24691 选在 IANA 注册区且低于各平台临时端口下限，极少冲突。
$RouterPort = 24691
function Test-PortFree([int]$Port) {
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start(); $listener.Stop()
        return $true
    } catch {
        return $false
    }
}
if (-not (Test-PortFree $RouterPort)) {
    Write-Host "端口 $RouterPort 已被占用。Pake 入口烘焙在该端口、无法漂移；请释放后重试。" -ForegroundColor Red
    exit 1
}

# --- 1. MSVC 环境 ----------------------------------------------------------
Write-Host "=== 配置 MSVC 构建环境 ===" -ForegroundColor Cyan
$vcvars = $env:PAKE_VCVARS
if (-not $vcvars) {
    $vcvars = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
}
if (-not (Test-Path $vcvars)) {
    Write-Host "找不到 vcvars64.bat：$vcvars" -ForegroundColor Red
    Write-Host "请先安装 VS 2022 Build Tools 的 VCTools workload，或用 -env PAKE_VCVARS 指定路径。" -ForegroundColor Red
    exit 1
}
cmd /c "`"$vcvars`" > nul && set" | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2]) }
}
Write-Host "MSVC link.exe:" -ForegroundColor Green
cmd /c "where link.exe" | Select-Object -First 2
# tauri-build shells out to vswhere to locate the toolchain; vcvars does not
# put it on PATH, so add the VS Installer dir explicitly (benign if absent).
$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) { $env:PATH = (Split-Path $vswhere) + ';' + $env:PATH }

# --- 2. 临时启动前端路由（:24691）-------------------------------------------
Write-Host "`n=== 临时启动前端路由（供 pake 抓取页面）===" -ForegroundColor Cyan
$pyExe = Join-Path $output "python-bundle\python.exe"
if (-not (Test-Path $pyExe)) { $pyExe = "python" }
$env:PYTHONNOUSERSITE = "1"
$router = Start-Process -FilePath $pyExe `
    -ArgumentList @((Join-Path $backend "onboard_server.py")) `
    -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 2

# --- 3. 构建 Pake ----------------------------------------------------------
Write-Host "`n=== 构建 Pake（:24691 + 中文注入）===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $output | Out-Null

$pakeCmd = "$env:APPDATA\npm\pake.cmd"
# Invoke pake-cli with the call operator (&). `Start-Process -Wait` hangs on
# pake-cli's spawned tauri/wix subprocess tree (it never returns); & runs it
# inline, returns cleanly, and $LASTEXITCODE carries the exit code. (Not
# `cmd /c "pake.cmd" …` — that trips cmd's quote rules and errors out.)
Push-Location $output
& $pakeCmd http://127.0.0.1:24691 --name nanobot --identifier com.nanobot.desktop --icon $icon --width 1100 --height 720 --inject $inject
$pakeExit = $LASTEXITCODE
Pop-Location

# 停止临时路由
Stop-Process -Id $router.Id -Force -ErrorAction SilentlyContinue

if ($pakeExit -ne 0) {
    Write-Host "`n=== Pake 构建失败 (exit $pakeExit) ===" -ForegroundColor Red
    exit $pakeExit
}

# 拷贝产物 → output/nanobot.exe
$built = Join-Path $env:APPDATA "npm\node_modules\pake-cli\src-tauri\target\x86_64-pc-windows-msvc\release\pake-nanobot.exe"
if (Test-Path $built) {
    Copy-Item -Force $built (Join-Path $output "nanobot.exe")
    Write-Host "`n=== Pake 构建成功 → $(Join-Path $output 'nanobot.exe') ===" -ForegroundColor Green
} else {
    Write-Host "`n构建完成但未找到 pake-nanobot.exe，请手动从 pake-cli target 拷贝。" -ForegroundColor Yellow
}
exit 0
