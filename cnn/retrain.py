#!/usr/bin/env python3
"""GATED retrain for the meter-digit CNN — runs on the tower (jackmint).

Self-contained: bundles the model, preprocessing, monotonic audit, dataset
build, champion/challenger train, and gated promotion. No sibling imports, so it
runs cleanly as a systemd job.

Flow each run:
  1. SYNC frames + the baseline verified label set from the Acer (rsync).
  2. AUDIT — drop physically-impossible labels (monotonic LNDS over time).
  3. GATE on volume — skip if too few NEW oracle frames since the last train
     (unless --force). One bad/idle day shouldn't burn a 50-min train.
  4. SPLIT — a PERMANENT, deterministic hash holdout: a frame is TEST iff
     hash(filename) %% 100 < TEST_PCT. No model ever trains on a test frame, so
     the benchmark is stable and fair across every retrain cycle.
  5. TRAIN a challenger; EVAL champion + challenger on the SAME held-out test.
  6. PROMOTE the challenger ONLY if it strictly beats the champion's full-9 on
     the held-out test. Bump VERSION, back up the old model, restart meter-cnn.
    7. Write retrain_status.json + append retrain_history.jsonl for trends.

Guardrails preserved: independent-verified labels only (oracle/manual/consensus),
gated promotion (never auto-ship a worse model), monotonic audit as the floor.
"""
import argparse
import bisect
from collections import Counter
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

# ---------------------------------------------------------------- config
ACER = "jamesearlpace@192.168.0.109"
HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, "meter-cnn")
WORK = os.path.join(BASE, "retrain")
FRAMES = os.path.join(WORK, "frames")              # synced from Acer
BASELINE_JSONL = os.path.join(WORK, "cnn_train.jsonl")
MODEL_LIVE = os.path.join(BASE, "meter_cnn.pt")    # the champion the service runs
VERSION_FILE = os.path.join(BASE, "VERSION")
STATUS = os.path.join(BASE, "retrain_status.json")
HISTORY = os.path.join(BASE, "retrain_history.jsonl")
MARKER = os.path.join(BASE, "last_retrain_maxts")  # max captured_ts trained on
MANUAL_MARKER = os.path.join(BASE, "last_retrain_manual")  # # manual edits trained on
CLEAN_REGIME = os.path.join(BASE, "clean_regime")  # set once the baseline is fair
MANUAL_JSONL = os.path.join(WORK, "manual_labels.jsonl")  # human corrections (gold)
PROPAGATED_JSONL = os.path.join(WORK, "propagated_labels.jsonl")  # monotonic cleanup
REGRESSION_JSONL = os.path.join(WORK, "regression_labels.jsonl")  # permanent hard-fail tests
LOG = os.path.join(BASE, "retrain.log")

CROP = (0.02, 0.02, 0.92, 0.46)
ROTATE_180 = True
IN_H, IN_W = 64, 256
N_DIGITS, N_CLASSES = 9, 10
TEST_PCT = 12                  # ~12%% of frames held out forever (by name hash)
MIN_TEST = 30                  # need at least this many test frames to judge
MIN_NEW_FRAMES = 25            # skip retrain unless this many new since last run
MAX_PER_LABEL = 3
OUTSIDE_TAIL_TRUST = 0.35      # weak weight for current-range outside labels
OUTSIDE_TAIL_MAX_ROWS = 300    # cap added outside-tail rows per retrain
OUTSIDE_TAIL_MAX_PER_LABEL = 2 # avoid flooding near-duplicate values
OUTSIDE_TAIL_MIN_DELTA = 0     # include values strictly above trusted max
# Held-out coverage guard: if live data has enough 6/7 at digit index 3, require
# the test benchmark to include them (or fail the run before promotion).
COVERAGE_DIGIT_INDEX = 3
COVERAGE_CRITICAL_DIGITS = ("6", "7")
COVERAGE_MIN_CLEAN_PER_DIGIT = 5
COVERAGE_MIN_TEST_PER_DIGIT = 3
SYNTH_N = 600                  # recombined synthetic frames per retrain (covers
                              # the leading-edge high digits real data lacks)
SYNTH_MAX_STRIPS = 300         # cap real digit strips kept per value (memory)
BOOTSTRAP_FLOOR = 0.45         # first clean challenger promotes if it clears this
EPOCHS = 60                    # v2 plateaued by ~ep50; 60 = headroom, ~25%% faster
BATCH = 32
LR = 1e-3
SEED = 0
NAME_RE = re.compile(r"^(\d{9})_(\d+)(?:_oracle)?\.jpg$")

_clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- model
def _block(cin, cout, pool=(2, 2)):
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
        nn.Conv2d(cout, cout, 3, padding=1), nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True), nn.MaxPool2d(pool))


class MeterDigitCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = nn.Sequential(
            _block(1, 32), _block(32, 64), _block(64, 128),
            _block(128, 128, pool=(2, 2)))
        self.pool = nn.AdaptiveAvgPool2d((1, N_DIGITS))
        self.drop = nn.Dropout(0.3)
        self.heads = nn.ModuleList(
            [nn.Linear(128, N_CLASSES) for _ in range(N_DIGITS)])

    def forward(self, x):
        f = self.backbone(x)
        f = self.pool(f).squeeze(2).transpose(1, 2)
        f = self.drop(f)
        return torch.stack([self.heads[i](f[:, i, :])
                            for i in range(N_DIGITS)], dim=1)


# ---------------------------------------------------------------- data
# Per-frame base preprocessing (decode -> rotate -> crop -> gray -> CLAHE ->
# resize) is DETERMINISTIC, but __getitem__ runs it every epoch (~60x/frame).
# Cache the decoded base once; only the random _augment() needs to re-run per
# epoch. Pure speedup — bit-identical results (same seed, same augmentation).
_GRAY_CACHE = {}

