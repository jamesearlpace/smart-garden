"""CNN inference: frame bytes/path -> 9 digits + per-digit confidence.

This is the live reader's fast path. Returns the same shape the oracle does so
the pipeline can treat them uniformly:
  {ok, value, digits, confidence, min_conf, per_digit_conf, readable}

Routing rule (in the live pipeline): if min_conf < CONF_THRESHOLD, fall through
to the GPT-4o oracle. Otherwise accept the CNN read (free/instant).
"""
import os

import numpy as np
import torch
import torch.nn.functional as F

from config import N_DIGITS, CONF_THRESHOLD, ROTATE_180
from dataset import load_crop_gray, _clahe  # reuse identical preprocessing
from model import MeterDigitCNN

HERE = os.path.dirname(__file__)
_MODEL = None


def _get_model(weights=None):
    global _MODEL
    if _MODEL is None:
        m = MeterDigitCNN()
        w = weights or os.path.join(HERE, "model", "meter_cnn.pt")
        m.load_state_dict(torch.load(w, map_location="cpu"))
        m.eval()
        _MODEL = m
    return _MODEL


def read_path(path, weights=None):
    gray = load_crop_gray(path)                     # (H,W) float32, same as training
    return _read_gray(gray, weights)


def read_jpeg_bytes(data, rotate=ROTATE_180, weights=None):
    import cv2
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if rotate:
        img = cv2.rotate(img, cv2.ROTATE_180)
    from config import CROP, IN_H, IN_W
    h, w = img.shape[:2]
    l, t, r, b = CROP
    crop = img[int(t*h):int(b*h), int(l*w):int(r*w)]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    g = _clahe.apply(g)
    g = cv2.resize(g, (IN_W, IN_H), interpolation=cv2.INTER_AREA).astype(np.float32)/255.0
    return _read_gray(g, weights)


def _read_gray(gray, weights=None):
    m = _get_model(weights)
    x = torch.from_numpy(gray).unsqueeze(0).unsqueeze(0)   # (1,1,H,W)
    with torch.no_grad():
        logits = m(x)                                      # (1,9,10)
        probs = F.softmax(logits, dim=-1)[0]               # (9,10)
    conf, pred = probs.max(dim=-1)                          # (9,),(9,)
    digits = "".join(str(int(d)) for d in pred)
    per = [round(float(c), 3) for c in conf]
    min_conf = float(conf.min())
    value = int(digits) if len(digits) == 9 else None
    return {
        "ok": value is not None,
        "value": value,
        "digits": digits,
        "confidence": "high" if min_conf >= CONF_THRESHOLD else "low",
        "min_conf": round(min_conf, 3),
        "per_digit_conf": per,
        "readable": min_conf >= CONF_THRESHOLD,
    }


if __name__ == "__main__":
    import sys
    print(read_path(sys.argv[1]))
