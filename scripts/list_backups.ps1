param(
    [string]$CoreUrl = "http://127.0.0.1:8000",
    [string]$Username = "superadmin",
    [string]$Password = "superadmin",
    [int]$Limit = 50
)

$ErrorActionPreference = "Stop"

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$loginBody = @{ username = $Username; password = $Password } | ConvertTo-Json
Invoke-WebRequest -Uri "$CoreUrl/login" -Method POST -ContentType "application/json" -Body $loginBody -WebSession $session | Out-Null

$resp = Invoke-RestMethod -Uri "$CoreUrl/superadmin/backups?limit=$Limit" -Method GET -WebSession $session
$resp | ConvertTo-Json -Depth 6
