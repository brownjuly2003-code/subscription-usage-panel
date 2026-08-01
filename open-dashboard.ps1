# Subscription Usage Panel - simple open / refresh
#
# Default (convenient):
#   .\open-dashboard.ps1              # fetch now -> write dashboard.html -> open file
#   .\open-dashboard.ps1 -Install     # auto-refresh HTML every 10 min + at logon
#   .\open-dashboard.ps1 -Uninstall   # remove scheduled refresh
#
# Optional:
#   .\open-dashboard.ps1 -Live        # browser auto-refresh via local server
#   .\open-dashboard.ps1 -Stop        # stop -Live server if running
#   .\open-dashboard.ps1 -Status
#   .\open-dashboard.ps1 -Quiet       # refresh HTML only (for Task Scheduler)
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Live,
    [switch]$Stop,
    [switch]$Status,
    [switch]$Quiet,
    [int]$Port = 8765,
    [string]$BindHost = "127.0.0.1",
    [int]$EveryMinutes = 5
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$TaskName = "SubscriptionUsagePanel-Refresh"
$HtmlPath = Join-Path $Root "dashboard.html"
$Url = "http://$($BindHost):$($Port)/"
$HealthUrl = $Url + "api/health"
$PidFile = Join-Path $Root ".cache\serve.pid"
$ThisScript = $MyInvocation.MyCommand.Path

function Get-PythonExe {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    throw "python not found in PATH"
}

function Test-ServerUp {
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300)
    } catch {
        return $false
    }
}

function Get-ListenerPids {
    $found = @()
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            $found = @($conns | Select-Object -ExpandProperty OwningProcess -Unique)
        }
    } catch { }
    if (-not $found -or $found.Count -eq 0) {
        $lines = netstat -ano 2>$null | Select-String -Pattern (":$Port\s+.*LISTENING")
        foreach ($line in $lines) {
            $parts = ($line.ToString() -split "\s+") | Where-Object { $_ -ne "" }
            if ($parts.Count -ge 5) {
                $n = 0
                if ([int]::TryParse($parts[-1], [ref]$n) -and $n -gt 0) {
                    $found += $n
                }
            }
        }
        $found = @($found | Select-Object -Unique)
    }
    return $found
}

function Update-HtmlSnapshot {
    $py = Get-PythonExe
    $limitsPy = Join-Path $Root "limits.py"
    & $py $limitsPy --html $HtmlPath
    if (-not (Test-Path -LiteralPath $HtmlPath)) {
        throw "Failed to write dashboard.html"
    }
}

function Open-HtmlFile {
    if (-not (Test-Path -LiteralPath $HtmlPath)) {
        throw "dashboard.html not found"
    }
    Start-Process $HtmlPath
}

function Start-ServerBackground {
    if (Test-ServerUp) { return $true }
    $py = Get-PythonExe
    $cacheDir = Join-Path $Root ".cache"
    if (-not (Test-Path -LiteralPath $cacheDir)) {
        New-Item -ItemType Directory -Path $cacheDir | Out-Null
    }
    $limitsPy = Join-Path $Root "limits.py"
    $proc = Start-Process -FilePath $py `
        -ArgumentList @($limitsPy, "--serve", "--host", $BindHost, "--port", "$Port") `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $PidFile -Value $proc.Id -Encoding ascii
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        if (Test-ServerUp) { return $true }
        if ($proc.HasExited) { return $false }
        Start-Sleep -Milliseconds 400
    }
    return (Test-ServerUp)
}

function Stop-Server {
    $stopped = $false
    $list = @(Get-ListenerPids)
    if (Test-Path -LiteralPath $PidFile) {
        $saved = 0
        $raw = (Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ([int]::TryParse($raw, [ref]$saved) -and $saved -gt 0) {
            $list = @($list + $saved | Select-Object -Unique)
        }
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    }
    foreach ($procId in $list) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            if (-not $Quiet) { Write-Host "Stopped PID $procId" }
            $stopped = $true
        } catch { }
    }
    if (-not $stopped -and -not $Quiet) {
        Write-Host "No live server on port $Port"
    }
}

