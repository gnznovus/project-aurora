$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $root ".run"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

$corePidFile = Join-Path $runDir "core.pid"
$coreOut = Join-Path $root "core.log"
$coreErr = Join-Path $root "core.err.log"
$activeVenvPython = $null
if ($env:VIRTUAL_ENV) {
    $candidate = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
    if (Test-Path $candidate) { $activeVenvPython = $candidate }
}
$projectVenvPython = Join-Path $root ".venv\Scripts\python.exe"
$pythonCmd = if ($activeVenvPython) {
    $activeVenvPython
} elseif (Test-Path $projectVenvPython) {
    $projectVenvPython
} else {
    "python"
}

function Assert-PythonModules([string]$pythonPath, [string[]]$modules) {
    $importList = ($modules | ForEach-Object { "'$_'" }) -join ", "
    & $pythonPath -c "import importlib.util, sys; mods=[$importList]; missing=[m for m in mods if importlib.util.find_spec(m) is None]; print(','.join(missing)); sys.exit(1 if missing else 0)"
    if ($LASTEXITCODE -ne 0) {
        throw "Missing Python modules in selected environment ($pythonPath). Install dependencies first: pip install -e .[dev]"
    }
}

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

Assert-PythonModules -pythonPath $pythonCmd -modules @("alembic", "uvicorn")

Write-Host "[aurora] Applying database migrations..."
Push-Location $root
try {
    & $pythonCmd -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "alembic upgrade head failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Write-Host "[aurora] Starting Core..."
$p = Start-Process -FilePath $pythonCmd `
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
