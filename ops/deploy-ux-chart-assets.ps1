param([string]$Commit = "44bfd33", [switch]$WorkingTree)
$ErrorActionPreference = "Stop"
$files = @(
  "templates/cam_archive.html", "templates/convergence.html", "templates/costs.html",
  "templates/index.html", "templates/moisture_sim.html", "templates/sensor_history.html",
  "templates/water_usage.html", "static/vendor/chart.umd-4.4.1.min.js",
  "static/vendor/chartjs-adapter-date-fns-3.0.0.bundle.min.js",
  "static/vendor/chartjs-plugin-datalabels-2.2.0.min.js",
  "static/vendor/chartjs-plugin-zoom-2.0.1.min.js", "static/vendor/hammer-2.0.8.min.js"
)
$stage = Join-Path $env:TEMP "smart-garden-ux-chart-assets"
if (Test-Path $stage) { Remove-Item -Recurse -Force -LiteralPath $stage }
New-Item -ItemType Directory -Force $stage | Out-Null
foreach ($file in $files) {
  $out = Join-Path $stage $file
  New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
  if ($WorkingTree) {
    Copy-Item -LiteralPath (Join-Path "server-prod" $file) -Destination $out
  } else {
    cmd /c "git show ${Commit}:server-prod/$file > `"$out`""
    if ($LASTEXITCODE -ne 0) { throw "Could not stage $file from $Commit" }
  }
}
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Write-Host "Pre-deploy local/remote SHA256 differences:"
foreach ($file in $files) {
  $localHash = (Get-FileHash -Algorithm SHA256 (Join-Path $stage $file)).Hash.ToLower()
  $remoteHash = (ssh acer "test -f ~/smart-garden-server/$file && sha256sum ~/smart-garden-server/$file | cut -d' ' -f1 || echo missing").Trim()
  if ($localHash -ne $remoteHash) { Write-Host "$file local=$localHash remote=$remoteHash" }
}
ssh acer "cd ~/smart-garden-server && mkdir -p backups/ux-chart-$stamp static/vendor && cp --parents templates/cam_archive.html templates/convergence.html templates/costs.html templates/index.html templates/moisture_sim.html templates/sensor_history.html templates/water_usage.html backups/ux-chart-$stamp/"
foreach ($file in $files) {
  $remoteDir = (Split-Path $file -Parent).Replace('\','/')
  scp (Join-Path $stage $file) "acer:smart-garden-server/$remoteDir/"
}
ssh acer "sudo systemctl restart smart-garden-server && systemctl is-active smart-garden-server"
foreach ($file in $files) {
  $localHash = (Get-FileHash -Algorithm SHA256 (Join-Path $stage $file)).Hash.ToLower()
  $remoteHash = (ssh acer "sha256sum ~/smart-garden-server/$file | cut -d' ' -f1").Trim()
  if ($localHash -ne $remoteHash) { throw "Parity failed: $file" }
}
curl.exe -fsS -o NUL -w "login=%{http_code}`n" https://sprinklers.savagepace.com/login
