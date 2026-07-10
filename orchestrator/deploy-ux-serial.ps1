param([Parameter(Mandatory=$true)][string[]]$Files)
$ErrorActionPreference = 'Stop'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
foreach ($file in $Files) {
    $local = Join-Path $PSScriptRoot "..\server-prod\$file"
    $remote = "~/smart-garden-server/$file"
    ssh acer "cp $remote $remote.bak.ux-$stamp"
    scp $local "acer:$remote"
}
ssh acer "sudo systemctl restart smart-garden-server"
ssh acer "systemctl is-active smart-garden-server"