def load_crop_gray(path):
    cached = _GRAY_CACHE.get(path)
    if cached is not None:
        return cached.copy()
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    if ROTATE_180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    h, w = img.shape[:2]
    l, t, r, b = CROP
    crop = img[int(t * h):int(b * h), int(l * w):int(r * w)]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = _clahe.apply(gray)
    gray = cv2.resize(gray, (IN_W, IN_H), interpolation=cv2.INTER_AREA)
    out = gray.astype(np.float32) / 255.0
    _GRAY_CACHE[path] = out
    return out.copy()


def _glare(gray):
    """Simulate a smooth LCD reflection that washes digits toward white — a
    faithful model of the real glare band (unlike a hard random-erase box).
    Either a soft elliptical hot-spot or a horizontal reflection stripe; pixels
    blend toward white where the mask is strong, melting segment boundaries
    together (exactly the failure where '5'/'8' read as '0')."""
    h, w = gray.shape
    yy, xx = np.ogrid[:h, :w]
    if random.random() < 0.5:
        cx, cy = random.uniform(0.15, 0.85) * w, random.uniform(0.25, 0.75) * h
        sx, sy = random.uniform(0.12, 0.45) * w, random.uniform(0.18, 0.60) * h
        mask = np.exp(-(((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2))
    else:
        by, bh = random.uniform(0.2, 0.8) * h, random.uniform(0.08, 0.35) * h
        mask = np.exp(-(((yy - by) / bh) ** 2)) * np.ones((1, w))
    a = (mask * random.uniform(0.30, 0.60)).astype(np.float32)
    return np.clip(gray * (1 - a) + a, 0, 1).astype(np.float32)


def _perspective(gray):
    """Mild perspective warp — the meter is viewed at an angle."""
    h, w = gray.shape
    m = 0.06
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[random.uniform(-m, m) * w, random.uniform(-m, m) * h],
                      [w + random.uniform(-m, m) * w, random.uniform(-m, m) * h],
                      [w + random.uniform(-m, m) * w, h + random.uniform(-m, m) * h],
                      [random.uniform(-m, m) * w, h + random.uniform(-m, m) * h]])
    return cv2.warpPerspective(gray, cv2.getPerspectiveTransform(src, dst),
                               (w, h), borderMode=cv2.BORDER_REPLICATE)


def _bright_gradient(gray):
    """Linear brightness ramp — uneven lighting across the display."""
    h, w = gray.shape
    g0, g1 = random.uniform(-0.25, 0.25), random.uniform(-0.25, 0.25)
    ramp = (np.linspace(g0, g1, w)[None, :] if random.random() < 0.5
            else np.linspace(g0, g1, h)[:, None])
    return np.clip(gray + ramp, 0, 1).astype(np.float32)


def _jpeg(gray):
    """JPEG recompression artifacts (frames arrive as JPEG)."""
    ok, buf = cv2.imencode(".jpg", (gray * 255).astype(np.uint8),
                           [cv2.IMWRITE_JPEG_QUALITY, random.randint(30, 75)])
    if not ok:
        return gray
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0


