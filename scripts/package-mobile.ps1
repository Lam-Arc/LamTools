<#
.SYNOPSIS
  Build the signed Sunday Android APK.
.DESCRIPTION
  Creates or reuses a user-scoped release keystore.  The keystore remains
  outside the repository and its password is protected with the current
  Windows user's DPAPI.  Credentials are injected into one Gradle process and
  are never written to the repository or printed.
#>
param()

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$MobileRoot = Join-Path $Root 'core\mobile'
$AndroidRoot = Join-Path $MobileRoot 'android'
$PackagePath = Join-Path $MobileRoot 'package.json'
$JavaRoot = 'C:\Users\Administrator\AppData\Roaming\.minecraft\runtime\java-runtime-delta'
$AndroidSdkRoot = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { 'E:\Environment\AndroidSDK' }
$SigningRoot = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.lamtools\signing'
$KeystorePath = Join-Path $SigningRoot 'lamtools-mobile-release.p12'
$PasswordPath = Join-Path $SigningRoot 'lamtools-mobile-release.password.dpapi'
$KeyAlias = 'lamtools-mobile-release'
$OutputRoot = Join-Path $Root 'release\mobile'

function Read-DpapiSecret {
    param([Parameter(Mandatory)][string]$Path)

    $encrypted = (Get-Content -LiteralPath $Path -Raw).Trim()
    if (-not $encrypted) { throw "Signing credential file is empty: $Path" }
    $secure = ConvertTo-SecureString -String $encrypted
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function New-RandomSecret {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', 'A').Replace('/', 'B')
}

function Save-DpapiSecret {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Secret
    )

    $secure = ConvertTo-SecureString -String $Secret -AsPlainText -Force
    $encrypted = ConvertFrom-SecureString -SecureString $secure
    Set-Content -LiteralPath $Path -Value $encrypted -Encoding ascii -NoNewline
}

function Ensure-ReleaseCredentials {
    New-Item -ItemType Directory -Path $SigningRoot -Force | Out-Null
    $hasKeystore = Test-Path -LiteralPath $KeystorePath -PathType Leaf
    $hasPassword = Test-Path -LiteralPath $PasswordPath -PathType Leaf
    if ($hasKeystore -ne $hasPassword) {
        throw "Release signing state is incomplete. Keep both files or restore them: $KeystorePath and $PasswordPath"
    }

    if ($hasKeystore) {
        return Read-DpapiSecret -Path $PasswordPath
    }

    $secret = New-RandomSecret
    $keytool = Join-Path $JavaRoot 'bin\keytool.exe'
    if (-not (Test-Path -LiteralPath $keytool -PathType Leaf)) {
        throw "Required keytool was not found: $keytool"
    }
    $arguments = @(
        '-genkeypair',
        '-noprompt',
        '-alias', $KeyAlias,
        '-keyalg', 'RSA',
        '-keysize', '2048',
        '-validity', '10000',
        '-storetype', 'PKCS12',
        '-keystore', $KeystorePath,
        '-storepass', $secret,
        '-keypass', $secret,
        '-dname', 'CN=LamTools Mobile, OU=LamTools, O=LamTools, L=Unknown, ST=Unknown, C=CN'
    )
    & $keytool @arguments *> $null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $KeystorePath -PathType Leaf)) {
        throw "Unable to create the release keystore: $KeystorePath"
    }
    Save-DpapiSecret -Path $PasswordPath -Secret $secret
    return $secret
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$Description
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed (exit code $LASTEXITCODE)."
    }
}

if (-not (Test-Path -LiteralPath $JavaRoot -PathType Container)) {
    throw "Required Java runtime was not found: $JavaRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $JavaRoot 'bin\java.exe') -PathType Leaf)) {
    throw "Required java.exe was not found under: $JavaRoot"
}
if (-not (Test-Path -LiteralPath $MobileRoot -PathType Container)) {
    throw "Mobile project was not found: $MobileRoot"
}

$package = Get-Content -LiteralPath $PackagePath -Raw | ConvertFrom-Json
$version = [string]$package.version
if ($version -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Invalid mobile version '$version' in $PackagePath"
}
$gradlePath = Join-Path $AndroidRoot 'app\build.gradle'
$gradleText = Get-Content -LiteralPath $gradlePath -Raw
$versionCodeMatch = [Regex]::Match($gradleText, '(?m)^\s*versionCode\s+(\d+)\s*$')
if (-not $versionCodeMatch.Success) { throw "Unable to read Android versionCode from $gradlePath" }
$versionCode = $versionCodeMatch.Groups[1].Value
$apkName = "Sunday-mobile_$version.apk"
$expectedAppLabel = 'Sunday'

