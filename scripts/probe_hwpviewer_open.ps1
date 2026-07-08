param(
    [Parameter(Mandatory = $true)]
    [string[]]$Path,

    [string]$ViewerPath = "C:\Program Files (x86)\Hnc\Office 2024 Viewer\HOffice130\Bin\HwpViewer.exe",

    [int]$TimeoutSeconds = 45,

    [switch]$Trace
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName WindowsBase
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class HwpProbeNative {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, string lParam);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}
"@

$WM_CLOSE = 0x0010
$WM_SETTEXT = 0x000C
$BM_CLICK = 0x00F5
$MOUSEEVENTF_LEFTDOWN = 0x0002
$MOUSEEVENTF_LEFTUP = 0x0004

$NameHwpViewer = -join ([char[]](0xD55C, 0xAE00, 0x20, 0xBDF0, 0xC5B4))
$NameOpenDialog = -join ([char[]](0xBD88, 0xB7EC, 0xC624, 0xAE30))
$NameLoadToolbar = "$NameOpenDialog : ALT+O"
$NameOpenButton = (-join ([char[]](0xC5F4, 0xAE30))) + "(O)"
$PageSuffix = [string][char]0xCABD
$PageRegex = "\d+/\d+$PageSuffix"
$ViewerErrorMessage = -join ([char[]](
    0xD30C, 0xC77C, 0xC744, 0x20,
    0xC77D, 0xAC70, 0xB098, 0x20,
    0xC800, 0xC7A5, 0xD558, 0xB294, 0xB370, 0x20,
    0xC624, 0xB958, 0xAC00, 0x20,
    0xC788, 0xC2B5, 0xB2C8, 0xB2E4, 0x2E
))

function Write-TraceLine([string]$Message) {
    if ($Trace) {
        Write-Host "[trace] $Message"
    }
}

function Get-Name([System.Windows.Automation.AutomationElement]$Element) {
    try { return [string]$Element.Current.Name } catch { return "" }
}

function Get-Hwnd([System.Windows.Automation.AutomationElement]$Element) {
    try { return [IntPtr]$Element.Current.NativeWindowHandle } catch { return [IntPtr]::Zero }
}

function Find-ByName(
    [System.Windows.Automation.AutomationElement]$Root,
    [string]$Name,
    [System.Windows.Automation.TreeScope]$Scope = [System.Windows.Automation.TreeScope]::Descendants
) {
    if ($null -eq $Root) { return $null }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty,
        $Name
    )
    return $Root.FindFirst($Scope, $condition)
}

function Find-ByControlType(
    [System.Windows.Automation.AutomationElement]$Root,
    [System.Windows.Automation.ControlType]$ControlType,
    [System.Windows.Automation.TreeScope]$Scope = [System.Windows.Automation.TreeScope]::Descendants
) {
    if ($null -eq $Root) { return $null }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        $ControlType
    )
    return $Root.FindFirst($Scope, $condition)
}

function Find-FileNameEdit([System.Windows.Automation.AutomationElement]$Dialog) {
    if ($null -eq $Dialog) { return $null }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit
    )
    $edits = $Dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    for ($index = ([int]$edits.Count - 1); $index -ge 0; $index--) {
        $candidate = $edits.Item($index)
        if ((Get-Hwnd $candidate) -ne [IntPtr]::Zero -and $candidate.Current.ClassName -eq "Edit") {
            return $candidate
        }
    }
    for ($index = ([int]$edits.Count - 1); $index -ge 0; $index--) {
        $candidate = $edits.Item($index)
        if ((Get-Hwnd $candidate) -ne [IntPtr]::Zero) {
            return $candidate
        }
    }
    return $null
}

function Find-ViewerWindow([int]$ProcessId) {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $pidCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
        $ProcessId
    )
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $pidCondition)
    $fallback = $null
    foreach ($window in $windows) {
        $name = Get-Name $window
        if ($name -eq "Hancom AD") { continue }
        if ($null -eq $fallback) { $fallback = $window }
        if ($name -like "*$NameHwpViewer*") { return $window }
    }
    return $fallback
}

function Find-ProcessWindowByName([int]$ProcessId, [string]$Name) {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $pidCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
        $ProcessId
    )
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $pidCondition)
    foreach ($window in $windows) {
        if ((Get-Name $window) -eq $Name) { return $window }
        $nested = Find-ByName $window $Name
        if ($null -ne $nested) { return $nested }
    }
    return $null
}

function Wait-Until([scriptblock]$Block, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $value = & $Block
        if ($null -ne $value -and $false -ne $value) {
            return $value
        }
        Start-Sleep -Milliseconds 250
    }
    return $null
}

