#!/usr/bin/env python3
"""Consensus resolver — recover good labels from the needs-review pile.

The strict oracle verify left 305 frames in needs-review, mostly because two
independent reads disagreed by 1-5 on the FAST-MOVING last digit under glare.
The last digit matters (per-digit CNN), so we don't relax the rule — instead we
take a MAJORITY VOTE of multiple independent reads, which resolves stochastic
glare disagreement WITHOUT lowering the bar.

For each review frame:
  1. Re-read it REPS times with GPT-4o (temp 0, but glare makes it stochastic),
     each with a monotonic-neighbor context hint.
  2. If a single 9-digit value wins a strict majority (>= ceil(REPS/2)+ ... we
     require >= MAJORITY of REPS), that's the consensus read.
  3. MONOTONIC GATE: the consensus must fit between the nearest TRUSTED verified
     anchors in time (floor_val <= consensus <= ceil_val). The 104 already-
     verified frames are the anchors — a meter can't go backward, so a consensus
     that violates its neighbors is rejected even if reads agreed.
  4. Promote to the manifest with the CONSENSUS label (which may CORRECT the
     filename's label). The CNN trains on the manifest's (file,label), so a
     corrected label needs no file rename.

Frames that still can't reach majority+monotonic stay in needs-review.

Run on the Acer:
    cd ~/smart-garden-server && ./.venv/bin/python /tmp/resolve_consensus.py \
        --review ~/cnn-dataset-oracle/needs_review.jsonl \
        --manifest ~/cnn-dataset-oracle/manifest.jsonl \
        --dir ~/meter-training --reps 3
"""
import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
from collections import Counter

NAME_RE = re.compile(r"^(\d{9})_(\d+)(?:_oracle)?\.jpg$")

# OpenAI gpt-4o free-tier cap is 30,000 tokens/min; each read is ~1,000 tokens,
# so ~30 reads/min is the ceiling. Pace to ~1 read / 2.2s (≈27/min) with headroom
# and back off on any 429 by waiting it out. Keeps the batch from stalling in a
# retry storm (the bug that hung the first run).
MIN_INTERVAL_S = 2.2
_last_call = [0.0]


def throttled_read(oracle, jpeg, hint, max_retries=4):
    """Call oracle.read_meter with client-side pacing + 429 backoff.

    Raises QuotaExhausted if the account is out of credit (a different error
    from the per-minute rate limit — backing off won't help, so we stop).
    """
    for attempt in range(max_retries):
        wait = MIN_INTERVAL_S - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
        res = oracle.read_meter(jpeg, rotate180=True, hint=hint)
        err = str(res.get("error") or "")
        low = err.lower()
        if "exceeded your current quota" in low or "insufficient_quota" in low:
            raise QuotaExhausted(err)
        if "429" in err or "rate limit" in low:
            time.sleep(20 * (attempt + 1))   # per-minute limit — wait it out
            continue
        return res
    return res


class QuotaExhausted(Exception):
    """OpenAI account credit is spent — stop and let the user top up."""


