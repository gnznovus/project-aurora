$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $root ".run"
$corePidFile = Join-Path $runDir "core.pid"
$agentPidFile = Join-Path $runDir "agent.pid"

function Stop-ByPidFile([string]$pidFile, [string]$name) {
    if (-not (Test-Path $pidFile)) {
        Write-Host "[aurora] $name not running (no pid file)."
        return
    }
    $raw = Get-Content -Path $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $procId = 0
    if ($raw -and [int]::TryParse($raw, [ref]$procId)) {
        $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($p) {
            Write-Host "[aurora] Stopping $name PID $procId..."
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
}

Stop-ByPidFile -pidFile $corePidFile -name "Core"
Stop-ByPidFile -pidFile $agentPidFile -name "Agent"

Write-Host "[aurora] Stopping Docker services..."
Push-Location $root
try {
    docker compose down | Out-Host
} finally {
    Pop-Location
}

Write-Host "[aurora] All services stopped."
