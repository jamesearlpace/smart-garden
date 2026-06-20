#!/usr/bin/env python3
"""Finalize the CNN training set — apply human edits, emit the file the CNN trains on.

Trust priority (highest first):
  1. MANUAL (manual_labels.jsonl) — a human looked at the image. 'correct' sets
     the label, 'ok' confirms the current label, 'reject' EXCLUDES the frame.
  2. VERIFIED / PROMOTED / CORRECTED (manifest.jsonl) — passed the automated
     2-reader + monotonic + consensus gates.
  Anything still in needs_review (no manual decision) is EXCLUDED — unresolved.

Output: cnn_train.jsonl — one {file, label, source} per CNN-ready frame, plus a
per-digit expansion is left to the trainer. This is THE training file; nothing
else should be fed to the model.
"""
import argparse
import json
import os


def load_jsonl(path):
    out = []
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/home/jamesearlpace/cnn-dataset-oracle")
    ap.add_argument("--frames", default="/home/jamesearlpace/meter-training")
    ap.add_argument("--out", default="cnn_train.jsonl")
    args = ap.parse_args()

    manifest = load_jsonl(os.path.join(args.dir, "manifest.jsonl"))
    review = load_jsonl(os.path.join(args.dir, "needs_review.jsonl"))

    # Manual = last action per file wins, with the last explicit label carried
    # forward (a label-less 'ok' after a 'Fix' still confirms the fixed value).
    manual = {}
    for r in load_jsonl(os.path.join(args.dir, "manual_labels.jsonl")):
        f = r.get("file")
        if not f:
            continue
        r["label"] = r.get("label") or manual.get(f, {}).get("label")
        manual[f] = r

    final = {}          # file -> {file, label, source}
    rejected = set()

    # Start from the automated manifest (verified/promoted/corrected).
    for m in manifest:
        src = "consensus" if m.get("verifier") == "oracle-consensus" else "verified"
        final[m["file"]] = {"file": m["file"], "label": m["label"], "source": src}

    # Manual decisions override everything.
    for f, mv in manual.items():
        act = mv.get("action")
        if act == "reject":
            rejected.add(f)
            final.pop(f, None)
        elif act == "ok":
            # Confirm the value the human was looking at: a prior Fix is carried
            # on the 'ok' record now, so prefer it over the automated label.
            lbl = (mv.get("label")
                   or final.get(f, {}).get("label")
                   or next((r["label"] for r in review if r["file"] == f), None))
            if lbl:
                final[f] = {"file": f, "label": lbl, "source": "manual-ok"}
        elif act == "correct":
            final[f] = {"file": f, "label": mv["label"], "source": "manual"}

    # Drop any frame whose jpg is gone (quarantined since), and require 9 digits.
    out_rows = []
    missing = 0
    for f, row in sorted(final.items(), key=lambda kv: kv[1]["label"]):
        if f in rejected:
            continue
        if not os.path.exists(os.path.join(args.frames, f)):
            missing += 1
            continue
        d = "".join(c for c in row["label"] if c.isdigit())
        if len(d) != 9:
            continue
        out_rows.append({"file": f, "label": d, "source": row["source"]})

    out_path = os.path.join(args.dir, args.out)
    with open(out_path, "w") as fh:
        for r in out_rows:
            fh.write(json.dumps(r) + "\n")

    by_src = {}
    for r in out_rows:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    print(f"FINAL CNN TRAINING SET: {len(out_rows)} frames -> {out_path}\n")
    for s in ("manual", "manual-ok", "consensus", "verified"):
        if s in by_src:
            print(f"  {s:<12} {by_src[s]}")
    print(f"\n  excluded: {len(rejected)} manually rejected, "
          f"{missing} missing-jpg, "
          f"{len(review) - sum(1 for r in review if r['file'] in manual)} "
          f"unresolved review")
    # Distinct readings (per-digit model wants variety of NUMBERS, not dups).
    distinct = len({r["label"] for r in out_rows})
    print(f"  distinct readings: {distinct}")


if __name__ == "__main__":
    main()