def epoch_of(fname):
    m = NAME_RE.match(fname)
    return int(m.group(2)) if m else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--dir", default="/home/jamesearlpace/meter-training")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--server-dir", default="/home/jamesearlpace/smart-garden-server")
    args = ap.parse_args()

    sys.path.insert(0, args.server_dir)
    import vision_oracle
    if not vision_oracle.available():
        print("FAIL: no OPENAI_API_KEY")
        return 2

    review = [json.loads(l) for l in open(args.review) if l.strip()]
    # Base manifest = the originally-verified entries only. Strip any prior
    # consensus promotions so re-running (after a partial quota stop) rebuilds
    # cleanly from the durable results file instead of duplicating rows.
    manifest = [json.loads(l) for l in open(args.manifest) if l.strip()]
    manifest = [m for m in manifest if m.get("verifier") != "oracle-consensus"]

    # Trusted anchors = verified manifest, sorted by capture time.
    anchors = sorted(((epoch_of(r["file"]), int(r["label"])) for r in manifest))
    anchor_ts = [a[0] for a in anchors]

    def monotonic_ok(ts, val):
        """val must be >= the last verified value before ts and <= the first
        verified value after ts (meter is non-decreasing)."""
        import bisect
        i = bisect.bisect_left(anchor_ts, ts)
        lo = anchors[i - 1][1] if i > 0 else None
        hi = anchors[i][1] if i < len(anchors) else None
        if lo is not None and val < lo:
            return False
        if hi is not None and val > hi:
            return False
        return True

    need_majority = math.floor(args.reps / 2) + 1   # e.g. reps=3 -> 2

    # RESUMABLE: a results file records every frame we've already voted on, one
    # JSON line each, written IMMEDIATELY after each frame. A crash / quota stop
    # loses at most the current frame, and a restart skips everything already
    # done (no wasted re-reads, no wasted money).
    results_path = os.path.join(os.path.dirname(args.manifest),
                                "consensus_results.jsonl")
    done = {}
    if os.path.exists(results_path):
        for line in open(results_path):
            if line.strip():
                rec = json.loads(line)
                done[rec["file"]] = rec
        print(f"resuming: {len(done)} frames already voted "
              f"(skipping those)\n")

    import bisect

    def hint_lock_for(ts):
        """Use the nearest verified anchor BEFORE this frame as the hint's last
        value — stateless, so resuming gives identical hints."""
        i = bisect.bisect_left(anchor_ts, ts)
        return anchors[i - 1][1] if i > 0 else (anchors[0][1] if anchors else 0)

    todo = sorted(review, key=lambda x: epoch_of(x["file"]))
    quota_hit = False
    processed = 0
    with open(results_path, "a") as results_f:
        for n, r in enumerate(todo, 1):
            f = r["file"]
            if f in done:
                continue
            ts = epoch_of(f)
            path = os.path.join(args.dir, f)
            if not os.path.exists(path):
                continue
            jpeg = open(path, "rb").read()
            votes = Counter()
            if r.get("second_read") and len(str(r["second_read"])) == 9:
                votes[str(r["second_read"])] += 1
            lock = hint_lock_for(ts)
            hint = {"last_value": int(lock), "high_prefix": f"{int(lock):09d}"[:4]}
            try:
                for _ in range(args.reps):
                    res = throttled_read(vision_oracle, jpeg, hint)
                    d = res.get("digits") or ""
                    if len(d) == 9:
                        votes[d] += 1
            except QuotaExhausted:
                print(f"\n⚠️  OpenAI quota exhausted at frame {n}/{len(todo)}. "
                      f"Progress saved — top up credit and re-run to resume.")
                quota_hit = True
                break
            winner, count = (votes.most_common(1)[0] if votes else ("", 0))
            promote = (count >= need_majority and winner
                       and monotonic_ok(ts, int(winner)))
            rec = {"file": f, "orig_label": r["label"], "winner": winner,
                   "votes": count, "reps_plus_seed": args.reps + 1,
                   "promote": bool(promote)}
            results_f.write(json.dumps(rec) + "\n")
            results_f.flush()              # durable immediately
            done[f] = rec
            processed += 1
            if processed % 25 == 0:
                pr = sum(1 for d in done.values() if d["promote"])
                print(f"  consensus {len(done)}/{len(todo)} "
                      f"(promoted {pr})…", flush=True)

    # RECONCILE: rebuild manifest + needs_review from the durable results.
    promoted = [d for d in done.values() if d["promote"]]
    promoted_files = {d["file"] for d in promoted}
    with open(args.manifest, "w") as mf:
        for m in manifest:                          # keep the original verified
            mf.write(json.dumps(m) + "\n")
        for d in promoted:                          # add consensus promotions
            corrected = d["winner"] != d["orig_label"]
            mf.write(json.dumps({
                "file": d["file"], "label": d["winner"], "second_read": d["winner"],
                "verifier": "oracle-consensus", "votes": d["votes"],
                "reps": d["reps_plus_seed"],
                "corrected_from": d["orig_label"] if corrected else None,
                "agree": True}) + "\n")
    still_review = [r for r in review if r["file"] not in promoted_files]
    with open(args.review, "w") as rf:
        for r in still_review:
            d = done.get(r["file"])
            if d:
                r = dict(r); r["consensus_winner"] = d["winner"]
                r["consensus_count"] = d["votes"]
            rf.write(json.dumps(r) + "\n")

    corrected_n = sum(1 for d in promoted if d["winner"] != d["orig_label"])
    print(f"\nPROMOTED to manifest: {len(promoted)} "
          f"({corrected_n} with a CORRECTED label)")
    print(f"STILL in needs-review: {len(still_review)}")
    print(f"Manifest total now: {len(manifest) + len(promoted)}")
    if quota_hit:
        print("(Partial run — re-run after topping up to finish the rest.)")
    if promoted:
        print("\nSample corrections (orig label -> consensus):")
        shown = 0
        for d in promoted:
            if d["winner"] != d["orig_label"] and shown < 10:
                print(f"  {d['file']:<42} {d['orig_label']} -> {d['winner']} "
                      f"({d['votes']}/{d['reps_plus_seed']} votes)")
                shown += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
