param(
    [Parameter(Mandatory = $true)]
    [string]$BackupId,
    [string]$CoreUrl = "http://127.0.0.1:8000",
    [string]$Username = "superadmin",
    [string]$Password = "superadmin"
)

$ErrorActionPreference = "Stop"

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$loginBody = @{ username = $Username; password = $Password } | ConvertTo-Json
Invoke-WebRequest -Uri "$CoreUrl/login" -Method POST -ContentType "application/json" -Body $loginBody -WebSession $session | Out-Null

$resp = Invoke-RestMethod -Uri "$CoreUrl/superadmin/backups/$BackupId/offsite-sync" -Method POST -WebSession $session
$resp | ConvertTo-Json -Depth 8