function Click-Element([System.Windows.Automation.AutomationElement]$Element) {
    if ($null -eq $Element) { return $false }
    $point = New-Object System.Windows.Point
    try {
        if ($Element.TryGetClickablePoint([ref]$point)) {
            [HwpProbeNative]::SetCursorPos([int]$point.X, [int]$point.Y) | Out-Null
            [HwpProbeNative]::mouse_event($MOUSEEVENTF_LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
            Start-Sleep -Milliseconds 80
            [HwpProbeNative]::mouse_event($MOUSEEVENTF_LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
            return $true
        }
    } catch {}

    try {
        $rect = $Element.Current.BoundingRectangle
        if (-not $rect.IsEmpty -and $rect.Width -gt 0 -and $rect.Height -gt 0) {
            $x = [int]($rect.X + ($rect.Width / 2))
            $y = [int]($rect.Y + ($rect.Height / 2))
            [HwpProbeNative]::SetCursorPos($x, $y) | Out-Null
            [HwpProbeNative]::mouse_event($MOUSEEVENTF_LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
            Start-Sleep -Milliseconds 80
            [HwpProbeNative]::mouse_event($MOUSEEVENTF_LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
            return $true
        }
    } catch {}

    $pattern = $null
    try {
        if ($Element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
            $pattern.Invoke()
            return $true
        }
    } catch {}
    return $false
}

function Close-AdWindows([int]$ProcessId) {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $pidCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
        $ProcessId
    )
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $pidCondition)
    foreach ($window in $windows) {
        $candidates = @()
        if ((Get-Name $window) -eq "Hancom AD") {
            $candidates += $window
        }
        $nested = Find-ByName $window "Hancom AD"
        if ($null -ne $nested) {
            $candidates += $nested
        }
        foreach ($ad in $candidates) {
            $hwnd = Get-Hwnd $ad
            if ($hwnd -ne [IntPtr]::Zero) {
                Write-TraceLine "closing Hancom AD hwnd=$hwnd"
                [HwpProbeNative]::PostMessage($hwnd, $WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
            }
        }
    }
    Start-Sleep -Milliseconds 500
}

function Open-LoadDialog([System.Windows.Automation.AutomationElement]$Window, [int]$ProcessId) {
    $dialog = Find-ByName $Window $NameOpenDialog
    if ($null -eq $dialog) { $dialog = Find-ProcessWindowByName $ProcessId $NameOpenDialog }
    if ($null -ne $dialog) { return $dialog }

    $hwnd = Get-Hwnd $Window
    if ($hwnd -ne [IntPtr]::Zero) {
        [HwpProbeNative]::SetForegroundWindow($hwnd) | Out-Null
    }
    Start-Sleep -Milliseconds 300

    $load = Find-ByName $Window $NameLoadToolbar
    Write-TraceLine "load toolbar found=$($null -ne $load)"
    if ($null -ne $load) {
        $clicked = Click-Element $load
        Write-TraceLine "load toolbar clicked=$clicked"
    }

    $dialog = Wait-Until {
        Find-ProcessWindowByName $ProcessId $NameOpenDialog
    } 3
    Write-TraceLine "dialog after toolbar=$($null -ne $dialog)"
    if ($null -ne $dialog) { return $dialog }

    try {
        Write-TraceLine "send Alt+O"
        [System.Windows.Forms.SendKeys]::SendWait("%o")
    } catch {}
    $dialog = Wait-Until {
        Find-ProcessWindowByName $ProcessId $NameOpenDialog
    } 3
    Write-TraceLine "dialog after Alt+O=$($null -ne $dialog)"
    if ($null -ne $dialog) { return $dialog }

    try {
        Write-TraceLine "send Ctrl+O"
        [System.Windows.Forms.SendKeys]::SendWait("^o")
    } catch {}
    $dialog = Wait-Until {
        Find-ProcessWindowByName $ProcessId $NameOpenDialog
    } 3
    Write-TraceLine "dialog after Ctrl+O=$($null -ne $dialog)"
    return $dialog
}

function Read-VisibleText([System.Windows.Automation.AutomationElement]$Window) {
    $textCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Text
    )
    $texts = @()
    try {
        $items = $Window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $textCondition)
        foreach ($item in $items) {
            $name = Get-Name $item
            if ($name) { $texts += $name }
        }
    } catch {}
    return $texts
}

function Read-ProcessSnapshot([int]$ProcessId) {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $pidCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
        $ProcessId
    )
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $pidCondition)
    $titles = @()
    $texts = @()
    for ($index = 0; $index -lt [int]$windows.Count; $index++) {
        $window = $windows.Item($index)
        $title = Get-Name $window
        if ($title) { $titles += $title }
        $texts += Read-VisibleText $window
    }
    return @{
        titles = $titles
        texts = $texts
    }
}

