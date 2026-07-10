$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$files = @(
  'templates/_mobilenav.html',
  'templates/costs.html',
  'templates/forecast_merged.html',
  'templates/convergence.html',
  'templates/flow.html',
  'templates/water_usage.html'
)
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

Write-Host 'Pre-deploy server/local checksums'
foreach ($file in $files) {
  $local = Join-Path "$root/server-prod" $file
  $localHash = (Get-FileHash -Algorithm SHA256 $local).Hash.ToLower()
  $remoteHash = (ssh acer "sha256sum ~/smart-garden-server/$file | cut -d' ' -f1").Trim()
  Write-Host "$file local=$localHash remote=$remoteHash"
}

ssh acer "mkdir -p ~/smart-garden-server/backups/serial-fixer-$stamp/templates; for f in $($files -join ' '); do mkdir -p ~/smart-garden-server/backups/serial-fixer-$stamp/`$(dirname `$f); cp ~/smart-garden-server/`$f ~/smart-garden-server/backups/serial-fixer-$stamp/`$f; done"
foreach ($file in $files) {
  scp (Join-Path "$root/server-prod" $file) "acer:~/smart-garden-server/$file"
}
ssh acer "sudo systemctl restart smart-garden-server && systemctl is-active smart-garden-server"

Write-Host 'Post-deploy parity'
foreach ($file in $files) {
  $local = Join-Path "$root/server-prod" $file
  $localHash = (Get-FileHash -Algorithm SHA256 $local).Hash.ToLower()
  $remoteHash = (ssh acer "sha256sum ~/smart-garden-server/$file | cut -d' ' -f1").Trim()
  if ($localHash -ne $remoteHash) { throw "Parity mismatch: $file" }
  Write-Host "$file OK"
}
curl.exe -fsS -o NUL -w "login=%{http_code}`n" https://sprinklers.savagepace.com/login
