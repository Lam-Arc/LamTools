# Quick design_architecture tool test
$sid = (Invoke-WebRequest -Uri http://localhost:6173/api/sessions -Method POST -ContentType 'application/json' -Body '{"title":"design-tool-test"}' -UseBasicParsing | ConvertFrom-Json).id
Write-Host "Session: $sid"

$body = @{message = "开发一个食谱管理Web应用，前端Vue3，后端Python FastAPI，数据库SQLite。用户可以浏览食谱、搜索、按分类筛选、添加收藏。"} | ConvertTo-Json -Compress

$url = "http://localhost:6173/api/sessions/$sid/chat"
$req = [System.Net.HttpWebRequest]::Create($url)
$req.Method = "POST"
$req.ContentType = "application/json"
$req.Accept = "text/event-stream"
$req.ReadWriteTimeout = 600000
$req.Timeout = 600000
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
$req.ContentLength = $bytes.Length
$stream = $req.GetRequestStream()
$stream.Write($bytes, 0, $bytes.Length)
$stream.Close()

$resp = $req.GetResponse()
$rdr = New-Object System.IO.StreamReader($resp.GetResponseStream())

$start = Get-Date
$keyEvents = @()
while ($true) {
    if ($rdr.EndOfStream) { break }
    $line = $rdr.ReadLine()
    if ($line -eq $null) { Start-Sleep -Milliseconds 100; continue }
    if ($line.StartsWith("event: ")) {
        $evt = $line.Substring(7).Trim()
        if ($evt -notmatch "ping") { $keyEvents += $evt }
    }
    if ($line -match "design_architecture") {
        Write-Host ">>> DESIGN_ARCHITECTURE CALLED!" -ForegroundColor Green
    }
    if ($line -match "DESIGN PIPELINE COMPLETE") {
        Write-Host ">>> DESIGN PIPELINE COMPLETE" -ForegroundColor Green
    }
    Write-Host $line
    if ($line -match "writer_done" -or $line -match "writer_error") { break }
    if (((Get-Date) - $start).TotalSeconds -gt 600) { Write-Host "TIMEOUT (10min)"; break }
}
$rdr.Close(); $resp.Close()
Write-Host "`nKey events: $($keyEvents | Select-Object -Unique)"
