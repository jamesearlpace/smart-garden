$ErrorActionPreference = 'Stop'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$files = @('dashboard.py', 'meter_archive.py', 'templates/convergence.html')
foreach ($file in $files) {
    ssh acer "cp ~/smart-garden-server/$file ~/smart-garden-server/$file.bak.round11-$stamp"
    scp "server-prod/$file" "acer:~/smart-garden-server/$file"
}
ssh acer 'sudo systemctl restart smart-garden-server'
ssh acer 'systemctl is-active smart-garden-server'
curl.exe -sS -o NUL -w '%{http_code}' https://sprinklers.savagepace.com/login
