param(
    [Parameter(Mandatory = $true)]
    [string[]]$Path,

    [switch]$Visible,

    [switch]$AllowAccessPrompt,

    [string]$ExportPdfDirectory = "",

    [int]$TimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"

$script:HwpProbeUiAvailable = $false
try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    Add-Type -AssemblyName WindowsBase
    $script:HwpProbeUiAvailable = $true
} catch {}

$NameHwp = -join ([char[]](0xD55C, 0xAE00))
$NameAllowAccess = (-join ([char[]](0xC811, 0xADFC, 0x20, 0xD5C8, 0xC6A9))) + "(Y)"

function Get-HwpAutomationPids {
    @(Get-CimInstance Win32_Process -Filter "Name = 'Hwp.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*-Automation*Embedding*" } |
        ForEach-Object { [int]$_.ProcessId })
}

function Get-HwpPids {
    @(Get-CimInstance Win32_Process -Filter "Name = 'Hwp.exe'" -ErrorAction SilentlyContinue |
        ForEach-Object { [int]$_.ProcessId })
}

function Send-HwpPromptEnter([int[]]$BeforePids) {
    $before = @{}
    foreach ($processId in $BeforePids) { $before[$processId] = $true }

    $shell = $null
    try {
        $shell = New-Object -ComObject WScript.Shell
    } catch {
        return $false
    }

    $sent = $false
    foreach ($processId in Get-HwpPids) {
        if ($before.ContainsKey($processId)) { continue }
        try {
            [void]$shell.AppActivate($processId)
            Start-Sleep -Milliseconds 150
            $shell.SendKeys("{ENTER}")
            $sent = $true
        } catch {}
    }
    return $sent
}

function Stop-NewHwpAutomationProcesses([int[]]$BeforePids) {
    $before = @{}
    foreach ($processId in $BeforePids) { $before[$processId] = $true }

    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        $stoppedAny = $false
        foreach ($proc in Get-CimInstance Win32_Process -Filter "Name = 'Hwp.exe'" -ErrorAction SilentlyContinue) {
            if ($proc.CommandLine -notlike "*-Automation*Embedding*") { continue }
            $processId = [int]$proc.ProcessId
            if ($before.ContainsKey($processId)) { continue }
            try {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                $stoppedAny = $true
            } catch {}
        }

        if (-not $stoppedAny) { Start-Sleep -Milliseconds 250 }
    }
}

function Stop-HwpAutomationProcesses {
    foreach ($proc in Get-CimInstance Win32_Process -Filter "Name = 'Hwp.exe'" -ErrorAction SilentlyContinue) {
        if ($proc.CommandLine -notlike "*-Automation*Embedding*") { continue }
        try {
            Stop-Process -Id ([int]$proc.ProcessId) -Force -ErrorAction SilentlyContinue
        } catch {}
    }
}

function Get-ElementName($Element) {
    try { return [string]$Element.Current.Name } catch { return "" }
}

function Read-ElementTexts($Element) {
    $texts = @()
    if ($null -eq $Element) { return $texts }
    $texts += Get-ElementName $Element
    try {
        $all = $Element.FindAll(
            [System.Windows.Automation.TreeScope]::Descendants,
            [System.Windows.Automation.Condition]::TrueCondition
        )
        foreach ($item in $all) {
            $name = Get-ElementName $item
            if ($name) { $texts += $name }
        }
    } catch {}
    return $texts
}

function Find-ButtonByName($Root, [string]$Name) {
    if ($null -eq $Root) { return $null }
    try {
        $buttonCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Button
        )
        $buttons = $Root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $buttonCondition)
        foreach ($button in $buttons) {
            if ((Get-ElementName $button) -eq $Name) { return $button }
        }
    } catch {}
    return $null
}

function Invoke-Element($Element) {
    if ($null -eq $Element) { return $false }
    $pattern = $null
    try {
        if ($Element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
            $pattern.Invoke()
            return $true
        }
    } catch {}
    return $false
}

function Invoke-HwpAccessPrompt([string[]]$TargetPaths) {
    if (-not $script:HwpProbeUiAvailable) { return $false }
    try {
        $root = [System.Windows.Automation.AutomationElement]::RootElement
        $windows = $root.FindAll(
            [System.Windows.Automation.TreeScope]::Children,
            [System.Windows.Automation.Condition]::TrueCondition
        )
        foreach ($window in $windows) {
            $title = Get-ElementName $window
            if ($title -notlike "*$NameHwp*") { continue }
            $texts = Read-ElementTexts $window
            $joined = $texts -join "`n"
            $matchesPath = $false
            foreach ($targetPath in $TargetPaths) {
                if (-not $targetPath) { continue }
                $fileName = [System.IO.Path]::GetFileName($targetPath)
                if ($joined -like "*$fileName*" -or $joined -like "*$targetPath*") {
                    $matchesPath = $true
                    break
                }
            }
            if (-not $matchesPath) { continue }
            $allow = Find-ButtonByName $window $NameAllowAccess
            if ($null -ne $allow -and (Invoke-Element $allow)) {
                Start-Sleep -Milliseconds 300
                return $true
            }
        }
    } catch {}
    return $false
}

