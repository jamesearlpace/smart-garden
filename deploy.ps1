param(
  [string[]]$Files = @(
    "dashboard.py",
    "flow_monitor.py",
    "meter_ledger.py",
    "water_reconcile.py"
  )
)

# deploy.ps1 — guarded deploy for smart-garden. Codex/James run this; no free-form ssh.
# Backs up remote, pushes selected server-prod code, restarts, smoke-tests. NEVER touches *.db.
$ErrorActionPreference = "Stop"
$H = "acer"; $R = "~/smart-garden-server"; $ts = Get-Date -f yyyyMMdd-HHmmss

if (-not $Files -or $Files.Count -eq 0) { throw "No deploy files specified" }
$bad = $Files | Where-Object { $_ -like "*.db" -or $_ -match "[\\/]" -or $_ -notmatch "^[A-Za-z0-9_.-]+$" }
if ($bad) { throw "Refusing unsafe deploy file(s): $($bad -join ', ')" }

$py = @($Files | Where-Object { $_ -like "*.py" })
$tpl = @($Files | Where-Object { $_ -like "*.html" })
$other = @($Files | Where-Object { $_ -notlike "*.py" -and $_ -notlike "*.html" })
if ($other) { throw "Unsupported deploy file type(s): $($other -join ', ')" }

Write-Host "1. Compile check..." -f Cyan
if ($py.Count) {
  & C:\Users\james\AppData\Local\Programs\Python\Python311\python.exe -m py_compile (($py | ForEach-Object { "server-prod\$_" }))
  if ($LASTEXITCODE) { throw "compile failed - abort" }
}
if (($Files -contains "dashboard.py") -or ($Files -contains "flow_monitor.py") -or $tpl.Count) {
  & C:\Users\james\AppData\Local\Programs\Python\Python311\python.exe server-prod\tools\check_zone_labels.py
  if ($LASTEXITCODE) { throw "zone label check failed - abort" }
}

Write-Host "2. Backup remote..." -f Cyan
$remoteFiles = @()
$remoteFiles += $py
$remoteFiles += ($tpl | ForEach-Object { "templates/$_" })
ssh $H "cd $R; for f in $($remoteFiles -join ' '); do cp `$f `$f.bak.$ts 2>/dev/null; done"

Write-Host "3. Push code (NOT dbs)..." -f Cyan
if ($py.Count) {
  scp ($py | ForEach-Object { "server-prod\$_" }) "${H}:${R}/"
}
if ($tpl.Count) {
  scp ($tpl | ForEach-Object { "server-prod\templates\$_" }) "${H}:${R}/templates/"
}

if ($py -contains "dashboard.py") {
  Write-Host "3b. Set guarded OCR thresholds..." -f Cyan
  $dropin = @'
[Service]
Environment=METER_ARCHIVE_STALE_CNN_MIN_CONF=0.97
Environment=METER_ARCHIVE_REPROCESS_CNN_MIN_CONF=0.97
Environment=METER_ARCHIVE_EXACT_CNN_MIN_CONF=0.97
Environment=METER_CONSTRAINED_MIN_CONF=0.97
'@
  $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($dropin))
  ssh $H "sudo mkdir -p /etc/systemd/system/smart-garden-server.service.d; echo $encoded | base64 -d | sudo tee /etc/systemd/system/smart-garden-server.service.d/zz-codex-ocr-thresholds.conf >/dev/null; sudo systemctl daemon-reload"
}

Write-Host "4. Restart..." -f Cyan
ssh $H "sudo systemctl restart smart-garden-server"

Write-Host "5. Smoke test..." -f Cyan
Start-Sleep 4
$code = (ssh $H "curl -s -o /dev/null -w '%{http_code}' http://localhost:5125/login")
if ($code -eq "200") { Write-Host "OK deployed - /login 200 (backups .bak.$ts)" -f Green } else { Write-Host "WARN http $code - check service" -f Yellow }
