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
$AndroidRoot = Join-Path $MobileRoot 'src-tauri\gen\android'
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

function Invoke-CheckedWithRetry {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$Description,
        [int]$Attempts = 3
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        & $FilePath @Arguments
        if ($LASTEXITCODE -eq 0) { return }
        if ($attempt -eq $Attempts) { throw "$Description failed after $Attempts attempts (exit code $LASTEXITCODE)." }
        Start-Sleep -Milliseconds (500 * $attempt)
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
$gradlePath = Join-Path $AndroidRoot 'app\build.gradle.kts'
$gradleText = Get-Content -LiteralPath $gradlePath -Raw
$versionCodeMatch = [Regex]::Match($gradleText, 'getProperty\("tauri\.android\.versionCode",\s*"(\d+)"\)')
if (-not $versionCodeMatch.Success) { throw "Unable to read Android versionCode from $gradlePath" }
$versionCode = $versionCodeMatch.Groups[1].Value
$apkName = "Sunday-mobile_$version.apk"
$expectedAppLabel = 'Sunday'

$secret = Ensure-ReleaseCredentials
$previousJavaHome = [Environment]::GetEnvironmentVariable('JAVA_HOME', 'Process')
$previousPath = [Environment]::GetEnvironmentVariable('Path', 'Process')
$previousAndroidHome = [Environment]::GetEnvironmentVariable('ANDROID_HOME', 'Process')
$previousNdkHome = [Environment]::GetEnvironmentVariable('NDK_HOME', 'Process')
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
    $env:ANDROID_HOME = $AndroidSdkRoot
    $env:NDK_HOME = Join-Path $AndroidSdkRoot 'ndk\28.2.13676358'

    # Tauri leaves previously built emulator ABIs in the generated jniLibs
    # directory. Gradle would silently include those stale libraries in the
    # next universal APK even when only physical-device targets were requested.
    $jniLibsRoot = [IO.Path]::GetFullPath((Join-Path $AndroidRoot 'app\src\main\jniLibs'))
    foreach ($abi in @('x86', 'x86_64')) {
        $staleAbiRoot = [IO.Path]::GetFullPath((Join-Path $jniLibsRoot $abi))
        if (-not $staleAbiRoot.StartsWith($jniLibsRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean an Android ABI outside jniLibs: $staleAbiRoot"
        }
        if ([IO.Directory]::Exists($staleAbiRoot)) {
            [IO.Directory]::Delete($staleAbiRoot, $true)
        }
    }

    Push-Location $MobileRoot
    try {
        # Keep the generated Tauri Android shell aligned with the checked-in
        # launcher assets, including adaptive foreground/background resources.
        Invoke-Checked -FilePath 'powershell.exe' -Arguments @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $MobileRoot 'scripts\prepare-tauri-android-icons.ps1')
        ) -Description 'Android launcher icon synchronization'

        # Tauri owns the Android shell and embeds the shared Rust Agent core.
        # Build the two physical-device ABIs into one signed universal APK.
        Invoke-Checked -FilePath 'npm.cmd' -Arguments @(
            'run', 'tauri', '--', 'android', 'build', '--apk', '--target', 'aarch64', 'armv7', '--ci'
        ) -Description 'Tauri Android release build'
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in $signingNames) {
        [Environment]::SetEnvironmentVariable($name, $previousSigning[$name], 'Process')
    }
    [Environment]::SetEnvironmentVariable('JAVA_HOME', $previousJavaHome, 'Process')
    [Environment]::SetEnvironmentVariable('Path', $previousPath, 'Process')
    [Environment]::SetEnvironmentVariable('ANDROID_HOME', $previousAndroidHome, 'Process')
    [Environment]::SetEnvironmentVariable('NDK_HOME', $previousNdkHome, 'Process')
}

