$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runAll = Join-Path $PSScriptRoot "run_all.ps1"

Write-Host "[aurora] Safe startup: docker + migrate + restart core/agent"
& $runAll -RestartExisting
