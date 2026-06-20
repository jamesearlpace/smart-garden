#!/usr/bin/env python3
"""Batch re-read suspect banked frames with the GPT-4o vision oracle and emit
PROPOSED label corrections for human confirmation.

Why proposals (not auto-apply): the oracle ALSO misreads under glare, so its
re-reads are SUGGESTIONS. Each frame is read 3x and a value must win a strict
majority (>=2/3) to be proposed at all; the human accepts/dismisses in the
label-review gallery. Accepted proposals become manual (gold) corrections.

Runs on the Acer (frames + OPENAI_API_KEY env live here). Launched detached by
the dashboard's /api/cam/reprocess endpoint; writes progress to
reprocess_status.json so the gallery can show a progress bar.

Usage:
  reprocess.py --list /tmp/reprocess_list.json   # JSON array of jpg basenames
"""
import argparse
import json
import os
import sys
import time

BANK_DIR = os.environ.get("METER_BANK_DIR", "/home/jamesearlpace/meter-training")
LABELS_DIR = os.environ.get("METER_LABELS_DIR",
                            "/home/jamesearlpace/cnn-dataset-oracle")
PROPOSED_PATH = os.path.join(LABELS_DIR, "proposed_labels.jsonl")
STATUS_PATH = os.path.join(LABELS_DIR, "reprocess_status.json")
REPS = int(os.environ.get("METER_REPROCESS_REPS", "3"))
# Be gentle on the OpenAI rate/token cap (same constraint resolve_consensus hit).
THROTTLE_S = float(os.environ.get("METER_REPROCESS_THROTTLE_S", "2.2"))


def _digits9(res):
    """Pull a 9-digit string from an oracle result, or None."""
    if not res.get("ok") or not res.get("readable") or res.get("confidence") == "low":
        return None
    d = "".join(c for c in str(res.get("digits", "")) if c.isdigit())
    if len(d) != 9:
        v = res.get("value")
        if isinstance(v, int):
            d = f"{v:09d}"
    return d if len(d) == 9 else None


def write_status(d):
    try:
        tmp = STATUS_PATH + ".tmp"
        json.dump(d, open(tmp, "w"))
        os.replace(tmp, STATUS_PATH)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True, help="JSON file: array of basenames")
    args = ap.parse_args()

    try:
        files = json.load(open(args.list))
    except Exception as e:
        print(f"bad list: {e}", file=sys.stderr)
        sys.exit(1)
    files = [os.path.basename(str(f)) for f in files if str(f).endswith(".jpg")]

    try:
        import vision_oracle
    except Exception as e:
        write_status({"running": False, "error": f"oracle import: {e}",
                      "total": len(files), "done": 0})
        sys.exit(1)
    if not vision_oracle.available():
        write_status({"running": False, "error": "no OPENAI_API_KEY",
                      "total": len(files), "done": 0})
        sys.exit(1)

    os.makedirs(LABELS_DIR, exist_ok=True)
    total = len(files)
    started = time.time()
    proposed = changed = confirmed = unresolved = errors = 0

    write_status({"running": True, "total": total, "done": 0,
                  "started": started, "updated": started,
                  "proposed": 0, "changed": 0, "confirmed": 0,
                  "unresolved": 0, "errors": 0, "last_file": ""})

    with open(PROPOSED_PATH, "a") as out:
        for i, fname in enumerate(files, 1):
            path = os.path.join(BANK_DIR, fname)
            cur = fname.split("_")[0]
            cur = cur if (len(cur) == 9 and cur.isdigit()) else None
            try:
                frame = open(path, "rb").read()
            except Exception:
                errors += 1
                _progress(total, i, started, proposed, changed, confirmed,
                          unresolved, errors, fname)
                continue
            # Hint: high-digit prefix from the (suspect) current label fights
            # glare on the leading digits; the low digits are read from pixels.
            hint = None
            if cur:
                hint = {"last_value": int(cur), "high_prefix": cur[:4]}
            votes = {}
            for _ in range(REPS):
                try:
                    res = vision_oracle.read_meter(frame, rotate180=True, hint=hint)
                    d = _digits9(res)
                    if d:
                        votes[d] = votes.get(d, 0) + 1
                except Exception:
                    pass
                time.sleep(THROTTLE_S)
            # strict majority
            best, bestn = None, 0
            for d, n in votes.items():
                if n > bestn:
                    best, bestn = d, n
            if best is None or bestn < 2:
                unresolved += 1
            else:
                same = (best == cur)
                rec = {"file": fname, "proposed": best, "current": cur,
                       "votes": bestn, "reps": REPS, "agree": same,
                       "source": "oracle-reprocess",
                       "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
                out.write(json.dumps(rec) + "\n")
                out.flush()
                proposed += 1
                if same:
                    confirmed += 1
                else:
                    changed += 1
            _progress(total, i, started, proposed, changed, confirmed,
                      unresolved, errors, fname)

    write_status({"running": False, "total": total, "done": total,
                  "started": started, "updated": time.time(),
                  "proposed": proposed, "changed": changed,
                  "confirmed": confirmed, "unresolved": unresolved,
                  "errors": errors, "last_file": "",
                  "secs": int(time.time() - started)})
    print(f"reprocess done: {proposed} proposed ({changed} changed, "
          f"{confirmed} confirmed), {unresolved} unresolved, {errors} errors")


def _progress(total, done, started, proposed, changed, confirmed,
              unresolved, errors, last_file):
    write_status({"running": True, "total": total, "done": done,
                  "started": started, "updated": time.time(),
                  "proposed": proposed, "changed": changed,
                  "confirmed": confirmed, "unresolved": unresolved,
                  "errors": errors, "last_file": last_file})


if __name__ == "__main__":
    main()
