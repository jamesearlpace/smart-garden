$ErrorActionPreference = "Stop"
$cookie = (ssh acer "cd ~/smart-garden-server && sudo bash tools/authcookie.sh --header").Trim()
foreach ($path in @('/api/calibration', '/api/calibration/history', '/api/battery-calibration')) {
  $result = curl.exe -sS -w "`n%{http_code}" -H $cookie "https://sprinklers.savagepace.com$path"
  $lines = $result -split "`n"
  $status = $lines[-1].Trim()
  $body = ($lines[0..($lines.Length - 2)] -join "`n")
  if ($status -ne '200') { throw "$path returned $status" }
  $null = $body | ConvertFrom-Json
  Write-Host "$path 200 valid-json"
}