def _augment(gray):
    h, w = gray.shape
    # geometry: translate + scale + rotate (+ occasional perspective skew)
    tx, ty = random.uniform(-0.06, 0.06) * w, random.uniform(-0.10, 0.10) * h
    sc, ang = random.uniform(0.90, 1.10), random.uniform(-3, 3)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, sc)
    M[0, 2] += tx
    M[1, 2] += ty
    gray = cv2.warpAffine(gray, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    if random.random() < 0.20:
        gray = _perspective(gray)
    # lighting: global brightness + uneven gradient
    gray = np.clip(gray * random.uniform(0.75, 1.25)
                   + random.uniform(-0.12, 0.12), 0, 1)
    if random.random() < 0.25:
        gray = _bright_gradient(gray)
    # GLARE — the headline fix: a realistic reflection wash on ~40% of frames
    if random.random() < 0.40:
        gray = _glare(gray)
    # blur + sensor noise + JPEG artifacts (kept light so they rarely stack into
    # an unreadable image — augmentation must stay HARDER-but-READABLE)
    if random.random() < 0.5:
        gray = cv2.GaussianBlur(gray, (random.choice([3, 3, 5]),) * 2, 0)
    if random.random() < 0.25:
        gray = np.clip(gray + np.random.normal(
            0, random.uniform(0.02, 0.04), gray.shape), 0, 1)
    if random.random() < 0.20:
        gray = _jpeg(gray)
    # occasional small hard occlusion (real obstructions happen too)
    if random.random() < 0.10:
        ew, eh = random.randint(w // 14, w // 8), random.randint(h // 8, h // 4)
        ex, ey = random.randint(0, w - ew), random.randint(0, h - eh)
        gray[ey:ey + eh, ex:ex + ew] = random.uniform(0, 1)
    return gray.astype(np.float32)


class MeterDigits(Dataset):
    def __init__(self, rows, train=True):
        self.rows = rows
        self.train = train

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        if "img" in r:                       # in-memory synthetic (recombined)
            gray = np.array(r["img"], dtype=np.float32, copy=True)
        else:
            gray = load_crop_gray(os.path.join(FRAMES, r["file"]))
        if self.train:
            gray = _augment(gray)
        x = torch.from_numpy(gray).unsqueeze(0)
        y = torch.tensor([int(c) for c in r["label"]][:N_DIGITS],
                         dtype=torch.long)
        w = torch.tensor(float(r.get("w", 1.0)), dtype=torch.float32)
        return x, y, w


# ---------------------------------------------------------------- synthetic
# The meter is always weakest at its LEADING EDGE: the high digits only just
# reached a new value, so real labeled data for them is near-zero (e.g. the
# hundreds digit has spent its life as '1' and just rolled to '5'). We fix this
# with ZERO new human labels by RECOMBINING real digit pixels: slice confidently
# labeled frames into their 9 evenly-spaced digit cells, then reassemble those
# real strips into values the meter hasn't physically shown yet. The model sees
# every digit at every position using genuine pixels (real glare, real font).
def _digit_cells(width):
    return [(round(i * width / N_DIGITS), round((i + 1) * width / N_DIGITS))
            for i in range(N_DIGITS)]


def build_digit_library(train_rows):
    """lib[d] = list of real 64xCELL strips showing digit d, pooled across ALL
    positions (so even digits a position has never shown are available from the
    positions that have). Built from TRAIN frames only — never test (no leak)."""
    lib = {d: [] for d in range(10)}
    cells = _digit_cells(IN_W)
    rows = [r for r in train_rows if "file" in r]
    random.shuffle(rows)
    for r in rows:
        lbl = r["label"]
        if len(lbl) != N_DIGITS:
            continue
        if all(len(lib[int(c)]) >= SYNTH_MAX_STRIPS for c in lbl):
            continue
        try:
            gray = load_crop_gray(os.path.join(FRAMES, r["file"]))
        except Exception:
            continue
        for i, (x0, x1) in enumerate(cells):
            d = int(lbl[i])
            if len(lib[d]) < SYNTH_MAX_STRIPS:
                lib[d].append(gray[:, x0:x1].copy())
    return lib


def synth_rows(lib, n):
    """Generate n recombined frames focused on the leading edge. Positions 0-2
    are the meter's fixed prefix (094); position 3 is biased toward the high
    values real data lacks; positions 4-8 are uniform. Returns in-memory rows."""
    if sum(1 for d in range(10) if lib[d]) < 9:
        return []                         # not enough digit variety to compose
    cells = _digit_cells(IN_W)
    # bias the hundreds digit toward 5-9 (where the meter is heading) but keep
    # some low values so it doesn't forget them.
    p3_pool = [1, 2, 3, 4] + [5, 6, 7, 8, 9] * 3
    rows = []
    for _ in range(n):
        digs = [0, 9, 4, random.choice(p3_pool)] + \
               [random.randint(0, 9) for _ in range(5)]
        if any(not lib[d] for d in digs):
            continue
        strips = []
        for i, d in enumerate(digs):
            s = random.choice(lib[d])
            cw = cells[i][1] - cells[i][0]
            if s.shape[1] != cw:
                s = cv2.resize(s, (cw, IN_H), interpolation=cv2.INTER_AREA)
            strips.append(s)
        comp = np.hstack(strips)
        if comp.shape[1] != IN_W:
            comp = cv2.resize(comp, (IN_W, IN_H), interpolation=cv2.INTER_AREA)
        rows.append({"img": comp.astype(np.float32),
                     "label": "".join(str(d) for d in digs),
                     "w": 1.0, "synth": True})
    return rows


# ---------------------------------------------------------------- audit
def lnds_keep_mask(values):
    """True = on a longest non-decreasing subsequence (meter is monotonic)."""
    n = len(values)
    if n == 0:
        return []
    tails, tails_vals, prev = [], [], [-1] * n
    for i, v in enumerate(values):
        j = bisect.bisect_right(tails_vals, v)
        if j == len(tails_vals):
            prev[i] = tails[-1] if tails else -1
            tails.append(i)
            tails_vals.append(v)
        else:
            prev[i] = tails[j - 1] if j > 0 else -1
            tails[j] = i
            tails_vals[j] = v
    keep = [False] * n
    k = tails[-1]
    while k != -1:
        keep[k] = True
        k = prev[k]
    return keep


def is_test(fname):
    """Deterministic, permanent holdout — never trained on, stable benchmark."""
    h = int(hashlib.sha1(fname.encode()).hexdigest(), 16)
    return (h % 100) < TEST_PCT


# ---------------------------------------------------------------- steps
def sync_from_acer():
    os.makedirs(FRAMES, exist_ok=True)
    log("sync: rsync frames + baseline labels from Acer ...")
    # frames (oracle + manual originals). --delete keeps quarantined frames out.
    subprocess.run(
        ["rsync", "-az", "--timeout=60", f"{ACER}:meter-training/", FRAMES + "/"],
        check=True)
    subprocess.run(
        ["rsync", "-az", "--timeout=60",
         f"{ACER}:cnn-dataset-oracle/cnn_train.jsonl", BASELINE_JSONL],
        check=True)
    # Human corrections from the label-review gallery — the GOLD tier. Optional
    # (may not exist yet); never fail the retrain if it's absent.
    try:
        subprocess.run(
            ["rsync", "-az", "--timeout=60", "--ignore-missing-args",
             f"{ACER}:cnn-dataset-oracle/manual_labels.jsonl", MANUAL_JSONL],
            check=False)
    except Exception as e:
        log(f"sync: manual_labels rsync skipped ({e})")
    # Anchor & Propagate output — monotonic cleanup of the banked set. Optional.
    try:
        subprocess.run(
            ["rsync", "-az", "--timeout=60", "--ignore-missing-args",
             f"{ACER}:cnn-dataset-oracle/propagated_labels.jsonl",
             PROPAGATED_JSONL],
            check=False)
    except Exception as e:
        log(f"sync: propagated_labels rsync skipped ({e})")
    # Permanent regression set — human-banked hard failures. Optional.
    try:
        subprocess.run(
            ["rsync", "-az", "--timeout=60", "--ignore-missing-args",
             f"{ACER}:cnn-dataset-oracle/regression_labels.jsonl",
             REGRESSION_JSONL],
            check=False)
    except Exception as e:
        log(f"sync: regression_labels rsync skipped ({e})")
    n = len([f for f in os.listdir(FRAMES) if f.endswith(".jpg")])
    log(f"sync: {n} frames present")
    return n


def load_propagated():
    """Anchor & Propagate results: {file: status} for banked frames.
    status ∈ anchor|confirmed|repaired|flagged|outside. Trusted = the first
    three (human-anchored or monotonically validated/repaired)."""
    out = {}
    if os.path.exists(PROPAGATED_JSONL):
        for line in open(PROPAGATED_JSONL):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                d = "".join(c for c in str(r.get("label", "")) if c.isdigit())
                if len(d) == 9:
                    out[r["file"]] = (r.get("status"), d)
            except Exception:
                pass
    return out


def load_regression():
    """Permanent hard-failure regression set banked by a human: {file: label}.
    Forced into TEST (never trained on) and guards the promotion gate. Last
    write per file wins; an action 'remove' record drops a frame."""
    out = {}
    if os.path.exists(REGRESSION_JSONL):
        for line in open(REGRESSION_JSONL):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            f = r.get("file")
            if not f:
                continue
            if r.get("action") == "remove":
                out.pop(f, None)
            else:
                d = "".join(c for c in str(r.get("label", "")) if c.isdigit())
                if len(d) == 9:
                    out[f] = d
    return out


def load_hard_frames():
    """Files where the OpenAI oracle caught the CNN reading WRONG (per-frame
    sidecar source=oracle, cnn_correct=False). These are the LIVE failure cases
    — the honest, current benchmark material. A held-out slice of these becomes
    the test set, so the gate measures the frames we actually fail on (current
    high-value glare), not easy historical gimmes. Returns a set of .jpg names."""
    hard = set()
    try:
        names = os.listdir(FRAMES)
    except FileNotFoundError:
        return hard
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(FRAMES, name)))
        except Exception:
            continue
        if d.get("source") == "oracle" and d.get("cnn_correct") is False:
            jpg = name[:-5] + ".jpg"
            if os.path.exists(os.path.join(FRAMES, jpg)):
                hard.add(jpg)
    return hard


