#!/usr/bin/env python3
"""Rotate all sample frames 180 deg (camera is mounted upside-down) into a
sibling dir so they can be read right-side-up for ground-truth verification."""
import os
from PIL import Image

SRC = os.path.join(os.path.dirname(__file__), "frames")
DST = os.path.join(os.path.dirname(__file__), "frames_upright")
os.makedirs(DST, exist_ok=True)
n = 0
for f in os.listdir(SRC):
    if not f.endswith(".jpg"):
        continue
    img = Image.open(os.path.join(SRC, f)).rotate(180)
    img.save(os.path.join(DST, f), "JPEG", quality=95)
    n += 1
print(f"rotated {n} frames -> {DST}")
