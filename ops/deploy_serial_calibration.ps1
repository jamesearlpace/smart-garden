$ErrorActionPreference = "Stop"
$remote = "~/smart-garden-server/dashboard.py"
$local = "server-prod/dashboard.py"
$stamp = Get-Date -Format yyyyMMdd-HHmmss

$localBefore = (Get-FileHash -Algorithm SHA256 $local).Hash.ToLower()
$remoteBefore = (ssh acer "sha256sum $remote | cut -d' ' -f1").Trim()
Write-Host "Pre-deploy local=$localBefore remote=$remoteBefore"
ssh acer "cp $remote $remote.bak.$stamp"
scp $local "acer:~/smart-garden-server/dashboard.py"
ssh acer "sudo systemctl restart smart-garden-server"
Start-Sleep -Seconds 4
$login = (ssh acer "curl -s -o /dev/null -w '%{http_code}' http://localhost:5125/login").Trim()
$remoteAfter = (ssh acer "sha256sum $remote | cut -d' ' -f1").Trim()
Write-Host "Post-deploy local=$localBefore remote=$remoteAfter login=$login backup=$remote.bak.$stamp"
if ($login -ne "200") { throw "Live /login smoke test returned $login" }
if ($remoteAfter -ne $localBefore) { throw "Server/local SHA256 mismatch" }
