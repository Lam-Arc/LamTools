$ErrorActionPreference = 'Stop'
$taskEvidence = 'E:\LamTools\core\desktop\artifacts\rc-0.3.19\task-3b'
$taskDeadline = (Get-Date).AddMinutes(15)
while (-not (Test-Path "$taskEvidence\package-final.exit.txt")) {
    if ((Get-Date) -gt $taskDeadline) { throw 'Build deadline exceeded' }
    Start-Sleep -Seconds 5
}
if ((Get-Content "$taskEvidence\package-final.exit.txt" -Raw).Trim() -ne '0') { throw 'Build failed' }
$taskSetup = 'E:\LamTools\core\desktop\src-tauri\target\release\bundle\inno\Sunday_0.3.19_x64-setup.exe'
Copy-Item -LiteralPath $taskSetup -Destination "$taskEvidence\Sunday_0.3.19_x64-setup.exe"
Get-FileHash -LiteralPath $taskSetup -Algorithm SHA256 | ConvertTo-Json | Set-Content "$taskEvidence\installer-hash.json" -Encoding UTF8
$taskProcess = Start-Process -FilePath $taskSetup -WindowStyle Hidden -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/DIR=E:\setuptest\0.3.19',"/LOG=$taskEvidence\installed-final.log" -Wait -PassThru
$taskProcess.ExitCode | Set-Content "$taskEvidence\install-final.exit.txt"
if ($taskProcess.ExitCode -ne 0) { throw 'Installation failed' }
# Do not launch the main app while the user's dev instance holds its mutex.
& py -3.14 "$taskEvidence\accept-packaged.py" *> "$taskEvidence\packaged-acceptance-final.log"
$LASTEXITCODE | Set-Content "$taskEvidence\packaged-acceptance-final.exit.txt"
if ($LASTEXITCODE -ne 0) { throw 'Packaged acceptance failed' }
'passed; Tauri main-app launch/user acceptance pending' | Set-Content "$taskEvidence\acceptance-result.txt"