function New-ChildProbeScript {
    $script = @'
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetPath,

    [Parameter(Mandatory = $true)]
    [string]$VisibleWindow,

    [string]$OutputPdfPath = "",

    [Parameter(Mandatory = $true)]
    [string]$ResultPath
)

$ErrorActionPreference = "Stop"

function Write-ProbeResult($Value) {
    $Value | ConvertTo-Json -Compress -Depth 4 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
}

$hwp = $null
try {
    try {
        $hwp = New-Object -ComObject "HWPFrame.HwpObject"
    } catch {
        Write-ProbeResult @{
            Status = "skip"
            Message = "HWPFrame.HwpObject is not registered: $($_.Exception.Message)"
        }
        exit 2
    }

    $securityModuleRegistered = $false
    try { $securityModuleRegistered = [bool]$hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule") } catch {}
    try { $hwp.XHwpWindows.Item(0).Visible = $true } catch {}

    $opened = $hwp.Open($TargetPath, "", "")
    if ($opened -eq $false) {
        Write-ProbeResult @{
            Status = "fail"
            Message = "Hwp.Open returned false"
            SecurityModuleRegistered = $securityModuleRegistered
        }
        exit 1
    }

    $savedPdf = $null
    $pdfBytes = $null
    if ($OutputPdfPath) {
        if (Test-Path -LiteralPath $OutputPdfPath) {
            Remove-Item -LiteralPath $OutputPdfPath -Force
        }
        $savedPdf = $hwp.SaveAs($OutputPdfPath, "PDF", "")
        if ($savedPdf -eq $false -or -not (Test-Path -LiteralPath $OutputPdfPath)) {
            Write-ProbeResult @{
                Status = "fail"
                Message = "Hwp.SaveAs PDF returned false or produced no file"
                PageCount = $hwp.PageCount
                OutputPdfPath = $OutputPdfPath
                SecurityModuleRegistered = $securityModuleRegistered
            }
            exit 1
        }
        $pdfBytes = (Get-Item -LiteralPath $OutputPdfPath).Length
    }

    if (-not [System.Convert]::ToBoolean($VisibleWindow)) {
        try { $hwp.XHwpWindows.Item(0).Visible = $false } catch {}
    }

    $pageCount = $null
    try { $pageCount = $hwp.PageCount } catch {}
    Write-ProbeResult @{
        Status = "ok"
        Message = "opened"
        PageCount = $pageCount
        SavedPdf = $savedPdf
        OutputPdfPath = $OutputPdfPath
        PdfBytes = $pdfBytes
        SecurityModuleRegistered = $securityModuleRegistered
    }
    exit 0
} catch {
    Write-ProbeResult @{
        Status = "fail"
        Message = $_.Exception.Message
        SecurityModuleRegistered = $securityModuleRegistered
    }
    exit 1
} finally {
    if ($null -ne $hwp) {
        try { $hwp.Quit() | Out-Null } catch {}
        try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($hwp) | Out-Null } catch {}
    }
}
'@

    $path = Join-Path ([System.IO.Path]::GetTempPath()) ("hwp_make_probe_{0}.ps1" -f ([guid]::NewGuid().ToString("N")))
    Set-Content -LiteralPath $path -Value $script -Encoding UTF8
    return $path
}