function Install-RefreshSchedule {
    if ($EveryMinutes -lt 5) { $EveryMinutes = 5 }
    $cacheDir = Join-Path $Root ".cache"
    if (-not (Test-Path -LiteralPath $cacheDir)) {
        New-Item -ItemType Directory -Path $cacheDir | Out-Null
    }
    # wscript + VBS + pythonw = no console window flash (powershell -WindowStyle Hidden still flashes)
    $vbs = Join-Path $Root "refresh-quiet.vbs"
    if (-not (Test-Path -LiteralPath $vbs)) {
        throw "Missing refresh-quiet.vbs (silent refresher)"
    }
    $wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
    $action = New-ScheduledTaskAction `
        -Execute $wscript `
        -Argument "//B //Nologo `"$vbs`"" `
        -WorkingDirectory $Root
    $tLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $tRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -MultipleInstances IgnoreNew
    # Hide from Task Scheduler UI noise where supported
    try { $settings.Hidden = $true } catch { }
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
    Register-ScheduledTask -TaskName $TaskName `
        -Action $action `
        -Trigger @($tLogon, $tRepeat) `
        -Settings $settings `
        -Principal $principal `
        -Description "Silent refresh of Panel dashboard.html every $EveryMinutes min (no window)" `
        -Force | Out-Null

    # Ensure Hidden sticks on PS 5.1
    try {
        $t = Get-ScheduledTask -TaskName $TaskName
        $t.Settings.Hidden = $true
        Set-ScheduledTask -InputObject $t | Out-Null
    } catch { }

    $old = Get-ScheduledTask -TaskName "SubscriptionUsagePanel" -ErrorAction SilentlyContinue
    if ($old) {
        Unregister-ScheduledTask -TaskName "SubscriptionUsagePanel" -Confirm:$false
        if (-not $Quiet) { Write-Host "Removed old server autostart task." }
    }

    if (-not $Quiet) {
        Write-Host "OK: silent auto-refresh every $EveryMinutes min (no popup windows)."
        Write-Host "Open: $HtmlPath"
        Write-Host "Or double-click: Open Dashboard.bat"
    }
}

function Uninstall-RefreshSchedule {
    foreach ($n in @($TaskName, "SubscriptionUsagePanel")) {
        $existing = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        if ($existing) {
            Unregister-ScheduledTask -TaskName $n -Confirm:$false
            if (-not $Quiet) { Write-Host "Removed task: $n" }
        }
    }
}

if ($Uninstall) {
    Uninstall-RefreshSchedule
    Stop-Server
    exit 0
}

if ($Install) {
    Install-RefreshSchedule
    if (-not $Quiet) { Write-Host "Refreshing once now..." }
    Update-HtmlSnapshot
    if (-not $Quiet) {
        Write-Host "Done. Open dashboard.html anytime."
        Open-HtmlFile
    }
    exit 0
}

if ($Stop) {
    Stop-Server
    exit 0
}

if ($Status) {
    $age = "?"
    if (Test-Path -LiteralPath $HtmlPath) {
        $age = (Get-Item -LiteralPath $HtmlPath).LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
    }
    Write-Host "HTML: $HtmlPath"
    Write-Host "Last write: $age"
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "Auto-refresh task: $($task.State)"
    } else {
        Write-Host "Auto-refresh task: not installed (.\open-dashboard.ps1 -Install)"
    }
    if (Test-ServerUp) {
        Write-Host "Live server: UP  $Url"
    } else {
        Write-Host "Live server: off (not needed for normal use)"
    }
    exit 0
}

if ($Quiet) {
    Update-HtmlSnapshot
    exit 0
}

if ($Live) {
    if (-not (Test-ServerUp)) {
        if (-not (Start-ServerBackground)) {
            Write-Host "ERROR: live server failed to start"
            exit 1
        }
    }
    Write-Host "Live: $Url"
    Start-Process $Url
    exit 0
}

# Default: refresh snapshot, open file. No server.
if (-not $Quiet) { Write-Host "Updating limits..." }
Update-HtmlSnapshot
if (-not $Quiet) {
    $ts = (Get-Item -LiteralPath $HtmlPath).LastWriteTime.ToString("HH:mm:ss")
    Write-Host "Ready ($ts) - opening dashboard.html"
}
Open-HtmlFile
exit 0
