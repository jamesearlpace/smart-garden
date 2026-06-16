#!/usr/bin/env python3
"""Audit + quarantine POISONED training labels using meter monotonicity.

The training set is our ground truth, but OCR/ratchet bugs banked some frames
with wrong labels — too HIGH (ratcheting bug) or too LOW (glare misread). A water
meter is a cumulative odometer: true readings, ordered by capture time, must be
NON-DECREASING. So the largest set of labels that forms a non-decreasing sequence
in time is the trustworthy "backbone"; every label OFF that backbone is
inconsistent with the physics and is an outlier.

Algorithm: Longest Non-Decreasing Subsequence (LNDS) over (time, label). O(n log
n). Robust to BOTH false-highs and false-lows — a single bad reading can't
invalidate the rest (unlike a naive running-min/max envelope). Points not on the
LNDS are flagged.

Filenames embed the label + capture epoch: <9digit>_<epoch_ms>[_oracle].jpg

Default DRY-RUN. --apply moves flagged jpg+json into <dir>-quarantine/
(reversible — nothing deleted).
"""
import argparse
import bisect
import os
import re
import shutil

NAME_RE = re.compile(r"^(\d{9})_(\d+)(?:_oracle)?\.jpg$")


def lnds_keep_mask(values):
    """Return a boolean list: True = on a longest non-decreasing subsequence.

    Patience algorithm with reconstruction. Allows equal values (<=).
    """
    n = len(values)
    if n == 0:
        return []
    tails = []          # tails[k] = index ending an LNDS of length k+1
    tails_vals = []     # values at those tail indices (non-decreasing)
    prev = [-1] * n     # predecessor index for reconstruction
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/home/jamesearlpace/meter-training")
    ap.add_argument("--apply", action="store_true",
                    help="actually move flagged files (default: dry-run)")
    args = ap.parse_args()

    frames = []
    for f in os.listdir(args.dir):
        m = NAME_RE.match(f)
        if m:
            frames.append((int(m.group(2)), int(m.group(1)), f))  # epoch, val, file
    frames.sort()  # by epoch ascending
    if not frames:
        print("no frames found")
        return

    values = [v for _, v, _ in frames]
    keep = lnds_keep_mask(values)
    flagged = [(frames[i][0], frames[i][1], frames[i][2])
               for i in range(len(frames)) if not keep[i]]

    kept_n = sum(keep)
    print(f"Scanned {len(frames)} frames. Backbone (monotonic-consistent): "
          f"{kept_n}. Flagged outliers: {len(flagged)}.\n")
    for epoch, val, f in flagged:
        print(f"  {f:<44} label={val:09d}")
    if not flagged:
        print("  (none — all labels are monotonically consistent)")
        return

    qdir = args.dir.rstrip("/") + "-quarantine"
    if args.apply:
        os.makedirs(qdir, exist_ok=True)
        moved = 0
        for _, _, f in flagged:
            for ext in (".jpg", ".json"):
                src = os.path.join(args.dir, f[:-4] + ext)
                if os.path.exists(src):
                    shutil.move(src, os.path.join(qdir, os.path.basename(src)))
                    moved += 1
        print(f"\nAPPLIED: moved {moved} files into {qdir}")
    else:
        print(f"\nDRY-RUN: re-run with --apply to move these into {qdir} "
              "(reversible; nothing deleted).")


if __name__ == "__main__":
    main()
