"""Gated retrain: train challenger v2 and compare it to champion v1 on a FAIR
held-out test set.

Fairness: the test set is drawn ONLY from the NEW oracle frames (source
"oracle-new") that the v1 champion never trained on. v2 also excludes them from
training. So both models are judged on identical, truly-unseen frames — the
honest "did retraining help on fresh real data" question.

Promote rule: v2 ships ONLY if its full-9 accuracy on the held-out test BEATS
v1's (ties do not promote — never replace a proven champion without a win).
Writes meter_cnn_v2.pt; does NOT overwrite the champion meter_cnn.pt.
"""
import json
import os
import random
import time

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from config import N_DIGITS
from dataset import MeterDigits, load_crop_gray, FRAMES
from model import MeterDigitCNN

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "model")
CHAMP = os.path.join(OUT, "meter_cnn.pt")          # v1 champion
CHALL = os.path.join(OUT, "meter_cnn_v2.pt")       # v2 challenger
EPOCHS = 80
BATCH = 32
LR = 1e-3
TEST_FRAC = 0.25                                   # of the NEW frames
SEED = 0


def load_rows():
    rows = [json.loads(l) for l in open(os.path.join(DATA, "cnn_train.jsonl"))
            if l.strip()]
    rows = [r for r in rows
            if len("".join(c for c in r["label"] if c.isdigit())) == 9]
    return rows


def evaluate(model, loader, device):
    model.eval()
    dc = dt = fc = ft = 0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            pred = model(x).argmax(-1)
            dc += (pred == y).sum().item(); dt += y.numel()
            fc += (pred == y).all(dim=1).sum().item(); ft += y.size(0)
    return dc / dt, fc / ft


def main():
    random.seed(SEED); torch.manual_seed(SEED); np.random.seed(SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    rows = load_rows()

    new = [r for r in rows if r.get("source") == "oracle-new"]
    old = [r for r in rows if r.get("source") != "oracle-new"]
    random.shuffle(new)
    n_test = max(20, int(len(new) * TEST_FRAC))
    test = new[:n_test]
    train = old + new[n_test:]
    print(f"total {len(rows)}  train {len(train)}  held-out TEST {len(test)} "
          f"(all unseen-by-v1 new frames)  device {device}")

    train_ld = DataLoader(MeterDigits(train, train=True),
                          batch_size=BATCH, shuffle=True, num_workers=0)
    test_ld = DataLoader(MeterDigits(test, train=False),
                         batch_size=64, shuffle=False, num_workers=0)

    # --- champion v1 baseline on the held-out test ---
    champ = MeterDigitCNN().to(device)
    champ.load_state_dict(torch.load(CHAMP, map_location=device))
    v1_d, v1_f = evaluate(champ, test_ld, device)
    print(f"\nCHAMPION v1 on held-out test: per-digit {v1_d:.3f}  full-9 {v1_f:.3f}")

    # --- train challenger v2 ---
    model = MeterDigitCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)
    lossf = nn.CrossEntropyLoss()
    best_f = -1.0
    t0 = time.time()
    for ep in range(1, EPOCHS + 1):
        model.train()
        tot = 0.0
        for x, y in train_ld:
            x, y = x.to(device), y.to(device)
            logits = model(x)
            loss = sum(lossf(logits[:, d, :], y[:, d]) for d in range(N_DIGITS))
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item()
        sched.step()
        if ep % 10 == 0 or ep == 1:
            d, f = evaluate(model, test_ld, device)
            star = "  *" if f > best_f else ""
            print(f"ep {ep:3d}  loss {tot/len(train_ld):6.3f}  "
                  f"test digit {d:.3f}  full {f:.3f}{star}")
            if f > best_f:
                best_f = f
                torch.save(model.state_dict(), CHALL)
    # final challenger = best-by-test checkpoint
    model.load_state_dict(torch.load(CHALL, map_location=device))
    v2_d, v2_f = evaluate(model, test_ld, device)
    print(f"\nCHALLENGER v2 on held-out test: per-digit {v2_d:.3f}  "
          f"full-9 {v2_f:.3f}  ({time.time()-t0:.0f}s)")

    print("\n" + "=" * 52)
    print(f"  champion  v1  full-9 {v1_f:.3f}  per-digit {v1_d:.3f}")
    print(f"  challenger v2 full-9 {v2_f:.3f}  per-digit {v2_d:.3f}")
    if v2_f > v1_f:
        print(f"  VERDICT: PROMOTE v2  (+{(v2_f-v1_f)*100:.1f} pts full-9)")
    else:
        print(f"  VERDICT: KEEP v1     (v2 did not beat champion)")
    print("=" * 52)


if __name__ == "__main__":
    main()
