$ErrorActionPreference = 'Stop'
$taskEvidence = 'E:\LamTools\core\desktop\artifacts\rc-0.3.19'
$taskDeadline = (Get-Date).AddMinutes(25)
while (-not (Test-Path "$taskEvidence\package-accepted.exit.txt")) {
    if ((Get-Date) -gt $taskDeadline) { throw 'Build deadline exceeded' }
    Start-Sleep -Seconds 5
}
if ((Get-Content "$taskEvidence\package-accepted.exit.txt" -Raw).Trim() -ne '0') { throw 'Build failed' }
$taskSetup = 'E:\LamTools\core\desktop\src-tauri\target\release\bundle\inno\Sunday_0.3.19_x64-setup.exe'
Copy-Item -LiteralPath $taskSetup -Destination "$taskEvidence\Sunday_0.3.19_x64-setup.exe"
Get-FileHash -LiteralPath $taskSetup -Algorithm SHA256 | ConvertTo-Json | Set-Content "$taskEvidence\installer-hash.json" -Encoding UTF8
& 'E:\LamTools\.agents\skills\lamtools-setup-install\scripts\install_setup.ps1' -Version '0.3.19' -ForceCloseExisting *> "$taskEvidence\installed-startup-accepted.log"
$taskTarget = [IO.Path]::GetFullPath('E:\setuptest\0.3.19')
if (-not $taskTarget.StartsWith('E:\setuptest\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe process target' }
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($taskTarget + '\', [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
& powershell -NoProfile -File 'E:\LamTools\scripts\verify-desktop-lifecycle.ps1' -Installer $taskSetup -WorkRoot 'E:\setuptest\rc-0.3.19-lifecycle-accepted' *> "$taskEvidence\installer-lifecycle-accepted.log"
$LASTEXITCODE | Set-Content "$taskEvidence\installer-lifecycle-accepted.exit.txt"
if ($LASTEXITCODE -ne 0) { throw 'Lifecycle failed' }
& py -3.14 "$taskEvidence\accept-packaged.py" *> "$taskEvidence\packaged-upgrade-accepted.log"
$LASTEXITCODE | Set-Content "$taskEvidence\packaged-upgrade-accepted.exit.txt"
if ($LASTEXITCODE -ne 0) { throw 'Packaged upgrade acceptance failed' }
& py -3.14 "$taskEvidence\supplement-acceptance.py" *> "$taskEvidence\supplement-acceptance-accepted.log"
$LASTEXITCODE | Set-Content "$taskEvidence\supplement-acceptance-accepted.exit.txt"
if ($LASTEXITCODE -ne 0) { throw 'Supplement acceptance failed' }
& py -3.14 "$taskEvidence\audit-artifacts.py" *> "$taskEvidence\artifact-audit-accepted.log"
$LASTEXITCODE | Set-Content "$taskEvidence\artifact-audit-accepted.exit.txt"
if ($LASTEXITCODE -ne 0) { throw 'Artifact audit failed' }
'passed' | Set-Content "$taskEvidence\acceptance-result.txt"
