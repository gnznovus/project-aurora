param(
    [Parameter(Mandatory = $true)]
    [string]$BackupId,
    [string]$CoreUrl = "http://127.0.0.1:8000",
    [string]$Username = "superadmin",
    [string]$Password = "superadmin",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$loginBody = @{ username = $Username; password = $Password } | ConvertTo-Json
Invoke-WebRequest -Uri "$CoreUrl/login" -Method POST -ContentType "application/json" -Body $loginBody -WebSession $session | Out-Null

$dryRun = $true
if ($Apply) {
    $dryRun = $false
}

if ($dryRun) {
    $resp = Invoke-RestMethod -Uri "$CoreUrl/superadmin/backups/$BackupId/restore?dry_run=$dryRun" -Method POST -WebSession $session
}
else {
    $body = @{ confirm = $BackupId } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "$CoreUrl/superadmin/backups/$BackupId/restore?dry_run=$dryRun" -Method POST -ContentType "application/json" -Body $body -WebSession $session
}
$resp | ConvertTo-Json -Depth 8
