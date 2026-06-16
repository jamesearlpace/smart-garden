"""Train the meter-digit CNN. Reports per-digit accuracy AND full-9-correct
accuracy (the one that matters — a reading is only useful if all 9 are right).
Saves the best model by val full-accuracy.
"""
import os
import time

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from config import N_DIGITS
from dataset import MeterDigits, load_rows, split_rows
from model import MeterDigitCNN

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "model")
os.makedirs(OUT, exist_ok=True)

EPOCHS = 80
BATCH = 32
LR = 1e-3


def evaluate(model, loader, device):
    model.eval()
    digit_correct = digit_total = 0
    full_correct = full_total = 0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            logits = model(x)                       # (B,9,10)
            pred = logits.argmax(-1)                # (B,9)
            digit_correct += (pred == y).sum().item()
            digit_total += y.numel()
            full_correct += (pred == y).all(dim=1).sum().item()
            full_total += y.size(0)
    return digit_correct/digit_total, full_correct/full_total


def main():
    torch.manual_seed(0)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    rows = load_rows()
    tr, va = split_rows(rows)
    print(f"train {len(tr)}  val {len(va)}  device {device}")

    train_ds = MeterDigits(tr, train=True)
    val_ds = MeterDigits(va, train=False)
    train_ld = DataLoader(train_ds, batch_size=BATCH, shuffle=True, num_workers=0)
    val_ld = DataLoader(val_ds, batch_size=64, shuffle=False, num_workers=0)

    model = MeterDigitCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)
    lossf = nn.CrossEntropyLoss()

    best = -1.0
    t0 = time.time()
    for ep in range(1, EPOCHS+1):
        model.train()
        tot = 0.0
        for x, y in train_ld:
            x, y = x.to(device), y.to(device)
            logits = model(x)                       # (B,9,10)
            loss = sum(lossf(logits[:, d, :], y[:, d]) for d in range(N_DIGITS))
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item()
        sched.step()
        if ep % 5 == 0 or ep == 1:
            dacc, facc = evaluate(model, val_ld, device)
            print(f"ep {ep:3d}  loss {tot/len(train_ld):6.3f}  "
                  f"val digit {dacc:.3f}  val full {facc:.3f}"
                  + ("  *" if facc > best else ""))
            if facc > best:
                best = facc
                torch.save(model.state_dict(), os.path.join(OUT, "meter_cnn.pt"))
    # Final eval of the best-saved model.
    model.load_state_dict(torch.load(os.path.join(OUT, "meter_cnn.pt")))
    dacc, facc = evaluate(model, val_ld, device)
    print(f"\nBEST val: per-digit {dacc:.3f}  full-9 {facc:.3f}  "
          f"({time.time()-t0:.0f}s)  -> {OUT}/meter_cnn.pt")


if __name__ == "__main__":
    main()
