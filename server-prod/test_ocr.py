#!/usr/bin/env python3
"""Quick test of OCR pipeline with the test image."""
import sys
sys.path.insert(0, "/home/jamesearlpace/smart-garden-server")
from cam_ocr import MeterReader

m = MeterReader()
print("Enabled:", m.enabled)

with open("/tmp/water_meter.jpg", "rb") as f:
    data = f.read()
print(f"Image size: {len(data)} bytes")

result = m.process(data)
for k, v in result.items():
    print(f"  {k}: {v}")
