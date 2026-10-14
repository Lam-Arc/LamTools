$taskTokens = $null
$taskErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile('E:\LamTools\scripts\verify-desktop-lifecycle.ps1', [ref]$taskTokens, [ref]$taskErrors) | Out-Null
if ($taskErrors.Count -gt 0) { $taskErrors | Out-String | Write-Output; exit 1 }
Write-Output 'PASS: Windows PowerShell 5 parses installer lifecycle script'
