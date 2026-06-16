"""Dataset: load meter frames, rotate upright, crop the digit band, CLAHE-
normalize, and yield (grayscale tensor, 9 digit labels). Heavy augmentation
simulates the glare/blur/drift the live camera produces so the model generalizes
from only ~373 frames.
"""
import json
import os
import random

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

from config import CROP, ROTATE_180, IN_H, IN_W, N_DIGITS

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
FRAMES = os.path.join(DATA, "frames")

_clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))


def load_crop_gray(path, rotate=ROTATE_180):
    """Frame path -> preprocessed grayscale crop as float32 [0,1], shape (IN_H,IN_W)."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    if rotate:
        img = cv2.rotate(img, cv2.ROTATE_180)
    h, w = img.shape[:2]
    l, t, r, b = CROP
    crop = img[int(t*h):int(b*h), int(l*w):int(r*w)]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = _clahe.apply(gray)               # local contrast — pulls digits out of glare
    gray = cv2.resize(gray, (IN_W, IN_H), interpolation=cv2.INTER_AREA)
    return gray.astype(np.float32) / 255.0


def _augment(gray):
    """Random affine (shift/scale/rotate) + brightness/contrast + blur + glare
    erasing. Operates on a float32 (IN_H,IN_W) image."""
    h, w = gray.shape
    # affine: translate, scale, small rotation
    tx = random.uniform(-0.06, 0.06) * w
    ty = random.uniform(-0.10, 0.10) * h          # more vertical (camera drift)
    sc = random.uniform(0.90, 1.10)
    ang = random.uniform(-3, 3)
    M = cv2.getRotationMatrix2D((w/2, h/2), ang, sc)
    M[0, 2] += tx
    M[1, 2] += ty
    gray = cv2.warpAffine(gray, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    # brightness / contrast
    gray = np.clip(gray * random.uniform(0.75, 1.25)
                   + random.uniform(-0.12, 0.12), 0, 1)
    # blur (camera is often soft)
    if random.random() < 0.5:
        k = random.choice([3, 3, 5])
        gray = cv2.GaussianBlur(gray, (k, k), 0)
    # glare erase: drop a bright/dark rectangle to mimic reflection blobs
    if random.random() < 0.4:
        ew, eh = random.randint(w//10, w//4), random.randint(h//6, h//2)
        ex, ey = random.randint(0, w-ew), random.randint(0, h-eh)
        gray[ey:ey+eh, ex:ex+ew] = random.uniform(0, 1)
    return gray.astype(np.float32)


class MeterDigits(Dataset):
    def __init__(self, rows, train=True):
        self.rows = rows
        self.train = train

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        gray = load_crop_gray(os.path.join(FRAMES, r["file"]))
        if self.train:
            gray = _augment(gray)
        x = torch.from_numpy(gray).unsqueeze(0)        # (1,H,W)
        digits = [int(c) for c in r["label"]][:N_DIGITS]
        y = torch.tensor(digits, dtype=torch.long)     # (9,)
        return x, y


def load_rows():
    rows = [json.loads(l) for l in open(os.path.join(DATA, "cnn_train.jsonl")) if l.strip()]
    rows = [r for r in rows if len("".join(c for c in r["label"] if c.isdigit())) == 9]
    return rows


def split_rows(rows, val_frac=0.15, seed=42):
    rnd = random.Random(seed)
    rows = rows[:]
    rnd.shuffle(rows)
    n_val = max(1, int(len(rows) * val_frac))
    return rows[n_val:], rows[:n_val]