$secret = Ensure-ReleaseCredentials
$previousJavaHome = [Environment]::GetEnvironmentVariable('JAVA_HOME', 'Process')
$previousPath = [Environment]::GetEnvironmentVariable('Path', 'Process')
$signingNames = @(
    'LAMTOOLS_ANDROID_KEYSTORE_PATH',
    'LAMTOOLS_ANDROID_KEYSTORE_PASSWORD',
    'LAMTOOLS_ANDROID_KEY_ALIAS',
    'LAMTOOLS_ANDROID_KEY_PASSWORD'
)
$previousSigning = @{}
foreach ($name in $signingNames) {
    $previousSigning[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    $env:JAVA_HOME = $JavaRoot
    $env:Path = "$JavaRoot\bin;$previousPath"
    $env:LAMTOOLS_ANDROID_KEYSTORE_PATH = $KeystorePath
    $env:LAMTOOLS_ANDROID_KEYSTORE_PASSWORD = $secret
    $env:LAMTOOLS_ANDROID_KEY_ALIAS = $KeyAlias
    $env:LAMTOOLS_ANDROID_KEY_PASSWORD = $secret

    Push-Location $MobileRoot
    try {
        Invoke-Checked -FilePath 'npm.cmd' -Arguments @('run', 'cap:sync') -Description 'Capacitor sync'
    } finally {
        Pop-Location
    }

    Push-Location $AndroidRoot
    try {
        Invoke-Checked -FilePath '.\gradlew.bat' -Arguments @('assembleRelease', '--no-daemon') -Description 'Android release build'
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in $signingNames) {
        [Environment]::SetEnvironmentVariable($name, $previousSigning[$name], 'Process')
    }
    [Environment]::SetEnvironmentVariable('JAVA_HOME', $previousJavaHome, 'Process')
    [Environment]::SetEnvironmentVariable('Path', $previousPath, 'Process')
}

$builtApk = Join-Path $AndroidRoot 'app\build\outputs\apk\release\app-release.apk'
if (-not (Test-Path -LiteralPath $builtApk -PathType Leaf)) {
    throw "Release APK was not produced: $builtApk"
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$outputApk = Join-Path $OutputRoot $apkName
Copy-Item -LiteralPath $builtApk -Destination $outputApk -Force

$verificationPreviousJavaHome = [Environment]::GetEnvironmentVariable('JAVA_HOME', 'Process')
$verificationPreviousPath = [Environment]::GetEnvironmentVariable('Path', 'Process')
try {
    # apksigner/aapt are Java launchers too.  Restore the known JDK for
    # verification because the build-scoped environment cleanup ran above.
    $env:JAVA_HOME = $JavaRoot
    $env:Path = "$JavaRoot\bin;$verificationPreviousPath"

    $buildToolsRoot = Join-Path $AndroidSdkRoot 'build-tools'
    $buildTools = Get-ChildItem -LiteralPath $buildToolsRoot -Directory |
        Sort-Object Name -Descending |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'apksigner.bat') -PathType Leaf }
    $buildToolsDir = $buildTools | Select-Object -First 1
    if (-not $buildToolsDir) { throw "Android build-tools with apksigner.bat were not found under $buildToolsRoot" }
    $apksigner = Join-Path $buildToolsDir.FullName 'apksigner.bat'
    $aapt = Join-Path $buildToolsDir.FullName 'aapt.exe'

    $signatureOutput = @(& $apksigner verify --verbose --print-certs $outputApk 2>&1)
    if ($LASTEXITCODE -ne 0 -or -not ($signatureOutput -match 'Verifies')) {
        throw "apksigner verification failed for $outputApk"
    }
    if (-not ($signatureOutput -match 'Number of signers:\s+1')) {
        throw "Unexpected signer count in $outputApk"
    }
    $packageOutput = @(& $aapt dump badging $outputApk 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect APK metadata: $outputApk" }
    $packageLine = $packageOutput | Select-String "^package:.*versionCode='$versionCode'.*versionName='$version'"
    if (-not $packageLine) {
        throw "APK metadata does not match package version $version / versionCode $versionCode"
    }
    $labelLine = $packageOutput | Where-Object { $_ -eq "application-label:'$expectedAppLabel'" }
    if (-not $labelLine) {
        throw "APK application label is not '$expectedAppLabel'"
    }

    $manifestOutput = @(& $aapt dump xmltree $outputApk AndroidManifest.xml 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect APK manifest flags: $outputApk" }
    $enabledBuildFlags = $manifestOutput -match 'android:(debuggable|testOnly)\b.*(0xffffffff|true)'
    if ($enabledBuildFlags) {
        throw "Release APK must not be debuggable or testOnly"
    }

    $size = (Get-Item -LiteralPath $outputApk).Length
    $sha256 = (Get-FileHash -LiteralPath $outputApk -Algorithm SHA256).Hash
    Write-Host ''
    Write-Host '=== Signed Android release complete ===' -ForegroundColor Green
    Write-Host "APK:       $outputApk"
    Write-Host "Version:   $version (versionCode $versionCode)"
    Write-Host "Label:     $expectedAppLabel (non-debuggable, non-testOnly)"
    Write-Host "SizeBytes: $size"
    Write-Host "SHA256:    $sha256"
    Write-Host "Keystore:  $KeystorePath"
    Write-Host "Signature: verified with $apksigner"
    $signatureOutput |
        Select-String 'Verifies|Number of signers:|certificate DN:|certificate SHA-256 digest:' |
        ForEach-Object { Write-Host "  $($_.Line.Trim())" }
} finally {
    [Environment]::SetEnvironmentVariable('JAVA_HOME', $verificationPreviousJavaHome, 'Process')
    [Environment]::SetEnvironmentVariable('Path', $verificationPreviousPath, 'Process')
}
