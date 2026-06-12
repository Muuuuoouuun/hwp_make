$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BundledPython = "C:\Users\aaaha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Test-Path $BundledPython) {
  $Python = $BundledPython
} else {
  $Python = "python"
}

Set-Location $ProjectRoot
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8787

