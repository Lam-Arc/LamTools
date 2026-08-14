<#
.SYNOPSIS
  Bump the LamCore version across all version-bearing files (single source of truth).

.DESCRIPTION
  Usage:
    .\scripts\bump-version.ps1 0.3.0

  Updates 5 places so the desktop app, the Rust shell, the packaged backend and
  the update check (`update.check` compares GitHub Releases against
  lamtools_core.__version__) all agree on one version:

    1. core/desktop/src-tauri/tauri.conf.json    (app bundle version)
    2. core/desktop/src-tauri/Cargo.toml         (Rust package version)
    3. core/desktop/package.json                 (desktop frontend version)
    4. core/pyproject.toml                       (Python package version)
    5. core/src/lamtools_core/__init__.py        (runtime __version__ used by update.check)

  After bumping, commit and push a tag `v<version>` — .github/workflows/release.yml
  then builds and publishes the installer automatically.
#>
param([Parameter(Mandatory = $true)][string]$NewVersion)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

if ($NewVersion -notmatch '^\d+\.\d+\.\d+$') {
    Write-Host "[FAIL] Version must be x.y.z (e.g. 0.3.0), got: $NewVersion" -ForegroundColor Red
    exit 1
}

function Set-ContentUtf8NoBom([string]$Path, [string]$Content) {
    # Keep files BOM-less UTF-8 (PowerShell 5 default would add a BOM).
    [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

function Update-File([string]$Path, [string]$Pattern, [string]$Replacement) {
    if (-not (Test-Path $Path)) {
        Write-Host "[SKIP] not found: $Path" -ForegroundColor Yellow
        return $false
    }
    $Content = [System.IO.File]::ReadAllText($Path)
    if ($Content -notmatch $Pattern) {
        Write-Host "[SKIP] pattern not found in $Path" -ForegroundColor Yellow
        return $false
    }
    $Updated = [System.Text.RegularExpressions.Regex]::Replace($Content, $Pattern, $Replacement)
    Set-ContentUtf8NoBom $Path $Updated
    Write-Host "  $Path -> $NewVersion" -ForegroundColor Green
    return $true
}

Write-Host "=== Bump version to $NewVersion ===" -ForegroundColor Cyan

$Failed = 0

# 1. tauri.conf.json — "version": "0.2.2"
if (-not (Update-File "$Root\core\desktop\src-tauri\tauri.conf.json" '"version"\s*:\s*"[^"]+"' "`"version`": `"$NewVersion`"")) { $Failed++ }

# 2. Cargo.toml — version = "0.2.2" (package section, line-start anchored)
if (-not (Update-File "$Root\core\desktop\src-tauri\Cargo.toml" '(?m)^version = "[^"]+"' "version = `"$NewVersion`"")) { $Failed++ }

# 3. desktop package.json — "version": "0.2.2"
if (-not (Update-File "$Root\core\desktop\package.json" '"version"\s*:\s*"[^"]+"' "`"version`": `"$NewVersion`"")) { $Failed++ }

# 4. pyproject.toml — version = "0.2.2"
if (-not (Update-File "$Root\core\pyproject.toml" '(?m)^version = "[^"]+"' "version = `"$NewVersion`"")) { $Failed++ }

# 5. lamtools_core/__init__.py — __version__ = "0.2.2"
if (-not (Update-File "$Root\core\src\lamtools_core\__init__.py" '(?m)^__version__ = "[^"]+"' "__version__ = `"$NewVersion`"")) { $Failed++ }

# Final assertion: every one of the 5 files must now carry the new version.
# A silent [SKIP] used to let versions drift while the script printed
# "=== Done ===" and exited 0 (audit 14 S3 — same root cause as the
# release.yml tag-mismatch guard).
foreach ($Check in @(
    @{ Path = "$Root\core\desktop\src-tauri\tauri.conf.json"; Pattern = '"version"\s*:\s*"([^"]+)"' },
    @{ Path = "$Root\core\desktop\src-tauri\Cargo.toml"; Pattern = '(?m)^version = "([^"]+)"' },
    @{ Path = "$Root\core\desktop\package.json"; Pattern = '"version"\s*:\s*"([^"]+)"' },
    @{ Path = "$Root\core\pyproject.toml"; Pattern = '(?m)^version = "([^"]+)"' },
    @{ Path = "$Root\core\src\lamtools_core\__init__.py"; Pattern = '(?m)^__version__ = "([^"]+)"' }
)) {
    $Content = [System.IO.File]::ReadAllText($Check.Path)
    $Match = [System.Text.RegularExpressions.Regex]::Match($Content, $Check.Pattern)
    if (-not $Match.Success -or $Match.Groups[1].Value -ne $NewVersion) {
        Write-Host "[FAIL] final check: $($Check.Path) is not at $NewVersion" -ForegroundColor Red
        $Failed++
    }
}

if ($Failed -gt 0) {
    Write-Host ""
    Write-Host "[FAIL] $Failed version location(s) failed to sync — fix and re-run." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Done. Next steps ===" -ForegroundColor Cyan
Write-Host "  1. Review:  git diff"
Write-Host "  2. Commit:  git commit -am \"chore: bump version to $NewVersion\""
Write-Host "  3. Release: git tag v$NewVersion && git push origin main --tags"
Write-Host "     (release.yml 会自动校验 tag 与 5 处版本号一致后构建发布)"

