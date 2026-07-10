#!/bin/bash
cd ~/meter-archive
echo "total frames: $(ls | wc -l)"
echo "coverage across the freeze window:"
for stamp in 20260708-22 20260708-23 20260709-02 20260709-03 20260709-04 20260709-06 20260709-08 20260709-10 20260709-12 20260709-14; do
  n=$(ls ${stamp}*.jpg 2>/dev/null | wc -l)
  echo "  ${stamp}:xx -> ${n} frames"
done
