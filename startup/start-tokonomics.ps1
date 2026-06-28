# ============================================================
#  Start Tokonomics  (canonical launcher)
#    backend : python -m tokonomics
#      dashboard -> http://127.0.0.1:8765
#      proxy     -> http://127.0.0.1:8788  (ANTHROPIC_BASE_URL)
#  Starts the backend minimized (logs to %TEMP%\tokonomics.log),
#  waits until the dashboard is ready, then opens it in the browser.
# ============================================================
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$out = Join-Path $env:TEMP 'tokonomics.log'
$err = Join-Path $env:TEMP 'tokonomics.err.log'
$url = 'http://127.0.0.1:8765/'

# 1) Start the backend (dashboard + proxy) minimized, logging output
Start-Process -FilePath 'python' -ArgumentList '-m', 'tokonomics' `
    -WindowStyle Minimized -RedirectStandardOutput $out -RedirectStandardError $err

# 2) Wait (up to ~15s) until the dashboard responds
for ($i = 0; $i -lt 30; $i++) {
    try {
        if ((Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 2).StatusCode -eq 200) { break }
    } catch { }
    Start-Sleep -Milliseconds 500
}

# 3) Open the dashboard in the default browser
Start-Process $url
Write-Host "Tokonomics started -> $url  (log: $out)"
