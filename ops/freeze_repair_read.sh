#!/bin/bash
set -e
cd ~/smart-garden-server/tools
SRC=reread_20260708_real_frames.py
DST=reread_20260709_freeze.py
cp "$SRC" "$DST"
# Retarget constants to the freeze window (07-08 22:00 -> 07-09 16:04, just before re-anchor)
sed -i 's#reread_cache_20260708.json#reread_cache_20260709_freeze.json#' "$DST"
sed -i 's#WINDOW_START = "2026-07-06T03:30:00"#WINDOW_START = "2026-07-08T22:00:00"#' "$DST"
sed -i 's#WINDOW_END = "2026-07-08T10:20:00"#WINDOW_END = "2026-07-09T16:04:00"#' "$DST"
sed -i 's#NOTE = "reread_20260708_real_frames"#NOTE = "reread_20260709_freeze"#' "$DST"
sed -i 's#ORIGIN_READ = "oracle_reread:20260708"#ORIGIN_READ = "oracle_reread:20260709_freeze"#' "$DST"
sed -i 's#ORIGIN_INTERP = "repair:20260708_reread_interp"#ORIGIN_INTERP = "repair:20260709_freeze_interp"#' "$DST"
echo '=== patched constants ==='
grep -nE 'WINDOW_START|WINDOW_END|CACHE_PATH|^NOTE|ORIGIN_READ|ORIGIN_INTERP' "$DST"
echo '=== py_compile ==='
cd ~/smart-garden-server && ./.venv/bin/python -m py_compile tools/"$DST" && echo OK
echo '=== READ phase (safe, no DB writes) ==='
cd ~/smart-garden-server && REREAD_PACE_S=1.5 ./.venv/bin/python tools/"$DST" read 2>&1 | tail -25
