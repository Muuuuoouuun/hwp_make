param([string]$Python = "python", [string]$Iscc = "", [switch]$SkipDependencies)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot
$BuildRoot = Join-Path $ProjectRoot "tmp\desktop-build"
$VenvPython = Join-Path $BuildRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $Python -m venv (Join-Path $BuildRoot "venv")
    if ($LASTEXITCODE -ne 0) { throw "Build environment creation failed" }
}
if (-not $SkipDependencies) {
    & $VenvPython -m pip install -r requirements.lock.txt pyinstaller==6.19.0
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
}
if (-not $Iscc) {
    $Candidates = @((Join-Path $BuildRoot "tools\inno\ISCC.exe"), "C:\Program Files (x86)\Inno Setup 6\ISCC.exe", "C:\Program Files\Inno Setup 6\ISCC.exe")
    $Iscc = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "Inno Setup compiler required. Pass -Iscc with its ISCC.exe path." }
$env:PYTHONIOENCODING = "utf-8"
& $VenvPython scripts/prepare_desktop_build.py
if ($LASTEXITCODE -ne 0) { throw "Build assets failed" }
& $VenvPython -m PyInstaller --noconfirm --distpath dist --workpath tmp/desktop-build/pyinstaller packaging/basic.spec
if ($LASTEXITCODE -ne 0) { throw "Executable build failed" }
& $Iscc ("/DSourceRoot=" + $ProjectRoot) packaging/basic.iss
if ($LASTEXITCODE -ne 0) { throw "Installer compilation failed" }
Get-FileHash -Algorithm SHA256 dist/HWP-Make-Basic-Setup-1.0.0-x64.exe