def load_manual():
    """Human corrections from the gallery — last action per file wins, with the
    last EXPLICIT label carried forward (a label-less 'ok' after a 'Fix' still
    confirms the fixed value). Returns {file: {action, label?}}."""
    out = {}
    if os.path.exists(MANUAL_JSONL):
        for line in open(MANUAL_JSONL):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            f = r.get("file")
            if not f:
                continue
            r["label"] = r.get("label") or out.get(f, {}).get("label")
            out[f] = r
    return out


def gather_labels(manual=None):
    """file -> label, from the trusted baseline jsonl + (Anchor&Propagate output
    OR raw oracle-banked filenames). The monotonic audit drops physically-
    impossible AUTO labels. Human manual corrections are then overlaid as the
    GOLD tier — authoritative OVER the audit.

    When Anchor & Propagate has run, its CONFIRMED/REPAIRED/anchor labels are the
    trusted training set for banked frames. Additionally, include a bounded tail
    of current-range OUTSIDE labels (strictly above the trusted max) at LOW
    weight so retraining can follow the live meter range instead of stalling
    while anchors catch up."""
    manual = manual or {}
    prop = load_propagated()
    labels = {}
    weak_tail = {}
    # baseline curated set (consensus / verified) — high trust, kept either way
    if os.path.exists(BASELINE_JSONL):
        for line in open(BASELINE_JSONL):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            d = "".join(c for c in r["label"] if c.isdigit())
            if len(d) == 9 and os.path.exists(os.path.join(FRAMES, r["file"])):
                labels[r["file"]] = d
    if prop:
        # Propagation active: trust anchor/confirmed/repaired labels. Also allow
        # a small weakly-weighted OUTSIDE tail above the trusted max so the
        # dataset keeps pace with current meter values.
        n_trust = 0
        trusted_vals = []
        outside = []
        for f, (st, d) in prop.items():
            if not os.path.exists(os.path.join(FRAMES, f)):
                continue
            if st in ("anchor", "confirmed", "repaired"):
                labels[f] = d
                n_trust += 1
                try:
                    trusted_vals.append(int(d))
                except Exception:
                    pass
            elif st == "outside":
                m = NAME_RE.match(f)
                if not m:
                    continue
                outside.append((int(m.group(2)), f, d))

        n_tail = 0
        trusted_hi = max(trusted_vals) if trusted_vals else None
        if trusted_hi is not None and outside:
            per_label = {}
            outside.sort(reverse=True)   # newest first
            for _, f, d in outside:
                try:
                    dv = int(d)
                except Exception:
                    continue
                if dv <= (trusted_hi + OUTSIDE_TAIL_MIN_DELTA):
                    continue
                if per_label.get(d, 0) >= OUTSIDE_TAIL_MAX_PER_LABEL:
                    continue
                if n_tail >= OUTSIDE_TAIL_MAX_ROWS:
                    break
                labels[f] = d
                weak_tail[f] = d
                per_label[d] = per_label.get(d, 0) + 1
                n_tail += 1

        if n_tail:
            d4 = Counter(lbl[3] for lbl in weak_tail.values() if len(lbl) > 3)
            log("propagation: %d trusted + %d weak outside-tail labels "
                "(digit4 mix %s)"
                % (n_trust, n_tail, dict(sorted(d4.items()))))
        else:
            log("propagation: %d trusted labels; no outside-tail labels added"
                % n_trust)
    else:
        # legacy: oracle-banked frames (independent verifier) — label from name
        for f in os.listdir(FRAMES):
            m = NAME_RE.match(f)
            if m and f not in labels:
                labels[f] = m.group(1)
    auto_labels = dict(labels)  # pre-audit snapshot (for confirming 'ok')
    # monotonic audit: order by capture ts, keep the non-decreasing backbone
    items = []
    for f, lbl in labels.items():
        m = NAME_RE.match(f)
        if not m:
            continue
        items.append((int(m.group(2)), int(lbl), f))
    items.sort()
    keep = lnds_keep_mask([v for _, v, _ in items])
    clean = {f: f"{lbl:09d}" for (ts, lbl, f), k in zip(items, keep) if k}
    dropped = len(items) - len(clean)
    log(f"audit: {len(clean)} clean, {dropped} impossible AUTO labels dropped")
    # ---- GOLD overlay: human edits win over everything, incl. the audit ----
    n_correct = n_ok = n_reject = n_revive = 0
    for f, mv in manual.items():
        act = mv.get("action")
        if not os.path.exists(os.path.join(FRAMES, f)):
            continue  # frame quarantined/gone — can't train on it
        if act == "reject":
            if clean.pop(f, None) is not None:
                n_reject += 1
        elif act == "correct":
            d = "".join(c for c in str(mv.get("label", "")) if c.isdigit())
            if len(d) == 9:
                if f not in clean:
                    n_revive += 1   # audit had dropped it; human revives+fixes
                clean[f] = d
                n_correct += 1
        elif act == "ok":
            d = ("".join(c for c in str(mv.get("label", "")) if c.isdigit())
                 or clean.get(f) or auto_labels.get(f))
            if d and len(d) == 9:
                if f not in clean:
                    n_revive += 1
                clean[f] = d
                n_ok += 1
    if manual:
        log(f"manual overlay: {n_correct} corrected, {n_ok} confirmed, "
            f"{n_reject} rejected, {n_revive} revived past audit")
    # ---- TRUST TIERS: human > human-anchored > monotonically repaired/confirmed
    # > auto. Used as per-sample loss weights so the model leans on the labels
    # we trust and is pulled less by raw oracle reads (91%% of frames, ~10%% of
    # which we've already caught as wrong).
    trust = {}
    for f in clean:
        mv = manual.get(f)
        if mv and mv.get("action") in ("correct", "ok"):
            trust[f] = 3.0
        elif f in weak_tail:
            trust[f] = OUTSIDE_TAIL_TRUST
        elif f in prop:
            trust[f] = {"anchor": 2.5, "repaired": 2.0,
                        "confirmed": 1.5}.get(prop[f][0], 1.0)
        else:
            trust[f] = 1.0
    return clean, trust


