param([ValidateSet('diff','deploy','verify')] [string]$Action)
$ErrorActionPreference = 'Stop'
$remote = 'acer'
$base = '/home/jamesearlpace/smart-garden-server'
$files = @('dashboard.py', 'templates/login.html', 'templates/sensor_history.html', 'templates/cam_archive.html')

if ($Action -eq 'diff') {
    $tmp = Join-Path $env:TEMP 'smart-garden-serial-fixer-remote'
    New-Item -ItemType Directory -Force $tmp | Out-Null
    foreach ($file in $files) {
        ssh $remote "sha256sum '$base/$file'"
        Get-FileHash (Join-Path 'server-prod' $file) -Algorithm SHA256 |
            ForEach-Object { "local $($_.Hash.ToLower())  $file" }
        $flat = $file.Replace('/', '_')
        scp "${remote}:$base/$file" (Join-Path $tmp $flat) | Out-Null
        git diff --no-index -- (Join-Path $tmp $flat) (Join-Path 'server-prod' $file)
    }
    exit
}

if ($Action -eq 'deploy') {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    ssh $remote "mkdir -p '$base/backups/serial-fixer-$stamp' && cp --parents '$base/dashboard.py' '$base/templates/login.html' '$base/templates/sensor_history.html' '$base/templates/cam_archive.html' '$base/backups/serial-fixer-$stamp/'"
    foreach ($file in $files) {
        scp (Join-Path 'server-prod' $file) "${remote}:$base/$file"
    }
    ssh $remote "cd '$base' && .venv/bin/python -m py_compile dashboard.py && sudo systemctl restart smart-garden-server"
    exit
}

foreach ($file in $files) {
    $remoteHash = (ssh $remote "sha256sum '$base/$file'").Split()[0]
    $localHash = (Get-FileHash (Join-Path 'server-prod' $file) -Algorithm SHA256).Hash.ToLower()
    if ($remoteHash -ne $localHash) { throw "Parity mismatch: $file" }
}
$login = curl.exe -sS -o NUL -w '%{http_code}' https://sprinklers.savagepace.com/login
if ($login -ne '200') { throw "Login smoke test returned $login" }
Write-Output 'Parity and /login smoke test passed.'
