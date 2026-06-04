#!/usr/bin/env bash
# authcurl.sh — exercise auth-protected smart-garden endpoints from the server itself.
#
# WHY: every HTTP request hits check_auth() which requires a `session` cookie of the
# form  email|ts|HMAC_SHA256(SESSION_SECRET, "email|ts")  where email is in
# allowed_emails.json. Google OAuth is only used once at login to mint that cookie;
# it is NOT involved per-request. So to test authed routes we just mint a valid,
# legitimate cookie here using the SAME secret the running service already holds.
#
# This grants NO new capability: reading the live SESSION_SECRET requires sudo on the
# server (it comes from the systemd process environment), which is already root-equiv.
# Nothing here weakens auth — there is no bypass endpoint, no relaxed check.
#
# MUST run ON the server (localhost). Requires sudo to read the live secret.
#
# Usage:
#   sudo bash authcurl.sh GET  /api/vacation
#   sudo bash authcurl.sh POST /api/vacation '{"enabled":true}'
#   sudo bash authcurl.sh POST /api/run      '{"id":0}'
#
# Body is sent via a temp file with --data-binary to avoid shell-quoting corruption.

set -euo pipefail

PORT="${SG_PORT:-5125}"
APP_DIR="${SG_DIR:-/home/jamesearlpace/smart-garden-server}"
METHOD="${1:-GET}"
ROUTE="${2:-/api/status}"
BODY="${3:-}"

PID=$(systemctl show smart-garden-server -p MainPID --value)
SECRET=$(sudo tr '\0' '\n' < "/proc/${PID}/environ" | sed -n 's/^SESSION_SECRET=//p')
[ -z "$SECRET" ] && SECRET="smartgarden2026default"   # matches dashboard.py default
EMAIL=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))[0]['email'])" "${APP_DIR}/allowed_emails.json")

TS=$(date +%s)
SIG=$(SECRET="$SECRET" EMAIL="$EMAIL" TS="$TS" python3 - <<'PY'
import os, hmac, hashlib
s = os.environ["SECRET"].encode()
e = os.environ["EMAIL"]
ts = os.environ["TS"]
print(hmac.new(s, f"{e}|{ts}".encode(), hashlib.sha256).hexdigest())
PY
)
TOKEN="${EMAIL}|${TS}|${SIG}"

echo ">>> ${METHOD} ${ROUTE}  (as ${EMAIL})"
COMMON=(-s -X "$METHOD" "http://localhost:${PORT}${ROUTE}"
        -H "X-Requested-With: XMLHttpRequest"
        --cookie "session=${TOKEN}"
        -w '\n<<< HTTP %{http_code}\n')

if [ -n "$BODY" ]; then
  TMP=$(mktemp)
  printf '%s' "$BODY" > "$TMP"
  curl "${COMMON[@]}" -H "Content-Type: application/json" --data-binary "@${TMP}"
  rm -f "$TMP"
else
  curl "${COMMON[@]}"
fi
