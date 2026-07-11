#!/usr/bin/env bash
set -euo pipefail
cd /home/jamesearlpace/smart-garden-server
cookie=$(sudo bash tools/authcookie.sh)
for path in "$@"; do
  code=$(curl -sS -o /tmp/sg-live-check.out -w '%{http_code}' \
    -H "Cookie: session=${cookie}" "http://127.0.0.1:5125${path}")
  printf '%s HTTP %s bytes=%s\n' "$path" "$code" "$(wc -c </tmp/sg-live-check.out)"
  test "$code" = 200
  case "$path" in
    /api/*) python3 -m json.tool </tmp/sg-live-check.out >/dev/null ;;
  esac
done
