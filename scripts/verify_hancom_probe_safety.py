"""Parse the Windows probe and prove unrelated Hancom sessions stay untouched."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        print("SKIP: PowerShell is required for probe safety verification")
        return 2
    probe = ROOT / "scripts/probe_hwp_open.ps1"
    sample = ROOT / "app/_vendor/hwpx/data/Skeleton.hwpx"
    with tempfile.TemporaryDirectory(prefix="hancom_probe_safety_") as temporary:
        driver = Path(temporary) / "guard.ps1"
        driver.write_text(r'''
param([string]$ProbePath, [string]$SamplePath, [switch]$NoActiveSession)
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($ProbePath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
function Get-CimInstance {
    if (-not $NoActiveSession) {
        [pscustomobject]@{ ProcessId = 4101; CommandLine = 'hwp -Automation -Embedding' }
    }
}
function Stop-Process { throw 'UNRELATED_PROCESS_STOP_ATTEMPTED' }
function Get-Command { [pscustomobject]@{ Source = 'mock-powershell-for-probe' } }
function Start-Process { throw 'EXPECTED_AUTOMATION_START' }
function Start-Sleep {}
& $ProbePath -Path $SamplePath
exit $LASTEXITCODE
''', encoding="utf-8")
        result = subprocess.run([shell, "-NoLogo", "-NoProfile", "-File", str(driver),
                                 str(probe), str(sample)], capture_output=True, text=True,
                                timeout=30)
        assert result.returncode == 2, (result.stdout, result.stderr)
        assert "another Hancom automation session is active; left untouched" in result.stdout
        assert "STOP_ATTEMPTED" not in result.stdout + result.stderr
        result = subprocess.run([shell, "-NoLogo", "-NoProfile", "-File", str(driver),
                                 str(probe), str(sample), "-NoActiveSession"],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 1 and "EXPECTED_AUTOMATION_START" in result.stdout, (result.stdout, result.stderr)
        assert "another Hancom automation session is active" not in result.stdout

        driver.write_text(r'''
param([string]$ProbePath)
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ProbePath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$cleanup = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Stop-NewHwpAutomationProcesses'
}, $true)
. ([scriptblock]::Create($cleanup.Extent.Text))
$script:Processes = @(
    [pscustomobject]@{ ProcessId = 4101; CommandLine = 'hwp -Automation -Embedding' },
    [pscustomobject]@{ ProcessId = 4102; CommandLine = 'hwp -Automation -Embedding' },
    [pscustomobject]@{ ProcessId = 4103; CommandLine = 'hwp interactive_document.hwpx' }
)
$script:Stopped = @()
function Get-CimInstance { $script:Processes }
function Start-Sleep {}
function Stop-Process {
    param([int]$Id, [switch]$Force, $ErrorAction)
    $script:Stopped += $Id
    $script:Processes = @($script:Processes | Where-Object { $_.ProcessId -ne $Id })
}
Stop-NewHwpAutomationProcesses @(4101)
if ($script:Stopped.Count -ne 1 -or $script:Stopped[0] -ne 4102) {
    throw "Wrong process cleanup: $script:Stopped"
}
if (@($script:Processes).Count -ne 2) { throw 'Unrelated Hancom process was removed' }
Write-Output 'OWN_AUTOMATION_CLEANUP_OK'
''', encoding="utf-8")
        result = subprocess.run([shell, "-NoLogo", "-NoProfile", "-File", str(driver), str(probe)],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0 and "OWN_AUTOMATION_CLEANUP_OK" in result.stdout, (result.stdout, result.stderr)
    print("HANCOM_PROBE_SAFETY_OK: syntax valid; active sessions preserved; only new automation cleaned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
