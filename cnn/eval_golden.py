"""Evaluate the trained CNN against the GOLDEN set — the independent ground
truth (frames verified by human/oracle viewing, NOT by the pipeline). This is
the honest accuracy number and the champion/challenger gate for retraining.

Golden frames live in ocr-harness/golden.json (the `true` field) but the images
are on the server. For local eval we use any golden frames present in data/frames;
on the server, point --frames at ~/meter-training.
"""
import json
import os
import sys

HERE = os.path.dirname(__file__)
GOLDEN = os.path.join(HERE, "..", "ocr-harness", "golden.json")


def main():
    frames_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "frames")
    import cnn_reader
    golden = json.load(open(GOLDEN))["frames"]
    n = correct = digit_ok = digit_tot = missing = 0
    rows = []
    for g in golden:
        path = os.path.join(frames_dir, g["file"])
        if not os.path.exists(path):
            missing += 1
            continue
        res = cnn_reader.read_path(path)
        got, true = res["digits"], g["true"]
        ok = got == true
        n += 1
        correct += ok
        for a, b in zip(got.ljust(9), true.ljust(9)):
            digit_tot += 1
            digit_ok += (a == b)
        rows.append((g["file"][:26], true, got, res["min_conf"], ok))
    print(f"{'frame':<28}{'true':<11}{'cnn':<11}{'min_conf':<9}ok")
    print("-"*64)
    for f, t, gg, c, ok in rows:
        print(f"{f:<28}{t:<11}{gg:<11}{c:<9}{'OK' if ok else 'X'}")
    if n:
        print(f"\nGolden full-9 accuracy: {correct}/{n} = {correct/n:.0%}")
        print(f"Golden per-digit:       {digit_ok}/{digit_tot} = {digit_ok/digit_tot:.0%}")
    if missing:
        print(f"({missing} golden frames not present in {frames_dir})")


if __name__ == "__main__":
    main()
