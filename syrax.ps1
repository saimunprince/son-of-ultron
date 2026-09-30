# Thin wrapper: everything lives in syrax.py (Windows, Linux, macOS).
#   .\syrax.ps1                     production UI
#   .\syrax.ps1 --dev               hot-reloading dev UI
#   .\syrax.ps1 --setup             install only
#   .\syrax.ps1 --install-service   start at login (Task Scheduler)
#   .\syrax.ps1 --uninstall-service
#   .\syrax.ps1 --status
#   .\syrax.ps1 --gate              release gate
$Root = $PSScriptRoot
$candidates = @((Join-Path $Root "backend\.venv\Scripts\python.exe"), "py", "python3", "python")
foreach ($py in $candidates) {
    $cmd = $null
    if (Test-Path $py) { $cmd = $py } else { $cmd = (Get-Command $py -ErrorAction SilentlyContinue).Source }
    if ($cmd) {
        if ($py -eq "py") { & $cmd -3 (Join-Path $Root "syrax.py") @args } else { & $cmd (Join-Path $Root "syrax.py") @args }
        exit $LASTEXITCODE
    }
}
Write-Error "SYRAX: Python not found. Install Python 3.12 (or uv) and rerun."
exit 1
