param(
    [Parameter(Mandatory = $true)]
    [string[]]$Files,
    [switch]$BackupDatabase
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$remoteRoot = '/home/jamesearlpace/smart-garden-server'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

if ($BackupDatabase) {
    ssh acer 'sudo systemctl stop smart-garden-server'
    if ($LASTEXITCODE -ne 0) { throw 'Service stop failed before database backup' }
    ssh acer "cp '$remoteRoot/smart-garden.db' '$remoteRoot/smart-garden.db.bak.$stamp'"
    if ($LASTEXITCODE -ne 0) { throw 'Database backup failed' }
}

foreach ($file in $Files) {
    $local = Join-Path $repo "server-prod/$file"
    if (-not (Test-Path -LiteralPath $local)) { throw "Missing local file: $local" }
    $remote = "$remoteRoot/$file"
    $localHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $local).Hash.ToLowerInvariant()
    $remoteHash = (ssh acer "sha256sum '$remote' | cut -d' ' -f1").Trim().ToLowerInvariant()
    Write-Host "BEFORE $file local=$localHash remote=$remoteHash"
    ssh acer "cp '$remote' '$remote.bak.$stamp'"
    if ($LASTEXITCODE -ne 0) { throw "Backup failed: $remote" }
    scp $local "acer:$remote"
    if ($LASTEXITCODE -ne 0) { throw "Copy failed: $file" }
}

ssh acer $(if ($BackupDatabase) { 'sudo systemctl start smart-garden-server' } else { 'sudo systemctl restart smart-garden-server' })
if ($LASTEXITCODE -ne 0) { throw 'Service restart failed' }
Start-Sleep -Seconds 2

$loginStatus = curl.exe -sS -o NUL -w '%{http_code}' 'https://sprinklers.savagepace.com/login'
if ($loginStatus -ne '200') { throw "Live /login smoke failed: HTTP $loginStatus" }

foreach ($file in $Files) {
    $local = Join-Path $repo "server-prod/$file"
    $remote = "$remoteRoot/$file"
    $localHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $local).Hash.ToLowerInvariant()
    $remoteHash = (ssh acer "sha256sum '$remote' | cut -d' ' -f1").Trim().ToLowerInvariant()
    Write-Host "AFTER $file local=$localHash remote=$remoteHash"
    if ($localHash -ne $remoteHash) { throw "Parity failed: $file" }
}

Write-Host "DEPLOY_OK backup_suffix=.bak.$stamp login=$loginStatus"
