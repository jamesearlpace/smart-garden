#!/usr/bin/env bash
# Idempotently install a weekly shadow-calibration run (bit-rot canary).
# Runs the read-only prototype every Monday 06:15 and appends output to a log.
# Safe: the tool never writes config / control DB / valves.
set -euo pipefail

DIR="$HOME/smart-garden-server"
LOG="$DIR/calibration-weekly.log"
LINE="15 6 * * 1 cd $DIR && ./.venv/bin/python tools/prototype_zone_calibration.py >> $LOG 2>&1"
MARKER="prototype_zone_calibration.py"

current="$(crontab -l 2>/dev/null || true)"
if printf '%s\n' "$current" | grep -qF "$MARKER"; then
  echo "cron already present; no change"
else
  printf '%s\n%s\n' "$current" "$LINE" | grep -v '^$' | crontab -
  echo "cron installed: $LINE"
fi

echo "--- current garden-related crontab ---"
crontab -l 2>/dev/null | grep -F "$MARKER" || true