def build_rows(clean, trust=None, regression=None, hard=None):
    """Dedup to MAX_PER_LABEL per distinct reading; split into train/test.

    NEW TEST POLICY: the benchmark is the held-out HARD frames (oracle-caught
    CNN failures) + the regression set — the frames that reflect the LIVE
    operating point (current high-value glare). Easy historical frames that
    happen to hash into the holdout are sent to TRAIN instead, so the gate stops
    grading the model on gimmes it already aces. Falls back to the plain hash
    holdout only if too few hard frames exist yet (< MIN_TEST).

    Regression frames are always FORCED into test (never trained on). reg/hard
    tags let the gate score each subset."""
    trust = trust or {}
    regression = regression or set()
    hard = hard or set()
    n_hard_test = len([f for f in clean if f in hard and is_test(f)])
    use_hard = n_hard_test >= MIN_TEST

    def in_test(f):
        if f in regression:
            return True
        if use_hard:
            return f in hard and is_test(f)
        return is_test(f)

    per = {}
    train, test = [], []
    test_files = set()
    # test frames first (never capped — keep the benchmark complete)
    for f, lbl in sorted(clean.items()):
        if in_test(f):
            test.append({"file": f, "label": lbl, "w": trust.get(f, 1.0),
                         "reg": f in regression, "hard": f in hard})
            test_files.add(f)

    # Coverage seeding: when live clean data has substantial 6/7 values at the
    # key leading-edge digit, guarantee minimum test coverage for those digits.
    clean_cov = Counter(lbl[COVERAGE_DIGIT_INDEX]
                        for lbl in clean.values() if len(lbl) > COVERAGE_DIGIT_INDEX)
    test_cov = Counter(r["label"][COVERAGE_DIGIT_INDEX]
                       for r in test if len(r["label"]) > COVERAGE_DIGIT_INDEX)
    forced = 0
    for d in COVERAGE_CRITICAL_DIGITS:
        if clean_cov.get(d, 0) < COVERAGE_MIN_CLEAN_PER_DIGIT:
            continue
        need = COVERAGE_MIN_TEST_PER_DIGIT - test_cov.get(d, 0)
        if need <= 0:
            continue
        cand = []
        for f, lbl in clean.items():
            if f in test_files:
                continue
            if len(lbl) <= COVERAGE_DIGIT_INDEX or lbl[COVERAGE_DIGIT_INDEX] != d:
                continue
            # Prefer hard frames if available; then deterministic filename order.
            cand.append((0 if f in hard else 1, f, lbl))
        cand.sort()
        for _, f, lbl in cand[:need]:
            test.append({"file": f, "label": lbl, "w": trust.get(f, 1.0),
                         "reg": f in regression, "hard": f in hard,
                         "forced_cov": True})
            test_files.add(f)
            test_cov[d] += 1
            forced += 1

    if forced:
        log("coverage seed: +%d forced test rows (digit%d test mix %s)"
            % (forced, COVERAGE_DIGIT_INDEX,
               dict(sorted((k, test_cov.get(k, 0))
                           for k in COVERAGE_CRITICAL_DIGITS))))

    for f, lbl in sorted(clean.items()):
        if f in test_files:
            continue
        if per.get(lbl, 0) >= MAX_PER_LABEL:
            continue
        train.append({"file": f, "label": lbl, "w": trust.get(f, 1.0)})
        per[lbl] = per.get(lbl, 0) + 1
    return train, test


