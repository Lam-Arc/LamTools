<# user:“该修就修，不用停下”+(固定原版提交、独立构建依赖和可复现入口)。 #>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$buildRoot = Join-Path $repoRoot '.build'
$source = Join-Path $buildRoot 'obsidian-excalidraw-upstream'
$toolchain = Join-Path $buildRoot 'excalidraw-toolchain'
$expected = '5e4c83f6370f93d3f794ef7afb9545a6b6208c11'
New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
if (-not (Test-Path -LiteralPath $source)) {
    & git clone --depth 1 --filter=blob:none --no-checkout 'https://github.com/zsviczian/obsidian-excalidraw-plugin.git' $source
    if ($LASTEXITCODE -ne 0) { throw 'Cannot clone Excalidraw source' }
    & git -C $source fetch --depth 1 origin $expected
    if ($LASTEXITCODE -ne 0) { throw 'Cannot fetch pinned Excalidraw commit' }
    & git -C $source checkout --detach $expected
    if ($LASTEXITCODE -ne 0) { throw 'Cannot select pinned Excalidraw commit' }
}
$actual = (& git -C $source rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actual -ne $expected) { throw "Excalidraw source must be at $expected; found $actual" }
if (-not (Test-Path -LiteralPath (Join-Path $source 'node_modules/@zsviczian/excalidraw/package.json'))) {
    Push-Location $source
    try { & npm ci --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { throw 'Cannot install upstream dependencies' } }
    finally { Pop-Location }
}
New-Item -ItemType Directory -Force -Path $toolchain | Out-Null
foreach ($name in @('package.json','package-lock.json')) {
    $from = Join-Path $repoRoot "plugins/excalidraw/build/$name"
    $to = Join-Path $toolchain $name
    if ((Test-Path -LiteralPath $to) -and (Get-FileHash -LiteralPath $from).Hash -ne (Get-FileHash -LiteralPath $to).Hash) { throw "Existing toolchain file differs: $to" }
    if (-not (Test-Path -LiteralPath $to)) { Copy-Item -LiteralPath $from -Destination $to }
}
if (-not (Test-Path -LiteralPath (Join-Path $toolchain 'node_modules/esbuild/package.json'))) {
    & npm ci --prefix $toolchain --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Cannot install pinned Excalidraw build tools' }
}
Push-Location $repoRoot
try {
    foreach ($script in @('build-excalidraw-markdown.mjs','build-excalidraw-writer.mjs','build-excalidraw-mermaid.mjs','build-excalidraw-ui.mjs')) {
        & node (Join-Path $PSScriptRoot $script)
        if ($LASTEXITCODE -ne 0) { throw "Build failed: $script" }
    }
    & node --test scripts/test-excalidraw-build.mjs
    if ($LASTEXITCODE -ne 0) { throw 'Reproducibility check failed' }
} finally { Pop-Location }