function Probe-One([string]$InputPath) {
    $resolved = (Resolve-Path -LiteralPath $InputPath).Path
    Get-Process HwpViewer -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500

    $proc = Start-Process -FilePath $ViewerPath -PassThru
    try {
        $window = Wait-Until { Find-ViewerWindow $proc.Id } 20
        if ($null -eq $window) {
            return [pscustomobject]@{
                path = $resolved
                status = "no_window"
                title = ""
                errorText = ""
                pagesText = ""
            }
        }

        Wait-Until {
            $current = Find-ViewerWindow $proc.Id
            if ($null -eq $current) { return $null }
            Find-ByName $current $NameLoadToolbar
        } 10 | Out-Null
        Close-AdWindows $proc.Id
        Start-Sleep -Milliseconds 500
        $window = Find-ViewerWindow $proc.Id
        $dialog = Open-LoadDialog $window $proc.Id
        if ($null -eq $dialog) {
            return [pscustomobject]@{
                path = $resolved
                status = "no_open_dialog"
                title = Get-Name $window
                errorText = ""
                pagesText = ""
            }
        }

        $edit = Find-FileNameEdit $dialog
        $open = Find-ByName $dialog $NameOpenButton
        if ($null -eq $edit -or $null -eq $open) {
            return [pscustomobject]@{
                path = $resolved
                status = "open_dialog_incomplete"
                title = Get-Name $window
                errorText = ""
                pagesText = ""
            }
        }

        $editHwnd = Get-Hwnd $edit
        Write-TraceLine "filename edit hwnd=$editHwnd"
        if ($editHwnd -ne [IntPtr]::Zero) {
            [HwpProbeNative]::SendMessage($editHwnd, $WM_SETTEXT, [IntPtr]::Zero, $resolved) | Out-Null
        } else {
            $valuePattern = $null
            try {
                if ($edit.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$valuePattern)) {
                    $valuePattern.SetValue($resolved)
                }
            } catch {
                return [pscustomobject]@{
                    path = $resolved
                    status = "set_filename_failed"
                    title = Get-Name $window
                    errorText = $_.Exception.Message
                    pagesText = ""
                }
            }
        }

        Start-Sleep -Milliseconds 300
        $openHwnd = Get-Hwnd $open
        Write-TraceLine "open button hwnd=$openHwnd"
        if ($openHwnd -ne [IntPtr]::Zero) {
            [HwpProbeNative]::SendMessage($openHwnd, $BM_CLICK, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
        } else {
            Click-Element $open | Out-Null
        }

        $fileName = [System.IO.Path]::GetFileName($resolved)
        $opened = $null
        $error = $null
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
            $window = Find-ViewerWindow $proc.Id
            if ($null -eq $window) { continue }
            $snapshot = Read-ProcessSnapshot $proc.Id
            $title = (($snapshot.titles | Where-Object { $_ -like "*$NameHwpViewer*" -or $_ -like "*$fileName*" } | Select-Object -First 1), (Get-Name $window) | Where-Object { $_ } | Select-Object -First 1)
            $texts = $snapshot.texts
            $joined = $texts -join "`n"
            $titleJoined = $snapshot.titles -join "`n"
            if ($titleJoined -like "*$fileName*" -or $joined -match $PageRegex) {
                $opened = @{
                    title = $titleJoined
                    texts = $texts
                }
                break
            }
            if ($joined -like "*$ViewerErrorMessage*") {
                $error = @{
                    title = $title
                    texts = $texts
                }
                break
            }
        }

        if ($null -ne $opened) {
            $pages = ($opened.texts | Where-Object { $_ -match $PageRegex } | Select-Object -First 1)
            return [pscustomobject]@{
                path = $resolved
                status = "opened"
                title = $opened.title
                errorText = ""
                pagesText = [string]$pages
            }
        }

        if ($null -ne $error) {
            $message = ($error.texts | Where-Object { $_ -like "*$ViewerErrorMessage*" } | Select-Object -First 1)
            return [pscustomobject]@{
                path = $resolved
                status = "viewer_error"
                title = $error.title
                errorText = [string]$message
                pagesText = ""
            }
        }

        $window = Find-ViewerWindow $proc.Id
        return [pscustomobject]@{
            path = $resolved
            status = "timeout"
            title = if ($null -ne $window) { Get-Name $window } else { "" }
            errorText = ""
            pagesText = ""
        }
    } finally {
        Get-Process HwpViewer -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

$results = foreach ($inputFile in $Path) {
    Probe-One $inputFile
}

$results | ConvertTo-Json -Depth 4
