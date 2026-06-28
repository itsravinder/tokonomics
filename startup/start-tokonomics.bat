@echo off
REM ============================================================
REM  Start Tokonomics  (canonical launcher)
REM    backend : python -m tokonomics
REM      dashboard -> http://127.0.0.1:8765
REM      proxy     -> http://127.0.0.1:8788  (ANTHROPIC_BASE_URL)
REM  Starts the backend minimized (logs to %TEMP%\tokonomics.log),
REM  waits until the dashboard is ready, then opens it in the browser.
REM ============================================================
cd /d "%~dp0.."

REM 1) Start the backend (dashboard + proxy) minimized, logging output
start "Tokonomics" /min cmd /c "python -m tokonomics >> ""%TEMP%\tokonomics.log"" 2>&1"

REM 2) Wait (up to ~15s) until the dashboard answers on :8765
powershell -NoProfile -Command "for($i=0;$i -lt 30;$i++){try{if((Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/ -TimeoutSec 2).StatusCode -eq 200){break}}catch{}; Start-Sleep -Milliseconds 500}"

REM 3) Open the dashboard in the default browser
start "" "http://127.0.0.1:8765/"
