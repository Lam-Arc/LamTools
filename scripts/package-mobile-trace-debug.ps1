<#
.SYNOPSIS
  Build a trace-enabled Android debug APK for either existing signing identity.
.DESCRIPTION
  Release mode uses the existing user-scoped key and DPAPI-protected password.
  Debug mode uses Gradle's default debug signing key. Neither mode creates or
  replaces release signing credentials.
#>
param(
    [ValidateSet('Release', 'Debug')][string]$SigningMode = 'Release',
    [string]$OutputPath = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$mobileRoot = Join-Path $root 'core\mobile'
$androidRoot = Join-Path $mobileRoot 'src-tauri\gen\android'
$version = [string]((Get-Content -LiteralPath (Join-Path $mobileRoot 'package.json') -Raw | ConvertFrom-Json).version)
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Unsupported mobile version: $version" }
$signingRoot = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.lamtools\signing'
$keystorePath = Join-Path $signingRoot 'lamtools-mobile-release.p12'
$passwordPath = Join-Path $signingRoot 'lamtools-mobile-release.password.dpapi'
$referenceApk = if ($SigningMode -eq 'Release') {
    Join-Path $root "release\mobile\Sunday-mobile_$version.apk"
} else {
    Join-Path $root "release\mobile\Sunday-mobile_$version-debug-aarch64.apk"
}
$builtApk = Join-Path $androidRoot 'app\build\outputs\apk\universal\debug\app-universal-debug.apk'
$javaRoot = 'C:\Users\Administrator\AppData\Roaming\.minecraft\runtime\java-runtime-delta'
$sdkRoot = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { 'E:\Environment\AndroidSDK' }
if (-not $OutputPath) {
    $modeLabel = if ($SigningMode -eq 'Release') { 'release-signed' } else { 'debug-signed' }
    $OutputPath = Join-Path $mobileRoot "artifacts\Sunday-mobile-trace-debug-$version-$(Get-Date -Format yyyyMMdd)-$modeLabel.apk"
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)

$requiredFiles = @($referenceApk, (Join-Path $javaRoot 'bin\java.exe'))
if ($SigningMode -eq 'Release') { $requiredFiles += @($keystorePath, $passwordPath) }
foreach ($required in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required signing or build input is missing: $required"
    }
}
$secret = $null
if ($SigningMode -eq 'Release') {
    $encrypted = (Get-Content -LiteralPath $passwordPath -Raw).Trim()
    if (-not $encrypted) { throw "Signing credential file is empty: $passwordPath" }
    $secure = ConvertTo-SecureString -String $encrypted
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $secret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

$savedEnvironment = @{}
$environmentNames = @(
    'JAVA_HOME', 'Path', 'ANDROID_HOME', 'NDK_HOME', 'VITE_MOBILE_TRACE_TURNS',
    'LAMTOOLS_ANDROID_SIGN_DEBUG_WITH_RELEASE',
    'LAMTOOLS_ANDROID_KEYSTORE_PATH', 'LAMTOOLS_ANDROID_KEYSTORE_PASSWORD',
    'LAMTOOLS_ANDROID_KEY_ALIAS', 'LAMTOOLS_ANDROID_KEY_PASSWORD'
)
foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:JAVA_HOME = $javaRoot
    $env:Path = "$javaRoot\bin;$($savedEnvironment['Path'])"
    $env:ANDROID_HOME = $sdkRoot
    $env:NDK_HOME = Join-Path $sdkRoot 'ndk\28.2.13676358'
    $env:VITE_MOBILE_TRACE_TURNS = '1'
    if ($SigningMode -eq 'Release') {
        $env:LAMTOOLS_ANDROID_SIGN_DEBUG_WITH_RELEASE = '1'
        $env:LAMTOOLS_ANDROID_KEYSTORE_PATH = $keystorePath
        $env:LAMTOOLS_ANDROID_KEYSTORE_PASSWORD = $secret
        $env:LAMTOOLS_ANDROID_KEY_ALIAS = 'lamtools-mobile-release'
        $env:LAMTOOLS_ANDROID_KEY_PASSWORD = $secret
    } else {
        # Guard against inherited opt-in credentials changing the debug identity.
        foreach ($name in $environmentNames | Where-Object { $_ -like 'LAMTOOLS_ANDROID_*' }) {
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        }
    }
    Push-Location $mobileRoot
    try {
        & npm.cmd run tauri -- android build --debug --apk --target aarch64 --ci
        if ($LASTEXITCODE -ne 0) { throw "Tauri Android debug build failed (exit code $LASTEXITCODE)." }
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
    $secret = $null
}

if (-not (Test-Path -LiteralPath $builtApk -PathType Leaf)) {
    throw "Signed debug APK was not produced: $builtApk"
}
$apksigner = Get-ChildItem (Join-Path $sdkRoot 'build-tools') -Directory |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName 'apksigner.bat' } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if (-not $apksigner) { throw 'Android apksigner was not found.' }
function Get-ApkSignerDigest {
    param([Parameter(Mandatory)][string]$ApkPath)
    $signerOutput = & $apksigner verify --print-certs $ApkPath
    $signerExitCode = $LASTEXITCODE
    $digestMatch = $signerOutput | Select-String 'certificate SHA-256 digest: ([0-9a-f]+)' | Select-Object -First 1
    if ($signerExitCode -ne 0 -or -not $digestMatch) {
        throw "Could not verify APK signature: $ApkPath"
    }
    return $digestMatch.Matches.Groups[1].Value
}
$referenceDigest = Get-ApkSignerDigest -ApkPath $referenceApk
$builtDigest = Get-ApkSignerDigest -ApkPath $builtApk
if ($builtDigest -ne $referenceDigest) { throw "Debug APK certificate differs from the $SigningMode reference APK; refusing to distribute it." }

$outputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
Copy-Item -LiteralPath $builtApk -Destination $OutputPath -Force
Write-Host "Signed trace APK: $OutputPath"
Write-Host "Certificate SHA-256: $builtDigest"
Write-Host "APK SHA-256: $((Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash)"
