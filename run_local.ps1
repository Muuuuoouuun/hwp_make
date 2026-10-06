param([switch]$CheckOnly)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# 파이썬 실행기 선택: "존재"만으로는 부족하다. 번들 런타임(codex-runtimes 캐시)에는
# fastapi/uvicorn이 없어 그걸 고르면 앱이 import 단계에서 죽는다. 그래서 후보들 중
# "실제로 uvicorn+fastapi를 import할 수 있는" 인터프리터를 고른다.
# 우선순위: HWP_MAKE_PYTHON → 번들 런타임 → PATH의 python → py 런처.
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

$Candidates = @()
if ($env:HWP_MAKE_PYTHON) { $Candidates += $env:HWP_MAKE_PYTHON }
$Candidates += $BundledPython
$Candidates += "python"
$Candidates += "py"

function Test-Candidate($exe) {
  # 경로형 후보는 파일이 있어야 하고, 명령형(python/py)은 PATH에 있어야 한다.
  if ($exe -match '[\\/]') {
    if (-not (Test-Path $exe)) { return $false }
  } else {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { return $false }
  }
  return $true
}

function Test-HasDeps($exe) {
  try {
    & $exe -c "import uvicorn, fastapi" *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

$Python = $null
$FirstRunnable = $null
foreach ($cand in $Candidates) {
  if (-not $cand) { continue }
  if (-not (Test-Candidate $cand)) { continue }
  if (-not $FirstRunnable) { $FirstRunnable = $cand }
  if (Test-HasDeps $cand) { $Python = $cand; break }
}

if (-not $Python) {
  Write-Host "[run_local] uvicorn/fastapi가 설치된 파이썬을 찾지 못했습니다." -ForegroundColor Yellow
  if ($FirstRunnable) {
    Write-Host "[run_local] 의존성 설치:  & '$FirstRunnable' -m pip install -r requirements.txt" -ForegroundColor Yellow
    Write-Host "[run_local] 또는 HWP_MAKE_PYTHON 환경변수로 의존성이 설치된 파이썬을 지정하세요." -ForegroundColor Yellow
  } else {
    Write-Host "[run_local] 파이썬 자체를 찾지 못했습니다. python 설치 후 'pip install -r requirements.txt'를 실행하세요." -ForegroundColor Yellow
  }
  exit 1
}

Write-Host "[run_local] Python: $Python" -ForegroundColor Green
if ($CheckOnly) { exit 0 }

# 앱의 "업데이트" 버튼은 git pull 후 종료 코드 3으로 서버를 끝낸다.
# 그 경우 requirements.txt가 바뀌었으면 의존성을 다시 설치하고 서버를 재시작한다.
$RestartExitCode = 3
$env:HWP_MAKE_SUPERVISED = "1"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$RequirementsHash = (Get-FileHash $Requirements).Hash

while ($true) {
  & $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
  if ($LASTEXITCODE -ne $RestartExitCode) { break }

  $NewHash = (Get-FileHash $Requirements).Hash
  if ($NewHash -ne $RequirementsHash) {
    Write-Host "[run_local] requirements.txt 변경 감지 - 의존성 설치 중..." -ForegroundColor Cyan
    & $Python -m pip install -r $Requirements
    $RequirementsHash = $NewHash
  }
  Write-Host "[run_local] 업데이트 적용 - 서버를 다시 시작합니다." -ForegroundColor Green
}
