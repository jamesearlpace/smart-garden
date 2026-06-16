"""Detect the bright LCD screen in each frame and crop the digit band relative
to it — robust to the CAMERA DRIFT we found (framing moved over the dataset, so
a fixed pixel crop misses the digits on newer frames).

Approach: the LCD is the large bright region. Threshold -> largest bright
contour -> its bounding box = the screen. The digit row is the top band of the
screen. Cropping relative to the detected screen self-aligns despite drift.
"""
import json
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
FRAMES = os.path.join(DATA, "frames")

# Digit band as a fraction of the DETECTED screen box (left,top,right,bottom).
BAND = (0.02, 0.04, 0.99, 0.62)


def detect_screen(bgr):
    """Return (x,y,w,h) of the bright LCD, or None."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    # Otsu threshold isolates the bright screen from the dark housing.
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    H, W = gray.shape
    best = None
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if area < 0.08 * W * H:                 # ignore small bright specks
            continue
        if w < h:                                # screen is wider than tall
            continue
        ar = w / float(h)
        if ar < 1.3 or ar > 4.5:                 # LCD aspect sanity
            continue
        if best is None or area > best[4]:
            best = (x, y, w, h, area)
    return best[:4] if best else None


def band_box(screen):
    x, y, w, h = screen
    l, t, r, b = BAND
    return (int(x + l * w), int(y + t * h), int(x + r * w), int(y + b * h))


def main():
    rows = [json.loads(x) for x in open(os.path.join(DATA, "cnn_train.jsonl"))]
    rows.sort(key=lambda r: r["label"])
    picks = [rows[i] for i in (0, len(rows)//4, len(rows)//2,
                               3*len(rows)//4, len(rows)-1)]
    tiles = []
    for r in picks:
        pil = Image.open(os.path.join(FRAMES, r["file"])).rotate(180).convert("RGB")
        bgr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        screen = detect_screen(bgr)
        marked = pil.copy()
        dr = ImageDraw.Draw(marked)
        if screen:
            x, y, w, h = screen
            dr.rectangle((x, y, x+w, y+h), outline=(0, 160, 255), width=3)
            bb = band_box(screen)
            dr.rectangle(bb, outline=(255, 0, 0), width=4)
            crop = pil.crop(bb).resize((512, 150))
        else:
            crop = Image.new("RGB", (512, 150), (60, 0, 0))
        tiles.append((r["label"], "FOUND" if screen else "MISS",
                      marked.resize((400, 300)), crop))

    pad = 8
    W = 400 + 512 + pad*3
    rowH = 300 + pad
    sheet = Image.new("RGB", (W, rowH*len(tiles)), (20, 24, 30))
    d = ImageDraw.Draw(sheet)
    for i, (lbl, st, marked, crop) in enumerate(tiles):
        y = i*rowH + pad
        sheet.paste(marked, (pad, y))
        sheet.paste(crop, (pad*2+400, y+75))
        d.text((pad*2+400, y+4), lbl + "  [" + st + "]",
               fill=(120, 230, 160) if st == "FOUND" else (240, 120, 120))
    out = os.path.join(HERE, "_lcd_preview.jpg")
    sheet.save(out, "JPEG", quality=92)
    print("wrote", out)


if __name__ == "__main__":
    main()
