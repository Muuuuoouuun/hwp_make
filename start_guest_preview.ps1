$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:HWP_WEB_ORIGIN = 'http://127.0.0.5:18913'
$env:HWP_WEB_AUTH_COOKIE = 'hwp_academy_latest_session'
$env:HWP_WEB_DATA_DIR = Join-Path $PSScriptRoot 'data\academy-batch-latest'
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m uvicorn app.web_main:app --host 127.0.0.5 --port 18913
exit $LASTEXITCODE
