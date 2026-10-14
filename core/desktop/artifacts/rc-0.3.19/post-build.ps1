$ErrorActionPreference = 'Stop'
$Root = 'E:\LamTools'
$Evidence = Join-Path $Root 'core\desktop\artifacts\rc-0.3.19'
$deadline = (Get-Date).AddMinutes(35)
while (-not (Test-Path -LiteralPath "$Evidence\package.exit.txt")) {
    if ((Get-Date) -gt $deadline) { throw 'Production build did not finish within acceptance wait budget' }
    Start-Sleep -Seconds 5
}
if ((Get-Content -LiteralPath "$Evidence\package.exit.txt" -Raw).Trim() -ne '0') { throw 'Production build failed; inspect package.log' }
$Setup = Join-Path $Root 'core\desktop\src-tauri\target\release\bundle\inno\Sunday_0.3.19_x64-setup.exe'
if (-not (Test-Path -LiteralPath $Setup)) { throw 'Matching candidate installer missing' }
Get-FileHash -LiteralPath $Setup -Algorithm SHA256 | ConvertTo-Json | Set-Content "$Evidence\installer-hash.json" -Encoding UTF8
Copy-Item -LiteralPath $Setup -Destination "$Evidence\Sunday_0.3.19_x64-setup.exe"
& "$Root\.agents\skills\lamtools-setup-install\scripts\install_setup.ps1" -Version '0.3.19' -StartupTimeoutSeconds 120 *> "$Evidence\installed-startup.log"
$IsolatedInstall = [IO.Path]::GetFullPath('E:\setuptest\0.3.19')
if (-not $IsolatedInstall.StartsWith('E:\setuptest\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe isolated installation path' }
Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($IsolatedInstall + '\', [StringComparison]::OrdinalIgnoreCase)
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
& "$Root\scripts\verify-desktop-lifecycle.ps1" -Installer $Setup -WorkRoot 'E:\setuptest\rc-0.3.19-lifecycle' *> "$Evidence\installer-lifecycle.log"
'passed' | Set-Content "$Evidence\post-build-result.txt"
