param([Parameter(Mandatory=$true)][string[]]$Files)
$ErrorActionPreference = 'Stop'
$remote = ssh acer "cd ~/smart-garden-server && sha256sum $($Files -join ' ')"
if ($LASTEXITCODE) { throw 'Remote hash check failed' }
$remoteMap = @{}
foreach ($line in $remote) {
  if ($line -match '^([0-9a-f]{64})\s+(.+)$') { $remoteMap[$Matches[2]] = $Matches[1] }
}
foreach ($file in $Files) {
  $localPath = Join-Path 'server-prod' $file
  $localHash = (Get-FileHash -Algorithm SHA256 $localPath).Hash.ToLowerInvariant()
  $remoteHash = $remoteMap[$file]
  $state = if ($localHash -eq $remoteHash) { 'MATCH' } else { 'DIFF' }
  Write-Output "$state $file local=$localHash remote=$remoteHash"
}
