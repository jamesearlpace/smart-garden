#!/usr/bin/env python3
"""Anchor & Propagate — turn a few human-confirmed labels into clean labels for
the whole banked set, using the meter's monotonic physics. Fast, no AI calls.

Idea: the meter only counts UP and every frame is timestamped. A handful of
human-confirmed frames ("anchors") pin tight value-windows for every frame
between them. We then, per frame:
  • CONFIRM  banked labels that sit on the monotonic backbone within an anchor
             window (the anchors vouch for that stretch),
  • REPAIR   labels that violate monotonicity but whose true value is pinned by
             a tight neighbor window (e.g. meter flat between two equal anchors),
  • FLAG     the few whose window is too wide to resolve without re-reading.
Frames outside the human anchor span stay OUTSIDE (untrusted) until anchored.

Inputs (on the Acer):
  BANK_DIR frames   — <label>_<epoch_ms>[_oracle].jpg  (label = the banked read)
  manual_labels.jsonl — human anchors: action correct(value)/ok(confirm)/reject(drop)
Output:
  propagated_labels.jsonl — {file, label, status, was, ts} per resolved frame
  propagate_status.json   — summary counts

Trust for the retrain: anchor + confirmed + repaired = trusted; outside/flagged
are excluded (low trust). Human anchors always win.
"""
import argparse
import json
import os
import re
import time

BANK_DIR = os.environ.get("METER_BANK_DIR", "/home/jamesearlpace/meter-training")
LABELS_DIR = os.environ.get("METER_LABELS_DIR",
                            "/home/jamesearlpace/cnn-dataset-oracle")
MANUAL_PATH = os.path.join(LABELS_DIR, "manual_labels.jsonl")
OUT_PATH = os.path.join(LABELS_DIR, "propagated_labels.jsonl")
STATUS_PATH = os.path.join(LABELS_DIR, "propagate_status.json")

NAME_RE = re.compile(r"^(\d{9})_(\d+)(?:_oracle)?\.jpg$")
# A window this tight (counts) is treated as pinning the value — safe to repair.
SNAP_MAX = int(os.environ.get("METER_PROP_SNAP_MAX", "60"))


def _digits(v):
    return f"{v:09d}"


