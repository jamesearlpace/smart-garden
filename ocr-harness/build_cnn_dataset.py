#!/usr/bin/env python3
"""Build a VERIFIED CNN training set — the gate that stops bad labels from
mistraining the model.

THE PRINCIPLE: collected != verified. Banking COLLECTS candidate (frame, label)
pairs cheaply and permissively — some labels are wrong (glare, a systematic OCR
misread, the old ratchet bug). The CNN must train ONLY on labels that pass
INDEPENDENT verification, never on raw banked labels.

A label is promoted to the CNN set only if ALL of these hold:
  1. MONOTONIC      — on the Longest Non-Decreasing Subsequence over time (a
                      meter only counts up; impossible labels are dropped).
  2. CROSS-READER   — a SECOND, independent reader agrees on all 9 digits. The
                      banked label usually came from GPT-4o (oracle) or the
                      lock; here we re-read each frame with RapidOCR on the tower
                      (a different architecture that fails differently). Two
                      independent readers agreeing is strong against a
                      systematic single-reader error — the exact failure that
                      monotonicity alone can't catch.
  3. (implicit) the frame exists and the label is a clean 9-digit value.

Frames that pass -> verified/manifest.jsonl (CNN-ready).
Frames that fail cross-reader -> review/ list + a montage for human spot-check.

Run on the Acer (reaches the tower OCR at OCR_TOWER_URL):
    cd ~/smart-garden-server && ./.venv/bin/python /tmp/build_cnn_dataset.py \
        --dir ~/meter-training --out ~/cnn-dataset [--limit N]

Cross-reader OCR is the tower's RapidOCR (free). No paid API calls.
"""
import argparse
import bisect
import json
import os
import re
import sys

NAME_RE = re.compile(r"^(\d{9})_(\d+)(?:_oracle)?\.jpg$")
TOWER_URL = os.environ.get("OCR_TOWER_URL", "http://192.168.0.120:5200/ocr")


def lnds_keep_mask(values):
    n = len(values)
    if n == 0:
        return []
    tails, tails_vals, prev = [], [], [-1] * n
    for i, v in enumerate(values):
        j = bisect.bisect_right(tails_vals, v)
        if j == len(tails_vals):
            prev[i] = tails[-1] if tails else -1
            tails.append(i); tails_vals.append(v)
        else:
            prev[i] = tails[j - 1] if j > 0 else -1
            tails[j] = i; tails_vals[j] = v
    keep = [False] * n
    k = tails[-1]
    while k != -1:
        keep[k] = True
        k = prev[k]
    return keep


