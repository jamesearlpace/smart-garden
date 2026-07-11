param([Parameter(Mandatory=$true)][string[]]$Files)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
foreach ($rel in $Files) {
    $local = Join-Path $root (Join-Path 'server-prod' $rel)
    if (-not (Test-Path -LiteralPath $local)) { throw "Missing local file: $local" }
    $remote = "~/smart-garden-server/$($rel -replace '\\','/')"
    $remoteHash = ssh acer "test -f $remote && sha256sum $remote || true"
    Write-Host "BEFORE $rel local=$((Get-FileHash -Algorithm SHA256 -LiteralPath $local).Hash) remote=$remoteHash"
    ssh acer "test ! -f $remote || cp $remote $remote.bak.$stamp"
    scp $local "acer:$remote"
}
ssh acer "sudo systemctl restart smart-garden-server && sudo systemctl is-active smart-garden-server"
$login = ''
for ($attempt = 1; $attempt -le 15; $attempt++) {
    $login = curl.exe -sS -o NUL -w '%{http_code}' https://sprinklers.savagepace.com/login
    if ($login -eq '200') { break }
    Start-Sleep -Seconds 2
}
if ($login -ne '200') { throw "Live login smoke failed after retries: HTTP $login" }
foreach ($rel in $Files) {
    $local = Join-Path $root (Join-Path 'server-prod' $rel)
    $remote = "~/smart-garden-server/$($rel -replace '\\','/')"
    $localHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $local).Hash.ToLowerInvariant()
    $remoteHash = (ssh acer "sha256sum $remote").Split(' ')[0].ToLowerInvariant()
    if ($localHash -ne $remoteHash) { throw "Parity failed for $rel" }
    Write-Host "AFTER $rel parity=$localHash"
}
