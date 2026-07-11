param([string[]]$Files)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$stage = Join-Path $env:TEMP 'smart-garden-round05-head'
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
git -C $root worktree prune
git -C $root worktree add --detach $stage HEAD
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
foreach ($rel in $Files) {
    $remoteRel = $rel -replace '^server-prod/', ''
    $remote = "~/smart-garden-server/$remoteRel"
    $local = Join-Path $stage $rel
    Write-Output "BEFORE $rel local=$((Get-FileHash $local -Algorithm SHA256).Hash.ToLower()) remote=$(ssh acer "sha256sum $remote")"
    ssh acer "test ! -f $remote || cp $remote $remote.bak.$stamp"
    scp $local "acer:$remote"
}
ssh acer "cd ~/smart-garden-server && .venv/bin/python -m py_compile database.py && sudo systemctl restart smart-garden-server && sudo systemctl is-active smart-garden-server"
for ($attempt = 1; $attempt -le 15; $attempt++) {
    $login = curl.exe -sS -o NUL -w '%{http_code}' https://sprinklers.savagepace.com/login
    if ($login -eq '200') { break }
    Start-Sleep -Seconds 2
}
if ($login -ne '200') { throw "Login smoke failed: HTTP $login" }
foreach ($rel in $Files) {
    $local = Join-Path $stage $rel
    $localHash = (Get-FileHash $local -Algorithm SHA256).Hash.ToLower()
    $remoteRel = $rel -replace '^server-prod/', ''
    $remoteHash = (ssh acer "sha256sum ~/smart-garden-server/$remoteRel").Split()[0]
    if ($localHash -ne $remoteHash) { throw "Parity failed: $rel" }
    Write-Output "AFTER $rel parity=$localHash"
}
git -C $root worktree remove --force $stage