def tower_read(jpeg_bytes):
    """Independent read via the tower's RapidOCR. Returns the 9-digit string it
    sees (joined digit tokens, right-9), or '' if it can't form 9 digits."""
    import urllib.request
    try:
        req = urllib.request.Request(TOWER_URL, data=jpeg_bytes,
                                     headers={"Content-Type": "image/jpeg"})
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = json.load(r).get("text", "")
    except Exception:
        return ""
    digs = "".join(ch for ch in txt if ch.isdigit())
    return digs[-9:] if len(digs) >= 9 else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/home/jamesearlpace/meter-training")
    ap.add_argument("--out", default="/home/jamesearlpace/cnn-dataset")
    ap.add_argument("--limit", type=int, default=0, help="cap frames (debug)")
    ap.add_argument("--low-only", action="store_true",
                    help="require only the LOW 5 digits to cross-agree (the high "
                         "digits come from the monotonic backbone anyway)")
    ap.add_argument("--verifier", choices=["tower", "oracle"], default="tower",
                    help="independent 2nd reader: 'tower' = RapidOCR (free, but "
                         "noisy on this glary feed), 'oracle' = GPT-4o re-read "
                         "with physics context hint (reliable, ~$0.002/frame)")
    ap.add_argument("--max-per-label", type=int, default=0,
                    help="keep at most N frames per distinct reading on the "
                         "backbone before verifying (0 = keep all). Set 1 to "
                         "dedup hard — one verified image per number is plenty "
                         "for a per-digit model and slashes oracle cost.")
    ap.add_argument("--server-dir", default="/home/jamesearlpace/smart-garden-server")
    args = ap.parse_args()

    frames = []
    for f in os.listdir(args.dir):
        m = NAME_RE.match(f)
        if m:
            frames.append((int(m.group(2)), int(m.group(1)), f))  # epoch, val, file
    frames.sort()
    if args.limit:
        frames = frames[-args.limit:]
    if not frames:
        print("no frames")
        return 1

    # 1) Monotonic backbone.
    keep = lnds_keep_mask([v for _, v, _ in frames])
    backbone = [frames[i] for i in range(len(frames)) if keep[i]]
    print(f"{len(frames)} frames -> {len(backbone)} on monotonic backbone "
          f"({len(frames) - len(backbone)} dropped as impossible)")

    # 1b) Optional dedup: keep at most N frames per distinct label (the NEWEST
    # by capture time — they tend to have current lighting). One clean image per
    # number is plenty to train a per-digit model, and it cuts oracle cost ~3x.
    if args.max_per_label > 0:
        seen = {}
        deduped = []
        for epoch, val, f in sorted(backbone, key=lambda t: -t[0]):  # newest first
            if seen.get(val, 0) >= args.max_per_label:
                continue
            seen[val] = seen.get(val, 0) + 1
            deduped.append((epoch, val, f))
        deduped.sort()  # back to time order for realistic hints
        print(f"dedup to {args.max_per_label}/label: {len(backbone)} -> "
              f"{len(deduped)} ({len(seen)} distinct readings)")
        backbone = deduped

    # 2) Independent verification.
    oracle = None
    if args.verifier == "oracle":
        sys.path.insert(0, args.server_dir)
        import vision_oracle as oracle
        if not oracle.available():
            print("FAIL: --verifier oracle but no OPENAI_API_KEY")
            return 2

    os.makedirs(args.out, exist_ok=True)
    verified, review = [], []
    prev_val = None
    for n, (epoch, val, f) in enumerate(backbone, 1):
        label = f"{val:09d}"
        jpeg = open(os.path.join(args.dir, f), "rb").read()
        if args.verifier == "oracle":
            # Fresh independent read with the slow-movement context hint, exactly
            # like the live pipeline. The hint anchors the high digits (which
            # the backbone already trusts); the LOW digits are read from pixels,
            # so a match on the full 9 is a genuine second confirmation.
            lock = prev_val if prev_val is not None else val - 300
            hint = {"last_value": int(lock), "high_prefix": f"{int(lock):09d}"[:4]}
            res = oracle.read_meter(jpeg, rotate180=True, hint=hint)
            second = res.get("digits") or ""
            conf = res.get("confidence")
        else:
            second = tower_read(jpeg)
            conf = None
        if args.low_only:
            agree = bool(second) and second[-5:] == label[-5:]
        else:
            agree = (second == label)
        rec = {"file": f, "label": label, "second_read": second,
               "verifier": args.verifier, "conf": conf, "agree": agree}
        (verified if agree else review).append(rec)
        prev_val = val
        if n % 25 == 0:
            print(f"  verify {n}/{len(backbone)}…")

    # 3) Emit.
    with open(os.path.join(args.out, "manifest.jsonl"), "w") as mf:
        for r in verified:
            mf.write(json.dumps(r) + "\n")
    with open(os.path.join(args.out, "needs_review.jsonl"), "w") as rf:
        for r in review:
            rf.write(json.dumps(r) + "\n")

    print(f"\nVERIFIED (CNN-ready): {len(verified)}")
    print(f"NEEDS REVIEW (excluded — verifier disagreed): {len(review)}")
    print(f"  -> {args.out}/manifest.jsonl  +  needs_review.jsonl")
    if review:
        print(f"\nSample disagreements (label vs independent {args.verifier} read):")
        for r in review[:12]:
            print(f"  {r['file']:<42} label={r['label']} "
                  f"{args.verifier}={r['second_read'] or '∅'}")
    print("\nThe CNN trains ONLY on manifest.jsonl. needs_review is never used "
          "as ground truth until a human resolves it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
