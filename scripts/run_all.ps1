param(
    [switch]$RestartExisting
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $root ".run"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

$corePidFile = Join-Path $runDir "core.pid"
$agentPidFile = Join-Path $runDir "agent.pid"
$coreOut = Join-Path $root "core.log"
$coreErr = Join-Path $root "core.err.log"
$agentOut = Join-Path $root "agent.log"
$agentErr = Join-Path $root "agent.err.log"

function Get-RunningProcessFromPidFile([string]$pidFile) {
    if (-not (Test-Path $pidFile)) { return $null }
    $raw = Get-Content -Path $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $raw) { return $null }
    $procId = 0
    if (-not [int]::TryParse($raw, [ref]$procId)) { return $null }
    return Get-Process -Id $procId -ErrorAction SilentlyContinue
}

function Stop-ByPidFile([string]$pidFile) {
    $p = Get-RunningProcessFromPidFile $pidFile
    if ($p) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $pidFile) {
        Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
    }
}

function Start-TrackedProcess(
    [string]$filePath,
    [string[]]$arguments,
    [string]$pidFile,
    [string]$stdoutFile,
    [string]$stderrFile
) {
    if (Test-Path $stdoutFile) { Remove-Item $stdoutFile -Force -ErrorAction SilentlyContinue }
    if (Test-Path $stderrFile) { Remove-Item $stderrFile -Force -ErrorAction SilentlyContinue }
    $p = Start-Process -FilePath $filePath `
        -ArgumentList $arguments `
        -WorkingDirectory $root `
        -RedirectStandardOutput $stdoutFile `
        -RedirectStandardError $stderrFile `
        -PassThru `
        -WindowStyle Hidden
    Set-Content -Path $pidFile -Value $p.Id -NoNewline
    return $p
}

Write-Host "[aurora] Starting Docker services..."
Push-Location $root
try {
    docker compose up -d | Out-Host
} finally {
    Pop-Location
}

$existingCore = Get-RunningProcessFromPidFile $corePidFile
$existingAgent = Get-RunningProcessFromPidFile $agentPidFile

if ($RestartExisting) {
    Stop-ByPidFile $corePidFile
    Stop-ByPidFile $agentPidFile
    $existingCore = $null
    $existingAgent = $null
}

if (-not $existingCore) {
    Write-Host "[aurora] Starting Core..."
    $core = Start-TrackedProcess `
        -filePath "python" `
        -arguments @("-m", "uvicorn", "aurora_core.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log", "--log-level", "warning") `
        -pidFile $corePidFile `
        -stdoutFile $coreOut `
        -stderrFile $coreErr
} else {
    Write-Host "[aurora] Core already running (PID $($existingCore.Id))."
}

if (-not $existingAgent) {
    Write-Host "[aurora] Starting Agent..."
    $agent = Start-TrackedProcess `
        -filePath "python" `
        -arguments @("-m", "aurora_agent.worker") `
        -pidFile $agentPidFile `
        -stdoutFile $agentOut `
        -stderrFile $agentErr
} else {
    Write-Host "[aurora] Agent already running (PID $($existingAgent.Id))."
}

$healthy = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $resp = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        if ($resp.status -eq "ok") { $healthy = $true; break }
    } catch {}
    Start-Sleep -Milliseconds 500
}

if ($healthy) {
    Write-Host "[aurora] Core health: OK"
} else {
    Write-Warning "[aurora] Core health check failed. Check core.err.log"
}

Write-Host ""
Write-Host "Aurora started."
Write-Host "Dashboard: http://127.0.0.1:8000/dashboard"
Write-Host "Core log:  $coreOut"
Write-Host "Agent log: $agentOut"
Write-Host ""
Write-Host "To force restart both: .\\scripts\\run_all.ps1 -RestartExisting"
