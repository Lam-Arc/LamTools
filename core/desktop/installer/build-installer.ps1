<#
.SYNOPSIS
  Compile the repository-owned Sunday Windows installer with Inno Setup.
.DESCRIPTION
  The source directory must contain lamcore.exe and lamcore-backend\LamCore.exe.
  Inno Setup can be supplied explicitly, through INNO_SETUP_ISCC, or installed
  in one of its standard machine/current-user locations.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [string]$IsccPath,
    [string]$IconPath,
    [string]$WebView2BootstrapperPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-AbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

function Resolve-IsccPath {
    param([AllowEmptyString()][string]$RequestedPath)

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        $candidates += $RequestedPath
    }
    if (-not [string]::IsNullOrWhiteSpace($env:INNO_SETUP_ISCC)) {
        $candidates += $env:INNO_SETUP_ISCC
    }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        $candidates += $command.Source
    }
    $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        $candidates += (Join-Path $programFilesX86 'Inno Setup 6\ISCC.exe')
    }
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        $absolute = Get-AbsolutePath $candidate
        if (Test-Path -LiteralPath $absolute -PathType Leaf) {
            return $absolute
        }
    }
    throw 'Inno Setup 6 compiler (ISCC.exe) was not found. Install Inno Setup 6 or pass -IsccPath.'
}

function Test-PeFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return ($stream.Length -gt 100KB) -and ($stream.ReadByte() -eq 0x4D) -and ($stream.ReadByte() -eq 0x5A)
    } finally {
        $stream.Dispose()
    }
}

if ($Version -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Invalid version '$Version'. Expected a semantic version such as 0.3.2."
}

$source = Get-AbsolutePath $SourceRoot
$output = Get-AbsolutePath $OutputDir
$scriptPath = Join-Path $PSScriptRoot 'Sunday.iss'
$repoRoot = Get-AbsolutePath (Join-Path $PSScriptRoot '..\..\..')
$icon = if ([string]::IsNullOrWhiteSpace($IconPath)) {
    Join-Path $repoRoot 'core\desktop\src-tauri\icons\icon.ico'
} else {
    Get-AbsolutePath $IconPath
}

$requiredFiles = @(
    (Join-Path $source 'lamcore.exe'),
    (Join-Path $source 'lamcore-backend\LamCore.exe'),
    $icon,
    $scriptPath
)
foreach ($requiredFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required installer input is missing: $requiredFile"
    }
}

$compiler = Resolve-IsccPath $IsccPath
New-Item -ItemType Directory -Path $output -Force | Out-Null

if ([string]::IsNullOrWhiteSpace($WebView2BootstrapperPath)) {
    $cacheDir = Join-Path (Split-Path -Parent $source) 'cache'
    New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
    $webView2 = Join-Path $cacheDir 'MicrosoftEdgeWebview2Setup.exe'
    if (-not (Test-PeFile $webView2)) {
        Write-Host 'Downloading the Microsoft Edge WebView2 evergreen bootstrapper...'
        Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $webView2
    }
} else {
    $webView2 = Get-AbsolutePath $WebView2BootstrapperPath
}
if (-not (Test-PeFile $webView2)) {
    throw "WebView2 bootstrapper is missing or invalid: $webView2"
}

$arguments = @(
    "/DAppVersion=$Version",
    "/DSourceDir=$source",
    "/DOutputDir=$output",
    "/DAppIcon=$icon",
    "/DWebView2Bootstrapper=$webView2",
    $scriptPath
)

Write-Host "Compiling Sunday installer with $compiler"
& $compiler @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compiler failed with exit code $LASTEXITCODE."
}

$installerPath = Join-Path $output "Sunday_${Version}_x64-setup.exe"
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Inno Setup completed without producing the expected installer: $installerPath"
}

[PSCustomObject]@{
    status = 'ok'
    version = $Version
    compiler = $compiler
    source_root = $source
    output_path = $installerPath
    size_bytes = (Get-Item -LiteralPath $installerPath).Length
} | ConvertTo-Json -Depth 2
