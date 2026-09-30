# Launch SYRAX on Windows: backend core (ws://127.0.0.1:8765) + orb UI (http://localhost:3000)
#   .\syrax.ps1                     production UI (builds when sources changed)
#   .\syrax.ps1 -Dev                hot-reloading dev UI
#   .\syrax.ps1 -InstallService     start SYRAX automatically at login (Task Scheduler)
#   .\syrax.ps1 -UninstallService   remove the login task
#   .\syrax.ps1 -Status             show the login task status
# Linux/GNOME: use ./syrax.sh instead.
[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$InstallService,
    [switch]$UninstallService,
    [switch]$Status,
    [switch]$Service
)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$TaskName = "SYRAX"
$Py = Join-Path $Root "backend\.venv\Scripts\python.exe"
$Cfg = Join-Path $Root "backend\config\config.toml"

if ($InstallService) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Root\syrax.ps1`" -Service" `
        -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "SYRAX will start automatically at your next login."
    Write-Host "Start it now:  Start-ScheduledTask -TaskName $TaskName     Stop:  Stop-ScheduledTask -TaskName $TaskName"
    exit 0
}
if ($UninstallService) {
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop } catch {}
    try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop } catch {}
    Write-Host "SYRAX login task removed."
    exit 0
}
if ($Status) {
    Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-Table -AutoSize
    Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-Table -AutoSize
    exit 0
}

if (-not (Test-Path $Py)) {
    Write-Error "SYRAX: backend not installed. Run:`n  cd backend; uv venv --python 3.12 .venv; uv pip install --python .venv\Scripts\python.exe -r requirements-syrax.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    Write-Error "SYRAX: frontend not installed. Run: cd frontend; npm install"
    exit 1
}

# Fail fast on a broken config instead of leaving the UI running alone.
$check = @'
import sys, tomllib
try:
    cfg = tomllib.load(open(sys.argv[1], "rb"))
except FileNotFoundError:
    sys.exit("SYRAX: backend/config/config.toml is missing. Copy config/config.syrax.example.toml over it.")
except tomllib.TOMLDecodeError as e:
    sys.exit(f"SYRAX: config.toml is not valid TOML ({e}). Only TOML goes in that file.")
if "llm" not in cfg or "daytona" not in cfg:
    sys.exit("SYRAX: config.toml needs [llm] and [daytona]. Copy config.syrax.example.toml over it.")
'@
$check | & $Py - $Cfg
if ($LASTEXITCODE -ne 0) { exit 1 }

# Refuse to start half-way when a port is already taken.
foreach ($port in 8765, 3000) {
    $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($owner) {
        if ($Service) { exit 0 }   # as a login task, another running SYRAX is fine: step aside quietly
        $proc = Get-Process -Id $owner.OwningProcess -ErrorAction SilentlyContinue
        $name = if ($proc) { "$($proc.ProcessName) pid $($proc.Id)" } else { "pid $($owner.OwningProcess)" }
        Write-Error "SYRAX: port $port is already in use by $name. Is SYRAX already running?"
        exit 1
    }
}

$Frontend = Join-Path $Root "frontend"
if (-not $Dev) {
    $buildId = Join-Path $Frontend ".next\BUILD_ID"
    $stale = -not (Test-Path $buildId)
    if (-not $stale) {
        $built = (Get-Item $buildId).LastWriteTime
        $sources = @("app", "components", "lib") | ForEach-Object { Get-ChildItem (Join-Path $Frontend $_) -Recurse -File }
        $sources += Get-Item (Join-Path $Frontend "package.json"), (Get-Item (Join-Path $Frontend "next.config.ts"))
        $stale = ($sources | Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1) -ne $null
    }
    if ($stale) {
        Write-Host "SYRAX: building the UI (first run or sources changed)..."
        Push-Location $Frontend
        try { npx next build | Out-Null } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { Write-Error "SYRAX: UI build failed. Run: cd frontend; npx next build"; exit 1 }
    }
}

# Each component is its own process; on exit the whole tree of each is killed
# (npx -> node -> next-server, python -> whisper threads), not just the top.
$procs = @()
function Stop-Tree($p) {
    if ($p -and -not $p.HasExited) { & taskkill /PID $p.Id /T /F 2>$null | Out-Null }
}
$env:SYRAX_OPEN_UI = if ($Service) { "1" } elseif ($env:SYRAX_OPEN_UI) { $env:SYRAX_OPEN_UI } else { "0" }

try {
    $procs += Start-Process -FilePath $Py -ArgumentList "-m", "syrax.server" -WorkingDirectory (Join-Path $Root "backend") -NoNewWindow -PassThru
    $uiArgs = if ($Dev) { "next dev --hostname 127.0.0.1 --port 3000" } else { "next start --hostname 127.0.0.1 --port 3000" }
    $procs += Start-Process -FilePath "npx.cmd" -ArgumentList $uiArgs -WorkingDirectory $Frontend -NoNewWindow -PassThru

    Write-Host "SYRAX core  : ws://127.0.0.1:8765/ws"
    Write-Host "SYRAX orb UI: http://localhost:3000"

    $opened = $env:SYRAX_OPEN_UI -ne "1"
    # If any part dies, take the rest down so nothing runs half-broken.
    while ($true) {
        Start-Sleep -Seconds 1
        $dead = $procs | Where-Object { $_.HasExited } | Select-Object -First 1
        if ($dead) { Write-Warning "SYRAX: a component exited, shutting down."; break }
        if (-not $opened) {
            try {
                $ui = Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:3000 -TimeoutSec 2
                $core = Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8765/health -TimeoutSec 2
                if ($ui.StatusCode -eq 200 -and $core.StatusCode -eq 200) { Start-Process "http://localhost:3000"; $opened = $true }
            } catch {}
        }
    }
} finally {
    foreach ($p in $procs) { Stop-Tree $p }
}
