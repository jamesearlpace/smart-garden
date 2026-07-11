param([string]$Path = "/api/water-usage/audit?minutes=60")

$ErrorActionPreference = "Stop"
$token = (ssh acer "sudo bash ~/smart-garden-server/tools/authcookie.sh").Trim()
if (-not $token) { throw "Could not mint live session cookie" }
ssh acer "curl -sS -H 'Cookie: session=$token' 'http://localhost:5125$Path'"
