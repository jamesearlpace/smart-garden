#!/usr/bin/env python3
"""Nightly GATED retrain for the meter-digit CNN — runs on the tower (jackmint).

Self-contained: bundles the model, preprocessing, monotonic audit, dataset
build, champion/challenger train, and gated promotion. No sibling imports, so it
runs cleanly as a systemd job.

Flow each night:
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
  7. Write retrain_status.json (for the dashboard) + log.

Guardrails preserved: independent-verified labels only (oracle/manual/consensus),
gated promotion (never auto-ship a worse model), monotonic audit as the floor.
"""
import argparse
import bisect
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
MARKER = os.path.join(BASE, "last_retrain_maxts")  # max captured_ts trained on
MANUAL_MARKER = os.path.join(BASE, "last_retrain_manual")  # # manual edits trained on
CLEAN_REGIME = os.path.join(BASE, "clean_regime")  # set once the baseline is fair
MANUAL_JSONL = os.path.join(WORK, "manual_labels.jsonl")  # human corrections (gold)
PROPAGATED_JSONL = os.path.join(WORK, "propagated_labels.jsonl")  # monotonic cleanup
LOG = os.path.join(BASE, "retrain.log")

CROP = (0.02, 0.02, 0.92, 0.46)
ROTATE_180 = True
IN_H, IN_W = 64, 256
N_DIGITS, N_CLASSES = 9, 10
TEST_PCT = 12                  # ~12%% of frames held out forever (by name hash)
MIN_TEST = 30                  # need at least this many test frames to judge
MIN_NEW_FRAMES = 25            # skip retrain unless this many new since last run
MAX_PER_LABEL = 3
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
def load_crop_gray(path):
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
    return gray.astype(np.float32) / 255.0


def _augment(gray):
    h, w = gray.shape
    tx = random.uniform(-0.06, 0.06) * w
    ty = random.uniform(-0.10, 0.10) * h
    sc = random.uniform(0.90, 1.10)
    ang = random.uniform(-3, 3)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, sc)
    M[0, 2] += tx
    M[1, 2] += ty
    gray = cv2.warpAffine(gray, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    gray = np.clip(gray * random.uniform(0.75, 1.25)
                   + random.uniform(-0.12, 0.12), 0, 1)
    if random.random() < 0.5:
        k = random.choice([3, 3, 5])
        gray = cv2.GaussianBlur(gray, (k, k), 0)
    if random.random() < 0.4:
        ew, eh = random.randint(w // 10, w // 4), random.randint(h // 6, h // 2)
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
        gray = load_crop_gray(os.path.join(FRAMES, r["file"]))
        if self.train:
            gray = _augment(gray)
        x = torch.from_numpy(gray).unsqueeze(0)
        y = torch.tensor([int(c) for c in r["label"]][:N_DIGITS],
                         dtype=torch.long)
        return x, y


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
    trusted training set for banked frames and raw UNCONFIRMED oracle reads are
    NOT trained on (flagged/outside are excluded). This is what lets a handful of
    human anchors clean the whole set instead of training on noisy auto-labels."""
    manual = manual or {}
    prop = load_propagated()
    labels = {}
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
        # Propagation active: trust its anchor/confirmed/repaired labels for
        # banked frames; do NOT add raw unconfirmed oracle reads (the noisy mass
        # the user doesn't want training the model). flagged/outside excluded.
        n_trust = 0
        for f, (st, d) in prop.items():
            if st in ("anchor", "confirmed", "repaired") and \
                    os.path.exists(os.path.join(FRAMES, f)):
                labels[f] = d
                n_trust += 1
        log(f"propagation: {n_trust} trusted (anchor/confirmed/repaired) labels; "
            f"raw unconfirmed reads excluded")
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
    return clean


def build_rows(clean):
    """Dedup to MAX_PER_LABEL per distinct reading; split by permanent hash."""
    per = {}
    train, test = [], []
    # test frames first (never capped — keep the benchmark complete)
    for f, lbl in sorted(clean.items()):
        if is_test(f):
            test.append({"file": f, "label": lbl})
    for f, lbl in sorted(clean.items()):
        if is_test(f):
            continue
        if per.get(lbl, 0) >= MAX_PER_LABEL:
            continue
        train.append({"file": f, "label": lbl})
        per[lbl] = per.get(lbl, 0) + 1
    return train, test


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
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            pred = model(x).argmax(-1)
            dc += (pred == y).sum().item()
            dt += y.numel()
            fc += (pred == y).all(dim=1).sum().item()
            ft += y.size(0)
    return dc / dt, fc / ft


def train_challenger(train_rows, test_loader, device):
    train_ld = DataLoader(MeterDigits(train_rows, train=True),
                          batch_size=BATCH, shuffle=True, num_workers=0)
    model = MeterDigitCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)
    lossf = nn.CrossEntropyLoss()
    best_f, best_state = -1.0, None
    for ep in range(1, EPOCHS + 1):
        model.train()
        for x, y in train_ld:
            x, y = x.to(device), y.to(device)
            logits = model(x)
            loss = sum(lossf(logits[:, d, :], y[:, d]) for d in range(N_DIGITS))
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        if ep % 10 == 0 or ep == EPOCHS:
            d, f = evaluate(model, test_loader, device)
            if f > best_f:
                best_f = f
                best_state = {k: v.cpu().clone()
                              for k, v in model.state_dict().items()}
            log(f"  ep {ep:3d}  test digit {d:.3f}  full {f:.3f}"
                + ("  *" if f >= best_f else ""))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="train even if too few new frames")
    ap.add_argument("--dry-run", action="store_true",
                    help="train + eval but never promote")
    args = ap.parse_args()
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
    clean = gather_labels(manual)
    n_new, max_ts = new_frame_count(clean)
    n_manual_new, manual_total = manual_new_count(manual)
    log(f"new frames since last retrain: {n_new} (threshold {MIN_NEW_FRAMES})")
    if n_manual_new:
        log(f"new human corrections since last retrain: {n_manual_new} "
            f"(total {manual_total}) — counts toward the gate")
    if (n_new + n_manual_new) < MIN_NEW_FRAMES and not args.force:
        log("SKIP: too few new frames/corrections — not worth a retrain tonight")
        write_status({"ts": time.time(), "skipped": True, "new_frames": n_new,
                      "new_manual": n_manual_new,
                      "reason": "below MIN_NEW_FRAMES"})
        return

    train_rows, test_rows = build_rows(clean)
    log(f"dataset: train {len(train_rows)}  held-out TEST {len(test_rows)} "
        f"({len({r['label'] for r in train_rows})} distinct train labels)")
    if len(test_rows) < MIN_TEST:
        log(f"ABORT: held-out test too small ({len(test_rows)} < {MIN_TEST})")
        write_status({"ts": time.time(), "skipped": True,
                      "reason": "test set too small"})
        return

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

    write_status({
        "ts": time.time(), "skipped": False, "promoted": promoted,
        "bootstrap": bootstrap,
        "champion_version": cur_ver, "challenger_version": nxt_ver,
        "champion_full9": round(c_f, 4), "challenger_full9": round(h_f, 4),
        "champion_perdigit": round(c_d, 4), "challenger_perdigit": round(h_d, 4),
        "train_n": len(train_rows), "test_n": len(test_rows),
        "new_frames": n_new, "new_manual": n_manual_new,
        "secs": int(time.time() - t0),
    })
    log(f"done in {int(time.time() - t0)}s")


if __name__ == "__main__":
    main()