function Invoke-HwpOpenProcess(
    [string]$ResolvedPath,
    [string]$OutputPdfPath,
    [bool]$ShowWindow,
    [int]$TimeoutSec,
    [bool]$AllowPrompt
) {
    $childScript = New-ChildProbeScript
    $resultPath = Join-Path ([System.IO.Path]::GetTempPath()) ("hwp_make_probe_{0}.json" -f ([guid]::NewGuid().ToString("N")))
    $powershell = (Get-Command powershell.exe).Source
    $beforeHwpPids = Get-HwpPids
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $childScript,
        "-TargetPath", $ResolvedPath,
        "-OutputPdfPath", $OutputPdfPath,
        "-VisibleWindow", ([string]$ShowWindow),
        "-ResultPath", $resultPath
    )

    $proc = $null
    $promptActions = 0
    try {
        $proc = Start-Process -FilePath $powershell -ArgumentList $args -WindowStyle Hidden -PassThru
        $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSec))
        $lastPromptNudge = (Get-Date).AddSeconds(-10)
        while (-not $proc.HasExited -and (Get-Date) -lt $deadline) {
            if ($AllowPrompt) {
                if (Invoke-HwpAccessPrompt @($ResolvedPath, $OutputPdfPath)) {
                    $promptActions += 1
                }
                if (((Get-Date) - $lastPromptNudge).TotalSeconds -ge 2) {
                    if (Send-HwpPromptEnter $beforeHwpPids) {
                        $promptActions += 1
                    }
                    $lastPromptNudge = Get-Date
                }
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $proc.HasExited) {
            try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
            $timeoutMessage = "HWP COM open timed out after ${TimeoutSec}s"
            if (-not $AllowPrompt) {
                $timeoutMessage = "$timeoutMessage; access prompt handling is disabled"
            }
            return @{
                Status = "skip"
                Message = $timeoutMessage
                AccessPromptsAllowed = $promptActions
            }
        }

        if (Test-Path -LiteralPath $resultPath) {
            try {
                $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
                $result | Add-Member -NotePropertyName AccessPromptsAllowed -NotePropertyValue $promptActions -Force
                return $result
            } catch {
                return @{
                    Status = "fail"
                    Message = "invalid probe result: $($_.Exception.Message)"
                    AccessPromptsAllowed = $promptActions
                }
            }
        }

        return @{
            Status = "fail"
            Message = "probe exited $($proc.ExitCode) without a result file"
            AccessPromptsAllowed = $promptActions
        }
    } finally {
        try { Remove-Item -LiteralPath $childScript -Force -ErrorAction SilentlyContinue } catch {}
        try { Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue } catch {}
    }
}

$failed = $false
$skipped = $false
$resolvedPdfDirectory = ""
if ($ExportPdfDirectory) {
    try {
        $pdfDirectory = New-Item -ItemType Directory -Path $ExportPdfDirectory -Force
        $resolvedPdfDirectory = $pdfDirectory.FullName
    } catch {
        Write-Host "FAIL $ExportPdfDirectory - cannot create PDF output directory: $($_.Exception.Message)"
        exit 1
    }
}

foreach ($inputPath in $Path) {
    $resolved = $null
    try {
        $resolved = (Resolve-Path -LiteralPath $inputPath).Path
    } catch {
        Write-Host "FAIL $inputPath - file not found"
        $failed = $true
        continue
    }

    Stop-HwpAutomationProcesses
    Start-Sleep -Milliseconds 500
    $beforePids = Get-HwpAutomationPids
    $pdfOutputPath = ""
    if ($resolvedPdfDirectory) {
        $pdfName = ([System.IO.Path]::GetFileNameWithoutExtension($resolved)) + ".pdf"
        $pdfOutputPath = Join-Path $resolvedPdfDirectory $pdfName
    }
    try {
        $result = Invoke-HwpOpenProcess $resolved $pdfOutputPath ([bool]$Visible) $TimeoutSeconds ([bool]$AllowAccessPrompt)
        $status = [string]$result.Status

        if ($status -eq "ok") {
            $pageSuffix = ""
            if ($null -ne $result.PageCount -and "$($result.PageCount)" -ne "") {
                $pageSuffix = " pages=$($result.PageCount)"
            }
            $promptSuffix = ""
            if ($null -ne $result.AccessPromptsAllowed -and [int]$result.AccessPromptsAllowed -gt 0) {
                $promptSuffix = " access_prompts_allowed=$($result.AccessPromptsAllowed)"
            }
            $pdfSuffix = ""
            if ($result.OutputPdfPath) {
                $pdfSuffix = " pdf=$($result.OutputPdfPath) bytes=$($result.PdfBytes)"
            }
            Write-Host "OK $resolved$pageSuffix$pdfSuffix$promptSuffix"
        } elseif ($status -eq "skip") {
            Write-Host "SKIP $resolved - $($result.Message)"
            $skipped = $true
        } else {
            Write-Host "FAIL $resolved - $($result.Message)"
            $failed = $true
        }
    } catch {
        Write-Host "FAIL $resolved - $($_.Exception.Message)"
        $failed = $true
    } finally {
        Stop-NewHwpAutomationProcesses $beforePids
        Stop-HwpAutomationProcesses
    }
}

if ($failed) {
    exit 1
}
if ($skipped) {
    exit 2
}
exit 0
