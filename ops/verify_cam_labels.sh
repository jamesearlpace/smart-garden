#!/usr/bin/env bash
set -euo pipefail
cd /home/jamesearlpace/smart-garden-server
token=$(sudo bash tools/authcookie.sh)
curl -fsS -H "Cookie: session=${token}" \
  'http://localhost:5125/api/cam/labels?captures=2'
