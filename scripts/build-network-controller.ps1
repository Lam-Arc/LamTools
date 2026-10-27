# user:“建议还是集成一下吧，尽量不把这些安装操作留给用户”+(构建控制器并准备随插件提供的 Mihomo/aria2)。
param([switch]$DebugBuild)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$pluginDir = Join-Path $taskRoot 'core/src/lamtools_core/plugins/bundled/network-exploration'
$buildDir = Join-Path $taskRoot '.build/network-controller'
# user:“界面太狗屎 打回重做”+(开发构建同时更新新版 Vue 界面)。
Push-Location "$taskRoot/core/ui"
try {
    & "$taskRoot/core/ui/node_modules/.bin/vite.cmd" build --config "$taskRoot/core/ui/vite.config.network-plugin.ts"
    if ($LASTEXITCODE -ne 0) { throw 'Network interface build failed' }
} finally { Pop-Location }
# user:“建议还是集成一下吧，尽量不把这些安装操作留给用户”+(构建时准备固定版本的 Mihomo/aria2 和许可证)。
& python "$pluginDir/engine_install.py"
if ($LASTEXITCODE -ne 0) { throw 'Bundled network engines could not be prepared' }
$cargoArgs = @('build','--locked','--manifest-path',"$pluginDir/controller/Cargo.toml",'--target-dir',$buildDir)
$profile = 'debug'
if (-not $DebugBuild) { $cargoArgs += '--release'; $profile = 'release' }
& cargo @cargoArgs
if ($LASTEXITCODE -ne 0) { throw 'Network Controller build failed' }
New-Item -ItemType Directory -Force -Path "$pluginDir/bin" | Out-Null
$target = "$pluginDir/bin/sunday-network-controller.exe"
$source = "$buildDir/$profile/sunday-network-controller.exe"
try {
    Copy-Item -LiteralPath $source -Destination $target -Force -ErrorAction Stop
} catch [System.IO.IOException] {
    # A running Sunday holds the executable. Windows allows the running image
    # to be renamed, so the next full restart picks up the new controller.
    $retired = "$target.old"
    Remove-Item -LiteralPath $retired -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $target -Destination $retired -Force
    Copy-Item -LiteralPath $source -Destination $target -Force
    Write-Warning "Controller was running; new build installed and the previous image kept as $retired until restart."
}
