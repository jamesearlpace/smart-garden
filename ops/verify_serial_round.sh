#!/usr/bin/env bash
set -euo pipefail

cd /home/jamesearlpace/smart-garden-server
for path in "$@"; do
  echo "=== ${path}"
  sudo bash tools/authcurl.sh GET "${path}" 2>/dev/null | tail -n +2
done