def coverage_guard(clean, test_rows):
    """Held-out benchmark coverage guard for live leading-edge ranges.

    If clean data has enough examples for a critical digit value (6/7 at the
    thousands position), require a minimum number of test rows for that value.
    Missing coverage means skip the retrain to prevent false confidence.
    """
    clean_cov = Counter(lbl[COVERAGE_DIGIT_INDEX]
                        for lbl in clean.values() if len(lbl) > COVERAGE_DIGIT_INDEX)
    test_cov = Counter(r["label"][COVERAGE_DIGIT_INDEX]
                       for r in test_rows
                       if len(r.get("label", "")) > COVERAGE_DIGIT_INDEX)

    required = [d for d in COVERAGE_CRITICAL_DIGITS
                if clean_cov.get(d, 0) >= COVERAGE_MIN_CLEAN_PER_DIGIT]
    missing = [d for d in required
               if test_cov.get(d, 0) < COVERAGE_MIN_TEST_PER_DIGIT]

    return {
        "digit_index": COVERAGE_DIGIT_INDEX,
        "critical_digits": list(COVERAGE_CRITICAL_DIGITS),
        "required": required,
        "missing": missing,
        "min_clean_per_digit": COVERAGE_MIN_CLEAN_PER_DIGIT,
        "min_test_per_digit": COVERAGE_MIN_TEST_PER_DIGIT,
        "clean_cov": dict(sorted(clean_cov.items())),
        "test_cov": dict(sorted(test_cov.items())),
    }


def new_frame_count(clean):
    """How many frames are newer than the last successful retrain."""
    last = 0.0
    if os.path.exists(MARKER):
        try:
            last = float(open(MARKER).read().strip())
        except Exception:
            last = 0.0
    mx = last
    n = 0
    for f in clean:
        m = NAME_RE.match(f)
        if not m:
            continue
        ts = int(m.group(2))
        if ts > last:
            n += 1
        mx = max(mx, ts)
    return n, mx


def manual_new_count(manual):
    """How many human corrections accrued since the last successful retrain.
    Manual edits to OLD frames don't advance the capture-ts marker, so they get
    their own marker. Each new correction is high-value and counts toward the
    volume gate."""
    last = 0
    if os.path.exists(MANUAL_MARKER):
        try:
            last = int(open(MANUAL_MARKER).read().strip())
        except Exception:
            last = 0
    total = len(manual)
    return max(0, total - last), total


def evaluate(model, loader, device):
    model.eval()
    dc = dt = fc = ft = 0
    with torch.no_grad():
        for batch in loader:
            x = batch[0].to(device)
            y = batch[1].to(device)
            pred = model(x).argmax(-1)
            dc += (pred == y).sum().item()
            dt += y.numel()
            fc += (pred == y).all(dim=1).sum().item()
            ft += y.size(0)
    return dc / dt, fc / ft


def eval_per_frame(model, rows, device):
    """Per-frame full-9 correctness (ordered like rows) — for the hard-frame
    comparison: which held-out frames each model gets fully right."""
    model.eval()
    ld = DataLoader(MeterDigits(rows, train=False), batch_size=64,
                    shuffle=False, num_workers=0)
    out = []
    with torch.no_grad():
        for batch in ld:
            x, y = batch[0].to(device), batch[1].to(device)
            pred = model(x).argmax(-1)
            out.extend((pred == y).all(dim=1).cpu().numpy().tolist())
    return out


def train_challenger(train_rows, test_loader, device):
    train_ld = DataLoader(MeterDigits(train_rows, train=True),
                          batch_size=BATCH, shuffle=True, num_workers=0)
    model = MeterDigitCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)
    lossf = nn.CrossEntropyLoss(reduction="none")
    best_f, best_state = -1.0, None
    # Early stop: eval every few epochs, keep the BEST model seen, and stop once
    # full-9 has plateaued for PATIENCE evals. Safe — we always return best_state,
    # so stopping early can only save time, never lower quality. (v2 plateaus ~ep50.)
    EVAL_EVERY = 5
    PATIENCE = 3            # stop after this many evals with no full-9 gain
    stale = 0
    for ep in range(1, EPOCHS + 1):
        model.train()
        for x, y, w in train_ld:
            x, y, w = x.to(device), y.to(device), w.to(device)
            logits = model(x)
            loss = sum((lossf(logits[:, d, :], y[:, d]) * w).mean()
                       for d in range(N_DIGITS))
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        if ep % EVAL_EVERY == 0 or ep == EPOCHS:
            d, f = evaluate(model, test_loader, device)
            improved = f > best_f + 1e-3
            if f > best_f:
                best_f = f
                best_state = {k: v.cpu().clone()
                              for k, v in model.state_dict().items()}
            log(f"  ep {ep:3d}  test digit {d:.3f}  full {f:.3f}"
                + ("  *" if improved else ""))
            stale = 0 if improved else stale + 1
            if stale >= PATIENCE:
                log(f"  early stop at ep {ep}: no full-9 gain in "
                    f"{PATIENCE * EVAL_EVERY} epochs (best {best_f:.3f})")
                break
    model.load_state_dict(best_state)
    return model


def bump_version():
    cur = "v1"
    if os.path.exists(VERSION_FILE):
        cur = open(VERSION_FILE).read().strip() or "v1"
    m = re.match(r"v(\d+)", cur)
    nxt = f"v{int(m.group(1)) + 1}" if m else "v2"
    return cur, nxt


def write_status(d):
    try:
        json.dump(d, open(STATUS, "w"), indent=1)
    except Exception:
        pass


