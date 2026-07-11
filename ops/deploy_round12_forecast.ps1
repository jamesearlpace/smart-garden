$ErrorActionPreference = 'Stop'

$local = Join-Path $PSScriptRoot '..\server-prod\templates\forecast_merged.html'
$remote = '/home/jamesearlpace/smart-garden-server/templates/forecast_merged.html'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$pre = Join-Path $env:TEMP "forecast_merged.pre-$stamp.html"
$post = Join-Path $env:TEMP "forecast_merged.post-$stamp.html"

Write-Host 'Pre-deploy server/local diff and hashes'
scp "acer:$remote" $pre
git diff --no-index -- $pre $local
if ($LASTEXITCODE -gt 1) { throw 'Pre-deploy diff failed' }
Get-FileHash -Algorithm SHA256 $local | Select-Object Path, Hash
ssh acer "sha256sum '$remote'"

ssh acer "cp '$remote' '$remote.bak.round12-$stamp'"
scp $local "acer:$remote"
ssh acer 'sudo systemctl restart smart-garden-server; sudo systemctl is-active smart-garden-server'

Write-Host 'Post-deploy server/local diff and hashes'
scp "acer:$remote" $post
git diff --no-index -- $post $local
if ($LASTEXITCODE -ne 0) { throw 'Post-deploy parity check failed' }
Get-FileHash -Algorithm SHA256 $local | Select-Object Path, Hash
ssh acer "sha256sum '$remote'"
$status = curl.exe -sS -o NUL -w '%{http_code}' https://sprinklers.savagepace.com/login
if ($status -ne '200') { throw "Live /login returned HTTP $status" }
Write-Host "Live /login HTTP $status"
