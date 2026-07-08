param(
    [Parameter(Mandatory = $true)]
    [string[]]$Path,

    [switch]$Visible
)

$ErrorActionPreference = "Stop"

function New-HwpComObject {
    try {
        return New-Object -ComObject "HWPFrame.HwpObject"
    } catch {
        Write-Host "SKIP HWPFrame.HwpObject is not registered: $($_.Exception.Message)"
        exit 2
    }
}

function Close-HwpObject($Hwp) {
    if ($null -eq $Hwp) { return }
    try { $Hwp.Quit() | Out-Null } catch {}
    try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($Hwp) | Out-Null } catch {}
}

$failed = $false

foreach ($inputPath in $Path) {
    $resolved = $null
    try {
        $resolved = (Resolve-Path -LiteralPath $inputPath).Path
    } catch {
        Write-Host "FAIL $inputPath - file not found"
        $failed = $true
        continue
    }

    $hwp = $null
    try {
        $hwp = New-HwpComObject
        try { $hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule") | Out-Null } catch {}
        try { $hwp.XHwpWindows.Item(0).Visible = [bool]$Visible } catch {}

        $opened = $hwp.Open($resolved, "", "")
        if ($opened -eq $false) {
            Write-Host "FAIL $resolved - Hwp.Open returned false"
            $failed = $true
            continue
        }

        $pageCount = ""
        try { $pageCount = " pages=$($hwp.PageCount)" } catch {}
        Write-Host "OK $resolved$pageCount"
    } catch {
        Write-Host "FAIL $resolved - $($_.Exception.Message)"
        $failed = $true
    } finally {
        Close-HwpObject $hwp
    }
}

if ($failed) {
    exit 1
}
exit 0
