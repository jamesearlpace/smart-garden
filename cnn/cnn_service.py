#!/usr/bin/env python3
"""CNN meter-digit service — runs on the tower (jackmint, 192.168.0.120:5201).

Isolated from the working RapidOCR service (port 5200). Loads the trained
PyTorch CNN (meter_cnn.pt) and reads a meter frame into 9 digits + per-digit
confidence. The Acer's OCR worker calls this FIRST (free/fast); only low-confidence
frames fall through to the paid GPT-4o oracle.

Endpoints:
  POST /cnn   body = raw JPEG bytes  -> {digits, value, min_conf, per_digit_conf,
                                          confidence, readable, ms}
  GET  /health                        -> {ok, model, threshold}

Run in the meter-ocr venv (has torch 2.12 CPU + cv2):
  ~/meter-ocr/.venv/bin/python ~/meter-cnn/cnn_service.py
"""
import os
import time
import logging

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("meter-cnn")
app = Flask(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
WEIGHTS = os.environ.get("METER_CNN_WEIGHTS", os.path.join(HERE, "meter_cnn.pt"))

# Model version tag — bump on each retrain so metrics can attribute reads/accuracy
# to a specific model. Read from a VERSION file next to the weights (one line),
# fallback to "v1". The retrain job writes this file when it promotes a new model.
def _model_version():
    try:
        with open(os.path.join(HERE, "VERSION")) as f:
            return f.read().strip() or "v1"
    except OSError:
        return "v1"

# --- must match cnn/config.py used at training time ---
CROP = (0.02, 0.02, 0.92, 0.46)
IN_H, IN_W = 64, 256
N_DIGITS, N_CLASSES = 9, 10
CONF_THRESHOLD = float(os.environ.get("METER_CNN_THRESHOLD", "0.90"))
ROTATE_180 = True

_clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))

_POW9 = 10 ** np.arange(8, -1, -1)


def _constrained_decode(probs_np, lo, hi, max_cand=40000):
    """Most-likely 9-digit value within [lo, hi] under the per-digit probs
    (probs_np shape (9,10)). The meter is monotonic + slow, so the true value
    sits in a narrow window above the last lock; constraining the read to that
    window recovers frames the free argmax collapses under glare. Returns int
    or None (window empty / too large)."""
    if hi < lo or (hi - lo + 1) > max_cand:
        return None
    logp = np.log(probs_np + 1e-9)
    cand = np.arange(lo, hi + 1, dtype=np.int64)
    digs = (cand[:, None] // _POW9) % 10            # (n,9)
    scores = logp[np.arange(9)[None, :], digs].sum(axis=1)
    return int(cand[scores.argmax()])


# --- model (copied from cnn/model.py so the service is self-contained) ---
def _block(cin, cout, pool=(2, 2)):
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(inplace=True),
        nn.Conv2d(cout, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(inplace=True),
        nn.MaxPool2d(pool))


class MeterDigitCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = nn.Sequential(
            _block(1, 32), _block(32, 64), _block(64, 128), _block(128, 128))
        self.pool = nn.AdaptiveAvgPool2d((1, N_DIGITS))
        self.drop = nn.Dropout(0.3)
        self.heads = nn.ModuleList([nn.Linear(128, N_CLASSES) for _ in range(N_DIGITS)])

    def forward(self, x):
        f = self.backbone(x)
        f = self.pool(f).squeeze(2).transpose(1, 2)
        f = self.drop(f)
        return torch.stack([self.heads[i](f[:, i, :]) for i in range(N_DIGITS)], dim=1)


_model = {"net": None}


def get_model():
    if _model["net"] is None:
        m = MeterDigitCNN()
        m.load_state_dict(torch.load(WEIGHTS, map_location="cpu"))
        m.eval()
        torch.set_num_threads(2)
        _model["net"] = m
        log.info("loaded CNN weights from %s", WEIGHTS)
    return _model["net"]


def preprocess(jpeg_bytes):
    arr = np.frombuffer(jpeg_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    if ROTATE_180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    h, w = img.shape[:2]
    l, t, r, b = CROP
    crop = img[int(t*h):int(b*h), int(l*w):int(r*w)]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    g = _clahe.apply(g)
    g = cv2.resize(g, (IN_W, IN_H), interpolation=cv2.INTER_AREA).astype(np.float32)/255.0
    return g


@app.route("/cnn", methods=["POST"])
def cnn():
    t0 = time.time()
    data = request.get_data(cache=False)
    if not data or len(data) < 100:
        return jsonify({"ok": False, "error": "no image"}), 400
    g = preprocess(data)
    if g is None:
        return jsonify({"ok": False, "error": "decode failed"}), 400
    m = get_model()
    x = torch.from_numpy(g).unsqueeze(0).unsqueeze(0)
    with torch.no_grad():
        probs = F.softmax(m(x), dim=-1)[0]          # (9,10)
    conf, pred = probs.max(dim=-1)
    digits = "".join(str(int(d)) for d in pred)
    min_conf = float(conf.min())
    value = int(digits) if len(digits) == 9 and digits.isdigit() else None
    # Optional CONSTRAINED decode: pass ?anchor=<lock>&ceil=<counts>. Returns the
    # most-likely 9-digit value WITHIN the physically-plausible window
    # [anchor, anchor+ceil] — rescues glare frames the free argmax collapses
    # (proven: 0% -> 100% in-window on live frames). Read-only extra field; the
    # raw digits/value/conf are unchanged so existing callers are unaffected.
    constrained_value = None
    try:
        anchor = request.args.get("anchor", type=int)
        ceil = request.args.get("ceil", type=int, default=300)
        if anchor is not None and ceil is not None and 0 <= ceil <= 40000:
            constrained_value = _constrained_decode(
                probs.numpy(), anchor, anchor + ceil)
    except Exception:
        constrained_value = None
    return jsonify({
        "ok": value is not None,
        "value": value,
        "digits": digits,
        "min_conf": round(min_conf, 3),
        "per_digit_conf": [round(float(c), 3) for c in conf],
        "confidence": "high" if min_conf >= CONF_THRESHOLD else "low",
        "readable": min_conf >= CONF_THRESHOLD,
        "constrained_value": constrained_value,
        "constrained_digits": (f"{constrained_value:09d}"
                               if constrained_value is not None else None),
        "version": _model_version(),
        "ms": int((time.time()-t0)*1000),
    })


@app.route("/health")
def health():
    ok = os.path.exists(WEIGHTS)
    return jsonify({"ok": ok, "model": WEIGHTS, "threshold": CONF_THRESHOLD,
                    "version": _model_version(), "in": [IN_H, IN_W]})


if __name__ == "__main__":
    get_model()
    app.run(host="0.0.0.0", port=int(os.environ.get("METER_CNN_PORT", "5201")))
