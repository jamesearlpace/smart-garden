"""Per-position meter-digit CNN: one shared conv backbone over the digit-band
crop, then 9 parallel classification heads (one per digit position). Each head
outputs 10 logits (0-9); the softmax max is the per-digit confidence used to
decide whether to fall through to the oracle.

Small enough to run in a few ms on CPU (Acer/tower), no GPU needed.
"""
import torch
import torch.nn as nn

from config import IN_H, IN_W, N_DIGITS, N_CLASSES


def _block(cin, cout, pool=(2, 2)):
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, padding=1),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
        nn.Conv2d(cout, cout, 3, padding=1),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(pool),
    )


class MeterDigitCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = nn.Sequential(
            _block(1, 32),                      # 64x256 -> 32x128
            _block(32, 64),                     # -> 16x64
            _block(64, 128),                    # -> 8x32
            _block(128, 128, pool=(2, 2)),      # -> 4x16
        )
        # Pool to a fixed (1 x N_DIGITS) so each column ~ one digit position.
        self.pool = nn.AdaptiveAvgPool2d((1, N_DIGITS))
        self.drop = nn.Dropout(0.3)
        # One linear head per digit position, sharing the 128-d column feature.
        self.heads = nn.ModuleList(
            [nn.Linear(128, N_CLASSES) for _ in range(N_DIGITS)])

    def forward(self, x):
        f = self.backbone(x)                    # (B,128,4,16)
        f = self.pool(f)                        # (B,128,1,9)
        f = f.squeeze(2).transpose(1, 2)        # (B,9,128)
        f = self.drop(f)
        # logits: (B, 9, 10)
        out = torch.stack([self.heads[i](f[:, i, :])
                           for i in range(N_DIGITS)], dim=1)
        return out
