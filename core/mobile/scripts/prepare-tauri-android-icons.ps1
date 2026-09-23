$ErrorActionPreference = 'Stop'

$MobileRoot = Split-Path -Parent $PSScriptRoot
$SourceRoot = Join-Path $MobileRoot 'src-tauri\icons\android'
$ResourceRoot = Join-Path $MobileRoot 'src-tauri\gen\android\app\src\main\res'
$AdaptiveSource = Join-Path $SourceRoot 'mipmap-anydpi-v26\ic_launcher.xml'
$BackgroundSource = Join-Path $SourceRoot 'values\ic_launcher_background.xml'

if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "Canonical Android launcher icons are missing: $SourceRoot"
}
if (-not (Test-Path -LiteralPath $AdaptiveSource -PathType Leaf)) {
    throw "Adaptive launcher icon definition is missing: $AdaptiveSource"
}
if (-not (Test-Path -LiteralPath $BackgroundSource -PathType Leaf)) {
    throw "Adaptive launcher background color is missing: $BackgroundSource"
}

$densities = @('mipmap-mdpi', 'mipmap-hdpi', 'mipmap-xhdpi', 'mipmap-xxhdpi', 'mipmap-xxxhdpi')
foreach ($density in $densities) {
    $sourceDensity = Join-Path $SourceRoot $density
    $destinationDensity = Join-Path $ResourceRoot $density
    if (-not (Test-Path -LiteralPath $sourceDensity -PathType Container)) {
        throw "Launcher icon density is missing: $sourceDensity"
    }
    New-Item -ItemType Directory -Path $destinationDensity -Force | Out-Null
    foreach ($name in @('ic_launcher.png', 'ic_launcher_round.png', 'ic_launcher_foreground.png')) {
        $sourceFile = Join-Path $sourceDensity $name
        if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) {
            throw "Launcher icon resource is missing: $sourceFile"
        }
        Copy-Item -LiteralPath $sourceFile -Destination (Join-Path $destinationDensity $name) -Force
    }
}

$adaptiveDestination = Join-Path $ResourceRoot 'mipmap-anydpi-v26'
$backgroundDestination = Join-Path $ResourceRoot 'values'
New-Item -ItemType Directory -Path $adaptiveDestination -Force | Out-Null
New-Item -ItemType Directory -Path $backgroundDestination -Force | Out-Null
Copy-Item -LiteralPath $AdaptiveSource -Destination (Join-Path $adaptiveDestination 'ic_launcher.xml') -Force
Copy-Item -LiteralPath $BackgroundSource -Destination (Join-Path $backgroundDestination 'ic_launcher_background.xml') -Force

Write-Host "Synchronized Sunday launcher icons from $SourceRoot"