def _hamming(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


def _load_manual():
    """file -> {'action','label'} (last write per file wins)."""
    out = {}
    if os.path.exists(MANUAL_PATH):
        for line in open(MANUAL_PATH):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                out[r["file"]] = r
            except Exception:
                pass
    return out


def _load_frames():
    """list of {file, ts, banked} for every banked jpg."""
    frames = []
    try:
        names = os.listdir(BANK_DIR)
    except FileNotFoundError:
        return frames
    for name in names:
        m = NAME_RE.match(name)
        if not m:
            continue
        frames.append({"file": name, "ts": int(m.group(2)),
                       "banked": int(m.group(1))})
    return frames


def _lnds_mask(values):
    """True where value is on a longest NON-DECREASING subsequence."""
    import bisect
    n = len(values)
    if n == 0:
        return []
    tails, tails_i, prev = [], [], [-1] * n
    for i, v in enumerate(values):
        j = bisect.bisect_right(tails, v)
        if j == len(tails):
            prev[i] = tails_i[-1] if tails_i else -1
            tails.append(v)
            tails_i.append(i)
        else:
            prev[i] = tails_i[j - 1] if j > 0 else -1
            tails[j] = v
            tails_i[j] = i
    keep = [False] * n
    k = tails_i[-1]
    while k != -1:
        keep[k] = True
        k = prev[k]
    return keep


def _repair(banked, lo, hi):
    """Best monotonically-valid value in [lo, hi] for a violating frame.
    Returns (value, status). status ∈ confirmed|repaired|flagged."""
    if lo > hi:
        return banked, "flagged"            # contradictory anchors around it
    if lo <= banked <= hi:
        return banked, "confirmed"          # actually fits — keep it
    if hi - lo <= SNAP_MAX:
        # Window pins the value tightly — pick the in-window value closest to
        # the banked DIGITS (usually fixes one misread digit).
        bd = _digits(banked)
        best, bestd = lo, _hamming(_digits(lo), bd)
        # check both ends + the numeric clamp; cheap and covers flat/near-flat
        for cand in (lo, hi, max(lo, min(hi, banked))):
            d = _hamming(_digits(cand), bd)
            if d < bestd:
                best, bestd = cand, d
        return best, "repaired"
    return banked, "flagged"                # window too wide — needs a re-read


def propagate(snap_max=None):
    frames = _load_frames()
    manual = _load_manual()
    rejects = {f for f, mv in manual.items() if mv.get("action") == "reject"}
    anchors = {}
    for f, mv in manual.items():
        act = mv.get("action")
        if act == "correct":
            d = "".join(c for c in str(mv.get("label", "")) if c.isdigit())
            if len(d) == 9:
                anchors[f] = int(d)
        elif act == "ok":
            anchors[f] = None               # confirm the banked value (filled below)

    frames = [f for f in frames if f["file"] not in rejects]
    frames.sort(key=lambda f: f["ts"])
    n = len(frames)
    for f in frames:
        if f["file"] in anchors:
            a = anchors[f["file"]]
            f["val"] = f["banked"] if a is None else a
            f["anchor"] = True
        else:
            f["val"] = f["banked"]
            f["anchor"] = False

    # anchor positions (sorted by time) + non-decreasing validation
    apos = [(k, frames[k]["val"]) for k in range(n) if frames[k]["anchor"]]
    conflicts = []
    cleaned = []
    last = -1
    for k, v in apos:
        if v < last:
            conflicts.append({"file": frames[k]["file"], "val": _digits(v),
                              "below": _digits(last)})
            frames[k]["anchor"] = False     # ignore the contradictory anchor
            continue
        cleaned.append((k, v))
        last = v
    apos = cleaned

    INF = 10 ** 12
    status = [None] * n
    label = [frames[k]["banked"] for k in range(n)]

    # frames before the first / after the last anchor: OUTSIDE (untrusted)
    if not apos:
        for k in range(n):
            status[k] = "outside"
        return _emit(frames, status, label, conflicts, snap_max)
    first_k = apos[0][0]
    last_k = apos[-1][0]
    for k in range(0, first_k):
        status[k] = "outside"
    for k in range(last_k + 1, n):
        status[k] = "outside"

    # mark anchors
    for k, v in apos:
        status[k] = "anchor"
        label[k] = v

    # each segment between consecutive anchors
    for (li, lo), (ri, hi) in zip(apos, apos[1:]):
        seg = list(range(li + 1, ri))
        if not seg:
            continue
        # candidates whose banked value sits inside the anchor window
        cand = [k for k in seg if lo <= frames[k]["banked"] <= hi]
        keep = _lnds_mask([frames[k]["banked"] for k in cand])
        backbone = {cand[i] for i, kp in enumerate(keep) if kp}
        # confirm backbone
        for k in seg:
            if k in backbone:
                status[k] = "confirmed"
                label[k] = frames[k]["banked"]
        # repair the rest using the nearest confirmed neighbors' values
        # build sorted confirmed positions in this segment incl the two anchors
        fixed = [(li, lo)] + sorted(
            (k, frames[k]["banked"]) for k in backbone) + [(ri, hi)]
        for k in seg:
            if status[k] is not None:
                continue
            # neighbor window from surrounding fixed points
            pv = lo
            nv = hi
            for fk, fv in fixed:
                if fk <= k:
                    pv = fv
                elif fk > k:
                    nv = fv
                    break
            v, st = _repair(frames[k]["banked"], pv, nv)
            status[k] = st
            label[k] = v

    return _emit(frames, status, label, conflicts, snap_max)


def _emit(frames, status, label, conflicts, snap_max):
    rows = []
    counts = {}
    for k, f in enumerate(frames):
        st = status[k] or "outside"
        counts[st] = counts.get(st, 0) + 1
        rows.append({"file": f["file"], "label": _digits(label[k]),
                     "status": st, "was": _digits(f["banked"]),
                     "ts": f["ts"]})
    with open(OUT_PATH, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    summary = {"ran": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "total": len(rows), "counts": counts,
               "conflicts": conflicts,
               "snap_max": snap_max if snap_max is not None else SNAP_MAX}
    json.dump(summary, open(STATUS_PATH, "w"), indent=1)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap-max", type=int, default=None,
                    help="override tight-window repair threshold (counts)")
    args = ap.parse_args()
    if args.snap_max is not None:
        global SNAP_MAX
        SNAP_MAX = args.snap_max
    s = propagate(args.snap_max)
    print("propagate:", json.dumps(s["counts"]),
          "conflicts:", len(s["conflicts"]))


if __name__ == "__main__":
    main()
