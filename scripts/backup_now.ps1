param(
    [string]$CoreUrl = "http://127.0.0.1:8000",
    [string]$Username = "superadmin",
    [string]$Password = "superadmin"
)

$ErrorActionPreference = "Stop"

Write-Host "[aurora] Logging in as $Username..."
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$loginBody = @{ username = $Username; password = $Password } | ConvertTo-Json
Invoke-WebRequest -Uri "$CoreUrl/login" -Method POST -ContentType "application/json" -Body $loginBody -WebSession $session | Out-Null

Write-Host "[aurora] Creating backup..."
$resp = Invoke-RestMethod -Uri "$CoreUrl/superadmin/backups/create" -Method POST -WebSession $session
$resp | ConvertTo-Json -Depth 5