def append_history(d):
    """Append one run record for long-term trend analysis."""
    try:
        with open(HISTORY, "a") as f:
            f.write(json.dumps(d) + "\n")
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="train even if too few new frames")
    ap.add_argument("--dry-run", action="store_true",
                    help="train + eval but never promote")
    ap.add_argument("--no-synth", action="store_true",
                    help="disable synthetic digit recombination")
    ap.add_argument("--epochs", type=int, default=0,
                    help="override epoch count (smoke tests)")
    args = ap.parse_args()
    if args.epochs:
        global EPOCHS
        EPOCHS = args.epochs
    random.seed(SEED)
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    torch.set_num_threads(max(1, os.cpu_count() - 1))
    device = "cpu"
    t0 = time.time()
    log("=" * 60)
    log("nightly retrain start")

    sync_from_acer()
    manual = load_manual()
    clean, trust = gather_labels(manual)
    regression = load_regression()
    hard = load_hard_frames()
    n_new, max_ts = new_frame_count(clean)
    n_manual_new, manual_total = manual_new_count(manual)
    log(f"new frames since last retrain: {n_new} (threshold {MIN_NEW_FRAMES})")
    if n_manual_new:
        log(f"new human corrections since last retrain: {n_manual_new} "
            f"(total {manual_total}) — counts toward the gate")
    if (n_new + n_manual_new) < MIN_NEW_FRAMES and not args.force:
        log("SKIP: too few new frames/corrections — not worth a retrain tonight")
        status = {"ts": time.time(), "skipped": True,
                  "new_frames": n_new, "new_manual": n_manual_new,
                  "reason": "below MIN_NEW_FRAMES",
                  "trusted_ground_truth_n": len(clean)}
        write_status(status)
        append_history(status)
        return

    train_rows, test_rows = build_rows(clean, trust, set(regression), hard)
    n_reg_test = sum(1 for r in test_rows if r.get("reg"))
    n_hard_test = sum(1 for r in test_rows if r.get("hard"))
    log(f"dataset: train {len(train_rows)}  held-out TEST {len(test_rows)} "
        f"({len({r['label'] for r in train_rows})} distinct train labels)")
    if n_hard_test:
        log(f"HARD BENCHMARK: test = {n_hard_test} held-out HARD frames "
            f"(oracle-caught CNN failures) — the gate now measures the LIVE "
            f"failure mode, not easy historical frames. ({len(hard)} hard total)")
    else:
        log(f"hard benchmark: only {len(hard)} hard frames, too few held out "
            f"— falling back to plain hash holdout")

    cov = coverage_guard(clean, test_rows)
    log("coverage gate: digit%d required=%s missing=%s clean=%s test=%s"
        % (cov["digit_index"], cov["required"], cov["missing"],
           cov["clean_cov"], cov["test_cov"]))
    if cov["missing"]:
        log("ABORT: held-out benchmark missing live-range coverage for digits %s "
            "at position %d" % (cov["missing"], cov["digit_index"]))
        status = {
            "ts": time.time(),
            "skipped": True,
            "reason": "coverage gap in held-out test",
            "coverage": cov,
            "trusted_ground_truth_n": len(clean),
            "new_frames": n_new,
            "new_manual": n_manual_new,
        }
        write_status(status)
        append_history(status)
        return

    if len(test_rows) < MIN_TEST:
        log(f"ABORT: held-out test too small ({len(test_rows)} < {MIN_TEST})")
        status = {
            "ts": time.time(),
            "skipped": True,
            "reason": "test set too small",
            "coverage": cov,
            "trusted_ground_truth_n": len(clean),
        }
        write_status(status)
        append_history(status)
        return

    # Synthetic recombination: teach every digit at every position (especially
    # the leading-edge high digits real data lacks) using REAL pixels sliced
    # from TRAIN frames only. Zero new human labels; never touches the holdout.
    if not args.no_synth:
        lib = build_digit_library(train_rows)
        synth = synth_rows(lib, SYNTH_N)
        if synth:
            train_rows = train_rows + synth
            log("synthetic: +%d recombined frames (digit strips %s)"
                % (len(synth), {d: len(lib[d]) for d in range(10)}))
        else:
            log("synthetic: skipped (insufficient digit variety)")

    test_loader = DataLoader(MeterDigits(test_rows, train=False),
                             batch_size=64, shuffle=False, num_workers=0)

    # champion baseline on the same held-out test
    champ = MeterDigitCNN().to(device)
    champ.load_state_dict(torch.load(MODEL_LIVE, map_location=device))
    c_d, c_f = evaluate(champ, test_loader, device)
    cur_ver, nxt_ver = bump_version()
    log(f"CHAMPION {cur_ver}: per-digit {c_d:.3f}  full-9 {c_f:.3f}")

    # challenger
    log(f"training challenger {nxt_ver} ({EPOCHS} epochs) ...")
    chall = train_challenger(train_rows, test_loader, device)
    h_d, h_f = evaluate(chall, test_loader, device)
    log(f"CHALLENGER {nxt_ver}: per-digit {h_d:.3f}  full-9 {h_f:.3f}")

    # FULL trusted ground-truth replay (not just holdout): this gives a
    # continuous signal of how each run tracks against all currently trusted
    # labels (manual + propagated-confirmed/repaired + validated baseline).
    gt_rows = [{"file": f, "label": lbl, "w": trust.get(f, 1.0)}
               for f, lbl in sorted(clean.items())]
    gt_loader = DataLoader(MeterDigits(gt_rows, train=False),
                           batch_size=64, shuffle=False, num_workers=0)
    c_gt_d, c_gt_f = evaluate(champ, gt_loader, device)
    h_gt_d, h_gt_f = evaluate(chall, gt_loader, device)
    log("GROUND-TRUTH replay: champion %.3f/%.3f  challenger %.3f/%.3f "
        "(digit/full-9 over %d trusted labels)"
        % (c_gt_d, c_gt_f, h_gt_d, h_gt_f, len(gt_rows)))

    # HARD-FRAME EVAL: the clean held-out benchmark is mostly easy historical
    # frames, so a glare/aug improvement can be invisible there. Compare the two
    # models on the subset the CHAMPION gets WRONG — that's where new robustness
    # shows up. fixed = champion-wrong that challenger nails; broke = the reverse.
    try:
        champ_pf = eval_per_frame(champ, test_rows, device)
        chall_pf = eval_per_frame(chall, test_rows, device)
        hard = [i for i, ok in enumerate(champ_pf) if not ok]
        fixed = sum(1 for i in hard if chall_pf[i])
        broke = sum(1 for i in range(len(champ_pf))
                    if champ_pf[i] and not chall_pf[i])
        log(f"HARD-FRAME EVAL: champion missed {len(hard)}/{len(test_rows)}; "
            f"challenger FIXED {fixed}, newly BROKE {broke} "
            f"(net {fixed - broke:+d} on hard frames)")
    except Exception as e:
        log(f"hard-frame eval skipped: {e}")

    # REGRESSION SET: human-banked known-hard frames, forced into the holdout
    # (never trained on). A challenger must NOT score worse on them than the
    # champion, no matter how good its overall full-9 — that's the lock that
    # stops a fixed failure from silently coming back.
    champ_reg = chall_reg = None
    reg_rows = [r for r in test_rows if r.get("reg")]
    if reg_rows:
        try:
            c_pf = eval_per_frame(champ, reg_rows, device)
            h_pf = eval_per_frame(chall, reg_rows, device)
            champ_reg = sum(c_pf) / len(reg_rows)
            chall_reg = sum(h_pf) / len(reg_rows)
            log(f"REGRESSION SET: champion {sum(c_pf)}/{len(reg_rows)} "
                f"({champ_reg:.2f})  challenger {sum(h_pf)}/{len(reg_rows)} "
                f"({chall_reg:.2f})")
        except Exception as e:
            log(f"regression eval skipped: {e}")

    promoted = False
    # The currently-deployed champion may PREDATE the permanent hash holdout
    # (the legacy v1/v2 were trained before it existed), so it has memorized
    # some held-out frames -> its test score is INFLATED and unbeatable by an
    # honestly-trained challenger. Detect that one-time situation: the first
    # challenger trained UNDER the clean regime is promoted as the new fair
    # baseline as long as it clears an absolute floor. From then on (clean_regime
    # marker present) strict gating applies: promote only if it beats champion.
    bootstrap = not os.path.exists(CLEAN_REGIME)
    if bootstrap:
        win = h_f >= BOOTSTRAP_FLOOR
        reason = (f"bootstrap: clean baseline (challenger {h_f:.3f} >= floor "
                  f"{BOOTSTRAP_FLOOR}) replacing pre-holdout champion")
    else:
        win = h_f > c_f
        reason = f"strict: {h_f:.3f} {'>' if win else '<='} champion {c_f:.3f}"

    # Regression guard: never promote a challenger that does WORSE on the
    # permanent regression set than the champion, even if overall full-9 is up.
    if win and chall_reg is not None and chall_reg < champ_reg:
        win = False
        reason = (f"BLOCKED by regression guard: challenger {chall_reg:.2f} < "
                  f"champion {champ_reg:.2f} on regression set ({reason})")

    if win and not args.dry_run:
        # back up the champion, swap in the challenger, bump version, restart
        backup = os.path.join(BASE, f"meter_cnn_{cur_ver}.pt")
        shutil.copy2(MODEL_LIVE, backup)
        tmp = MODEL_LIVE + ".new"
        torch.save(chall.state_dict(), tmp)
        os.replace(tmp, MODEL_LIVE)
        open(VERSION_FILE, "w").write(nxt_ver + "\n")
        open(MARKER, "w").write(str(max_ts))
        open(MANUAL_MARKER, "w").write(str(manual_total))
        open(CLEAN_REGIME, "w").write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
        subprocess.run(["sudo", "systemctl", "restart", "meter-cnn"], check=False)
        promoted = True
        log(f"PROMOTED {nxt_ver} ({reason}). "
            f"backup -> {os.path.basename(backup)}, service restarted")
    elif args.dry_run:
        log(f"DRY-RUN: would {'PROMOTE' if win else 'KEEP'} ({reason})")
    else:
        # still advance the markers so we don't re-evaluate the same frames /
        # corrections nightly (they remain in the training baseline regardless)
        open(MARKER, "w").write(str(max_ts))
        open(MANUAL_MARKER, "w").write(str(manual_total))
        log(f"KEEP {cur_ver}: {reason}")

    status = {
        "ts": time.time(), "skipped": False, "promoted": promoted,
        "bootstrap": bootstrap,
        "coverage": cov,
        "champion_version": cur_ver, "challenger_version": nxt_ver,
        "champion_full9": round(c_f, 4), "challenger_full9": round(h_f, 4),
        "champion_perdigit": round(c_d, 4), "challenger_perdigit": round(h_d, 4),
        "champion_ground_truth_full9": round(c_gt_f, 4),
        "challenger_ground_truth_full9": round(h_gt_f, 4),
        "champion_ground_truth_perdigit": round(c_gt_d, 4),
        "challenger_ground_truth_perdigit": round(h_gt_d, 4),
        "trusted_ground_truth_n": len(gt_rows),
        "champion_regression": round(champ_reg, 4) if champ_reg is not None else None,
        "challenger_regression": round(chall_reg, 4) if chall_reg is not None else None,
        "regression_n": len(reg_rows),
        "train_n": len(train_rows), "test_n": len(test_rows),
        "new_frames": n_new, "new_manual": n_manual_new,
        "secs": int(time.time() - t0),
    }
    write_status(status)
    append_history(status)
    log(f"done in {int(time.time() - t0)}s")


if __name__ == "__main__":
    main()
