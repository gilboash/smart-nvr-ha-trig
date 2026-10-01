$env:PATH = "C:\smart-nvr\bin;" + $env:PATH
Set-Location C:\smart-nvr

$logDir = "C:\smart-nvr\data\logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

while ($true) {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $logFile = Join-Path $logDir "snvr_$ts.log"

    & ".\venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 7070 *> $logFile
    $exitCode = $LASTEXITCODE

    # Keep at most the 20 most recent run logs
    Get-ChildItem $logDir -Filter "snvr_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 20 | Remove-Item -Force -ErrorAction SilentlyContinue

    Add-Content -Path (Join-Path $logDir "supervisor.log") -Value "$(Get-Date -Format o) app exited with code $exitCode, restarting in 5s"
    Start-Sleep -Seconds 5
}
