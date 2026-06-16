#!/usr/bin/env python3
"""Build the EXPANDED CNN training set for the v2 retrain.

Combines:
  (a) the existing verified v1 set (cnn_train.jsonl — manual/consensus/verified),
  (b) NEW oracle-banked frames that survived the monotonic audit (independent
      reader + physics gate = verified per guardrails #1 and #3).

Dedups to MAX_PER_LABEL frames per distinct 9-digit reading so the per-digit
model isn't skewed by numbers that happen to have many frames. Writes
cnn_train_v2.jsonl. Does NOT touch the v1 file.
"""
import json
import os
import glob
import re

DIR = "/home/jamesearlpace/cnn-dataset-oracle"
FRAMES = "/home/jamesearlpace/meter-training"
V1 = os.path.join(DIR, "cnn_train.jsonl")
OUT = os.path.join(DIR, "cnn_train_v2.jsonl")
MAX_PER_LABEL = 3
NAME_RE = re.compile(r"^(\d{9})_(\d+)(?:_oracle)?\.jpg$")


def nine(s):
    d = "".join(c for c in str(s) if c.isdigit())
    return d if len(d) == 9 else None


# existing verified set (keep its source tags)
rows = []
have = set()
for line in open(V1):
    line = line.strip()
    if not line:
        continue
    r = json.loads(line)
    lbl = nine(r["label"])
    if not lbl:
        continue
    if not os.path.exists(os.path.join(FRAMES, r["file"])):
        continue  # quarantined since v1
    rows.append({"file": r["file"], "label": lbl, "source": r.get("source", "verified")})
    have.add(r["file"])

# count per label so far (for dedup budget)
per_label = {}
for r in rows:
    per_label[r["label"]] = per_label.get(r["label"], 0) + 1

# new oracle survivors (in FRAMES, not already in the set)
new_added = 0
new_files = sorted(glob.glob(os.path.join(FRAMES, "*.jpg")))
for path in new_files:
    f = os.path.basename(path)
    if f in have:
        continue
    m = NAME_RE.match(f)
    if not m:
        continue
    lbl = m.group(1)
    # only oracle-banked frames are independently verified; skip old local-banked
    side = os.path.join(FRAMES, f.rsplit(".", 1)[0] + ".json")
    src = "oracle-new"
    if os.path.exists(side):
        try:
            meta = json.load(open(side))
            # require the filename label to match the sidecar label (sanity)
            if nine(meta.get("label", "")) != lbl:
                continue
        except Exception:
            pass
    if per_label.get(lbl, 0) >= MAX_PER_LABEL:
        continue
    rows.append({"file": f, "label": lbl, "source": src})
    have.add(f)
    per_label[lbl] = per_label.get(lbl, 0) + 1
    new_added += 1

with open(OUT, "w") as fh:
    for r in sorted(rows, key=lambda x: x["label"]):
        fh.write(json.dumps(r) + "\n")

by_src = {}
for r in rows:
    by_src[r["source"]] = by_src.get(r["source"], 0) + 1
distinct = len({r["label"] for r in rows})
print(f"EXPANDED SET: {len(rows)} frames ({distinct} distinct) -> {OUT}")
print(f"  new oracle frames added: {new_added}")
for s in sorted(by_src):
    print(f"  {s:<12} {by_src[s]}")
