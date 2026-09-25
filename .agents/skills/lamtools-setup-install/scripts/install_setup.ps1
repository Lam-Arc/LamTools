<#
.SYNOPSIS
  Install and launch a Sunday Inno Setup build for local verification.

.DESCRIPTION
  Finds Sunday_<version>_x64-setup.exe, installs it into the versioned
  E:\setuptest\<version> directory, launches lamcore.exe, and verifies that
  both the desktop process and its bundled backend run from that directory.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Version,

    [string]$SetupPath,

    [string]$InstallRoot = 'E:\setuptest',

    [switch]$ForceCloseExisting,

    [ValidateRange(5, 120)]
    [int]$StartupTimeoutSeconds = 20
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Normalize-Version {
    param([AllowNull()][string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    $normalized = $Value.Trim()
    if ($normalized.StartsWith('v', [System.StringComparison]::OrdinalIgnoreCase)) {
        $normalized = $normalized.Substring(1)
    }

    if ($normalized -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
        throw "Invalid version '$Value'. Expected a semantic version such as 0.2.9."
    }

    return $normalized
}

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

function Test-SamePath {
    param(
        [AllowNull()][string]$Left,
        [AllowNull()][string]$Right
    )

    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) {
        return $false
    }

    return [string]::Equals((Get-FullPath $Left), (Get-FullPath $Right), [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-ProcessSnapshot {
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ExecutablePath })
}

$repoRoot = Get-FullPath (Join-Path $PSScriptRoot '..\..\..\..')
$requestedVersion = Normalize-Version $Version
$setupFile = $null

if (-not [string]::IsNullOrWhiteSpace($SetupPath)) {
    $setupCandidate = Get-FullPath $SetupPath
    if (-not (Test-Path -LiteralPath $setupCandidate -PathType Leaf)) {
        throw "Setup file not found: $setupCandidate"
    }

    $setupFile = Get-Item -LiteralPath $setupCandidate
} else {
    $searchDirectories = @(
        (Join-Path $repoRoot 'core\desktop\src-tauri\target\release\bundle\inno'),
        (Join-Path $repoRoot 'dist'),
        (Join-Path $repoRoot 'dist-plugins')
    ) | Select-Object -Unique

    $matches = @()
    if ($null -ne $requestedVersion) {
        $expectedName = "Sunday_${requestedVersion}_x64-setup.exe"
        foreach ($directory in $searchDirectories) {
            if (Test-Path -LiteralPath $directory -PathType Container) {
                $matches += @(Get-ChildItem -LiteralPath $directory -File -Filter $expectedName -ErrorAction SilentlyContinue)
            }
        }
    } else {
        foreach ($directory in $searchDirectories) {
            if (Test-Path -LiteralPath $directory -PathType Container) {
                $matches += @(
                    Get-ChildItem -LiteralPath $directory -File -Filter 'Sunday_*_x64-setup.exe' -ErrorAction SilentlyContinue |
                        Where-Object { $_.Name -match '^Sunday_\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?_x64-setup\.exe$' }
                )
            }
        }
    }

    if ($matches.Count -eq 0) {
        $where = ($searchDirectories -join '; ')
        throw "No matching Sunday setup package found. Searched: $where"
    }

    $setupFile = @($matches | Sort-Object LastWriteTime -Descending)[0]
}

$nameMatch = [regex]::Match(
    $setupFile.Name,
    '^Sunday_(?<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)_x64-setup\.exe$'
)

if (-not $nameMatch.Success) {
    if ($null -eq $requestedVersion) {
        throw "Cannot determine the version from setup filename: $($setupFile.FullName)"
    }

    $packageVersion = $requestedVersion
} else {
    $packageVersion = $nameMatch.Groups['version'].Value
}

if ($null -ne $requestedVersion -and $packageVersion -ne $requestedVersion) {
    throw "Setup version mismatch. Requested $requestedVersion but found $packageVersion in $($setupFile.FullName)"
}

$installRootPath = Get-FullPath $InstallRoot
$destination = [System.IO.Path]::GetFullPath((Join-Path $installRootPath $packageVersion))
$destinationLeaf = [System.IO.Path]::GetFileName($destination.TrimEnd('\'))
$destinationRoot = [System.IO.Path]::GetPathRoot($destination)

if ($destinationLeaf -ne $packageVersion -or $destination.TrimEnd('\') -ieq $destinationRoot.TrimEnd('\')) {
    throw "Refusing unsafe install destination: $destination"
}

New-Item -ItemType Directory -Path $installRootPath -Force | Out-Null

$appPath = [System.IO.Path]::GetFullPath((Join-Path $destination 'lamcore.exe'))
$backendPath = [System.IO.Path]::GetFullPath((Join-Path $destination 'lamcore-backend\LamCore.exe'))
$destinationPrefix = $destination.TrimEnd('\') + '\'
$existingProcesses = @(
    Get-ProcessSnapshot |
        Where-Object { $_.ExecutablePath.StartsWith($destinationPrefix, [System.StringComparison]::OrdinalIgnoreCase) }
)

if ($existingProcesses.Count -gt 0) {
    if (-not $ForceCloseExisting) {
        $ids = ($existingProcesses | ForEach-Object { $_.ProcessId }) -join ', '
        throw "Processes already run from $destination (PID: $ids). Re-run with -ForceCloseExisting to replace this test install."
    }

    foreach ($process in $existingProcesses) {
        Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction Stop
    }

    Start-Sleep -Milliseconds 500
}

Write-Host "Installing $($setupFile.FullName)"
Write-Host "Destination: $destination"
$installerArguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="{0}"' -f $destination
$installerProcess = Start-Process -FilePath $setupFile.FullName -ArgumentList $installerArguments -Wait -PassThru
if ($installerProcess.ExitCode -ne 0) {
    throw "Installer failed with exit code $($installerProcess.ExitCode): $($setupFile.FullName)"
}

if (-not (Test-Path -LiteralPath $appPath -PathType Leaf)) {
    throw "Installed application was not found: $appPath"
}

if (-not (Test-Path -LiteralPath $backendPath -PathType Leaf)) {
    throw "Installed backend was not found: $backendPath"
}

$launchedProcess = Start-Process -FilePath $appPath -WorkingDirectory $destination -PassThru
$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
$mainProcess = $null
$backendProcesses = @()

do {
    Start-Sleep -Milliseconds 500
    $snapshot = Get-ProcessSnapshot
    $mainProcess = @($snapshot | Where-Object { Test-SamePath $_.ExecutablePath $appPath } | Select-Object -First 1)
    $backendProcesses = @($snapshot | Where-Object { Test-SamePath $_.ExecutablePath $backendPath })

    if ($mainProcess.Count -gt 0 -and $backendProcesses.Count -gt 0) {
        break
    }
} while ((Get-Date) -lt $deadline)

if ($mainProcess.Count -eq 0) {
    throw "lamcore.exe did not remain running within ${StartupTimeoutSeconds}s (initial PID $($launchedProcess.Id))."
}

if ($backendProcesses.Count -eq 0) {
    throw "LamCore backend did not start within ${StartupTimeoutSeconds}s: $backendPath"
}

$fileVersion = (Get-Item -LiteralPath $appPath).VersionInfo.ProductVersion
[PSCustomObject]@{
    status = 'ok'
    version = $packageVersion
    setup_path = $setupFile.FullName
    install_directory = $destination
    app_path = $appPath
    app_file_version = $fileVersion
    main_process_id = [int]$mainProcess[0].ProcessId
    backend_process_ids = @($backendProcesses | ForEach-Object { [int]$_.ProcessId })
} | ConvertTo-Json -Depth 3
