param([Parameter(Mandatory=$true)][string[]]$Files)

$ErrorActionPreference = "Stop"
$remote = "/home/jamesearlpace/smart-garden-server"
foreach($file in $Files){
  $localPath = if($file.EndsWith('.html')){"server-prod/templates/$file"}else{"server-prod/$file"}
  $remotePath = if($file.EndsWith('.html')){"$remote/templates/$file"}else{"$remote/$file"}
  $tempPath = Join-Path $env:TEMP ("round14-remote-" + [guid]::NewGuid().ToString('N') + '-' + $file)
  Write-Host "PRE-DIFF $file"
  scp "acer:$remotePath" $tempPath
  git diff --no-index -- $tempPath $localPath
  if($LASTEXITCODE -gt 1){ throw "Pre-deploy diff failed for $file" }
  Remove-Item -LiteralPath $tempPath
}

& "$PSScriptRoot/../deploy.ps1" -Files $Files

foreach($file in $Files){
  $localPath = if($file.EndsWith('.html')){"server-prod/templates/$file"}else{"server-prod/$file"}
  $remotePath = if($file.EndsWith('.html')){"$remote/templates/$file"}else{"$remote/$file"}
  $localHash = (Get-FileHash -Algorithm SHA256 $localPath).Hash.ToLowerInvariant()
  $remoteHash = (ssh acer "sha256sum '$remotePath' | cut -d' ' -f1").Trim()
  if($localHash -ne $remoteHash){ throw "Post-deploy parity failed for $file" }
  Write-Host "PARITY $file $localHash"
}

$login = (ssh acer "curl -s -o /dev/null -w '%{http_code}' http://localhost:5125/login").Trim()
if($login -ne '200'){ throw "Live /login smoke failed: $login" }