$builtApk = Join-Path $AndroidRoot 'app\build\outputs\apk\universal\release\app-universal-release.apk'
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
        Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName 'apksigner.bat') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName 'aapt.exe') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName 'zipalign.exe') -PathType Leaf)
        }
    $buildToolsDir = $buildTools | Select-Object -First 1
    if (-not $buildToolsDir) { throw "Android build-tools with apksigner.bat were not found under $buildToolsRoot" }
    $apksigner = Join-Path $buildToolsDir.FullName 'apksigner.bat'
    $aapt = Join-Path $buildToolsDir.FullName 'aapt.exe'
    $zipalign = Join-Path $buildToolsDir.FullName 'zipalign.exe'

    $signatureOutput = @(& $apksigner verify --verbose --print-certs $outputApk 2>&1)
    if ($LASTEXITCODE -ne 0 -or -not ($signatureOutput -match 'Verifies')) {
        throw "apksigner verification failed for $outputApk"
    }
    if (-not ($signatureOutput -match 'Number of signers:\s+1')) {
        throw "Unexpected signer count in $outputApk"
    }
    $packageOutput = @(& $aapt dump badging $outputApk 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect APK metadata: $outputApk" }
    $packageLine = $packageOutput | Select-String "^package:.*versionCode='(\d+)'.*versionName='$version'"
    if (-not $packageLine) {
        throw "APK metadata does not match package version $version"
    }
    $versionCode = [Regex]::Match($packageLine.Line, "versionCode='(\d+)'").Groups[1].Value
    if ([int]$versionCode -le 33) { throw "Tauri APK versionCode $versionCode cannot upgrade the published Capacitor APK (33)." }
    $versionParts = [Regex]::Match($version, '^(\d+)\.(\d+)\.(\d+)')
    $expectedVersionCode = [int]$versionParts.Groups[1].Value * 1000000 + [int]$versionParts.Groups[2].Value * 1000 + [int]$versionParts.Groups[3].Value
    if ([int]$versionCode -ne $expectedVersionCode) {
        throw "APK versionCode $versionCode does not match package version $version (expected $expectedVersionCode)."
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

    $resourceDump = @(& $aapt dump --values resources $outputApk 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect APK launcher resources: $outputApk" }
    $resourceText = $resourceDump -join "`n"
    $adaptiveIconLine = $packageOutput | Select-String "^application-icon-640:'(res/[^']+\.xml)'$" | Select-Object -First 1
    if (-not $adaptiveIconLine) { throw 'Release APK does not select an adaptive launcher icon' }
    $adaptiveIconPath = [Regex]::Match($adaptiveIconLine.Line, "^application-icon-640:'([^']+)'$").Groups[1].Value
    $adaptiveIconTree = @(& $aapt dump xmltree $outputApk $adaptiveIconPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or -not ($adaptiveIconTree -match 'E: adaptive-icon') -or
        -not ($adaptiveIconTree -match 'E: foreground') -or -not ($adaptiveIconTree -match 'E: background')) {
        throw 'Release APK adaptive launcher icon is incomplete'
    }
    $canonicalBackground = [xml](Get-Content -LiteralPath (Join-Path $MobileRoot 'src-tauri\icons\android\values\ic_launcher_background.xml') -Raw)
    $backgroundColor = [string]$canonicalBackground.resources.color.'#text'
    if ($backgroundColor -notmatch '^#[0-9a-fA-F]{6}$') { throw 'Canonical launcher background must be an opaque RGB color' }
    $expectedArgb = 'ff' + $backgroundColor.Substring(1)
    if ($resourceText -notmatch "(?i)color/ic_launcher_background: t=0x1d d=0x$expectedArgb\b") {
        throw 'Release APK adaptive launcher background does not match the canonical icon'
    }

    # Android 15+ devices with a 16 KiB page size require both APK entry
    # alignment and 16 KiB-aligned LOAD segments in 64-bit native libraries.
    & $zipalign -c -P 16 -v 4 $outputApk *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "APK is not zip-aligned for 16 KiB pages: $outputApk"
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($outputApk)
    $arm64Entry = $null
    try {
        Add-Type -AssemblyName System.Drawing
        $launcherBlock = [Regex]::Match(
            $resourceText,
            '(?ms)^\s*spec resource [^\r\n]*:mipmap/ic_launcher:[^\r\n]*\r?\n(?<block>.*?)(?=^\s*type \d+ )'
        ).Groups['block'].Value
        $xxxhdpiBlock = [Regex]::Match(
            $launcherBlock,
            '(?ms)^\s*config xxxhdpi:\r?\n(?<block>.*?)(?=^\s*config |^\s*type \d+ |\z)'
        ).Groups['block'].Value
        if (-not $xxxhdpiBlock) { throw 'Unable to resolve xxxhdpi launcher resources from APK' }
        foreach ($iconName in @('ic_launcher', 'ic_launcher_foreground')) {
            $pattern = '(?m)^\s*resource[^\r\n]*:mipmap/' + [Regex]::Escape($iconName) + ':[^\r\n]*\r?\n\s*\(string8\) "([^"]+)"'
            $iconMatch = [Regex]::Match($xxxhdpiBlock, $pattern)
            if (-not $iconMatch.Success) { throw "Unable to resolve APK launcher resource $iconName" }
            $iconEntry = $archive.GetEntry($iconMatch.Groups[1].Value)
            if (-not $iconEntry) { throw "APK launcher resource $iconName is missing" }
            $canonicalPath = Join-Path $MobileRoot "src-tauri\icons\android\mipmap-xxxhdpi\$iconName.png"
            $iconBytes = New-Object IO.MemoryStream
            $entryStream = $iconEntry.Open()
            try { $entryStream.CopyTo($iconBytes) } finally { $entryStream.Dispose() }
            $iconBytes.Position = 0
            $apkIcon = [Drawing.Bitmap]::new($iconBytes)
            $canonicalIcon = [Drawing.Bitmap]::new($canonicalPath)
            try {
                if ($apkIcon.Width -ne $canonicalIcon.Width -or $apkIcon.Height -ne $canonicalIcon.Height) {
                    throw "APK launcher $iconName dimensions do not match the canonical icon"
                }
                for ($y = 0; $y -lt $apkIcon.Height; $y++) {
                    for ($x = 0; $x -lt $apkIcon.Width; $x++) {
                        if ($apkIcon.GetPixel($x, $y).ToArgb() -ne $canonicalIcon.GetPixel($x, $y).ToArgb()) {
                            throw "APK launcher $iconName pixels do not match the canonical icon"
                        }
                    }
                }
            } finally {
                $canonicalIcon.Dispose()
                $apkIcon.Dispose()
                $iconBytes.Dispose()
            }
        }
        $appLibraries = @(
            $archive.Entries |
                Where-Object { $_.FullName -match '^lib/[^/]+/libsunday_mobile_lib\.so$' } |
                ForEach-Object { $_.FullName }
        )
        $expectedLibraries = @(
            'lib/arm64-v8a/libsunday_mobile_lib.so',
            'lib/armeabi-v7a/libsunday_mobile_lib.so'
        )
        $unexpectedLibraries = @($appLibraries | Where-Object { $_ -notin $expectedLibraries })
        $missingLibraries = @($expectedLibraries | Where-Object { $_ -notin $appLibraries })
        if ($unexpectedLibraries.Count -gt 0 -or $missingLibraries.Count -gt 0 -or $appLibraries.Count -ne 2) {
            throw "APK ABI set is invalid. Expected arm64-v8a and armeabi-v7a only; found: $($appLibraries -join ', ')"
        }
        $arm64Entry = $archive.Entries |
            Where-Object { $_.FullName -eq 'lib/arm64-v8a/libsunday_mobile_lib.so' } |
            Select-Object -First 1
        if (-not $arm64Entry) { throw 'arm64-v8a application library is missing from the APK' }

        $elfCheckRoot = Join-Path ([IO.Path]::GetTempPath()) ("lamtools-mobile-elf-$([Guid]::NewGuid().ToString('N'))")
        New-Item -ItemType Directory -Path $elfCheckRoot | Out-Null
        $arm64Library = Join-Path $elfCheckRoot 'libsunday_mobile_lib.so'
        try {
            $sourceStream = $arm64Entry.Open()
            try {
                $destinationStream = [IO.File]::Create($arm64Library)
                try { $sourceStream.CopyTo($destinationStream) } finally { $destinationStream.Dispose() }
            } finally {
                $sourceStream.Dispose()
            }

            $readElf = Join-Path $AndroidSdkRoot 'ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-readelf.exe'
            if (-not (Test-Path -LiteralPath $readElf -PathType Leaf)) {
                throw "llvm-readelf.exe was not found: $readElf"
            }
            $programHeaders = @(& $readElf -lW $arm64Library 2>&1)
            if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect arm64 ELF program headers' }
            $loadAlignments = @(
                $programHeaders |
                    Where-Object { $_ -match '^\s*LOAD\s' } |
                    ForEach-Object {
                        $match = [Regex]::Match($_, '(0x[0-9a-fA-F]+)\s*$')
                        if ($match.Success) { $match.Groups[1].Value.ToLowerInvariant() }
                    }
            )
            if ($loadAlignments.Count -eq 0 -or @($loadAlignments | Where-Object { $_ -ne '0x4000' }).Count -gt 0) {
                throw "arm64 ELF LOAD segments are not all 16 KiB aligned: $($loadAlignments -join ', ')"
            }
        } finally {
            if (Test-Path -LiteralPath $arm64Library -PathType Leaf) {
                Remove-Item -LiteralPath $arm64Library -Force
            }
            if (Test-Path -LiteralPath $elfCheckRoot -PathType Container) {
                Remove-Item -LiteralPath $elfCheckRoot -Force
            }
        }
    } finally {
        $archive.Dispose()
    }

    $size = (Get-Item -LiteralPath $outputApk).Length
    $sha256 = (Get-FileHash -LiteralPath $outputApk -Algorithm SHA256).Hash
    Write-Host ''
    Write-Host '=== Signed Android release complete ===' -ForegroundColor Green
    Write-Host "APK:       $outputApk"
    Write-Host "Version:   $version (versionCode $versionCode)"
    Write-Host "Label:     $expectedAppLabel (non-debuggable, non-testOnly)"
    Write-Host 'ABIs:      arm64-v8a, armeabi-v7a'
    Write-Host '16KiB:     zipalign and arm64 ELF LOAD segments verified'
    Write-Host 'Icon:      adaptive background and launcher PNG pixels verified'
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
