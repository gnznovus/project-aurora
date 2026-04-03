$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $root ".run"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

$corePidFile = Join-Path $runDir "core.pid"
$coreOut = Join-Path $root "core.log"
$coreErr = Join-Path $root "core.err.log"

function Get-CoreProcess() {
    if (-not (Test-Path $corePidFile)) { return $null }
    $raw = Get-Content -Path $corePidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $raw) { return $null }
    $procId = 0
    if (-not [int]::TryParse($raw, [ref]$procId)) { return $null }
    return Get-Process -Id $procId -ErrorAction SilentlyContinue
}

$existing = Get-CoreProcess
if ($existing) {
    Write-Host "[aurora] Stopping Core PID $($existing.Id)..."
    Stop-Process -Id $existing.Id -Force -ErrorAction SilentlyContinue
}
if (Test-Path $corePidFile) {
    Remove-Item -Path $corePidFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path $coreOut) { Remove-Item $coreOut -Force -ErrorAction SilentlyContinue }
if (Test-Path $coreErr) { Remove-Item $coreErr -Force -ErrorAction SilentlyContinue }

Write-Host "[aurora] Starting Core..."
$p = Start-Process -FilePath "python" `
    -ArgumentList @("-m", "uvicorn", "aurora_core.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log", "--log-level", "warning") `
    -WorkingDirectory $root `
    -RedirectStandardOutput $coreOut `
    -RedirectStandardError $coreErr `
    -PassThru `
    -WindowStyle Hidden

Set-Content -Path $corePidFile -Value $p.Id -NoNewline

$healthy = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $resp = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        if ($resp.status -eq "ok") { $healthy = $true; break }
    } catch {}
    Start-Sleep -Milliseconds 500
}

if ($healthy) {
    Write-Host "[aurora] Core restarted and healthy (PID $($p.Id))."
} else {
    Write-Warning "[aurora] Core restarted but health check failed. Check core.err.log"
}

Write-Host "Dashboard: http://127.0.0.1:8000/dashboard"
