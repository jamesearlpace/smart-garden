"""Visualize the digit-band crop on sample frames so we can tune it before
training. Frames are stored upside-down (camera mount) -> rotate 180 first.

The CNN reads the WHOLE digit band (no per-digit segmentation) with 9 output
heads, so this crop just needs to reliably contain all 9 digits with a little
margin, across the camera's fixed framing.
"""
import json
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
FRAMES = os.path.join(DATA, "frames")

# Fractional crop of the (rotated-upright) 800x600 frame: (left, top, right, bottom).
# Tune these by looking at _crop_preview.jpg until the box hugs the 9 digits.
CROP = (0.10, 0.10, 0.78, 0.36)


def crop_box(img):
    w, h = img.size
    l, t, r, b = CROP
    return (int(l * w), int(t * h), int(r * w), int(b * h))


def main():
    rows = [json.loads(x) for x in open(os.path.join(DATA, "cnn_train.jsonl"))]
    # a spread of samples across the value range
    rows.sort(key=lambda r: r["label"])
    picks = [rows[i] for i in (0, len(rows)//4, len(rows)//2,
                               3*len(rows)//4, len(rows)-1)]
    # Build a contact sheet: full frame with box drawn + the crop below it.
    tiles = []
    for r in picks:
        img = Image.open(os.path.join(FRAMES, r["file"])).rotate(180).convert("RGB")
        box = crop_box(img)
        marked = img.copy()
        ImageDraw.Draw(marked).rectangle(box, outline=(255, 0, 0), width=4)
        crop = img.crop(box).resize((512, 160))
        tiles.append((r["label"], marked.resize((400, 300)), crop))

    pad = 8
    W = 400 + 512 + pad * 3
    rowH = max(300, 160) + pad
    sheet = Image.new("RGB", (W, rowH * len(tiles)), (20, 24, 30))
    d = ImageDraw.Draw(sheet)
    for i, (lbl, marked, crop) in enumerate(tiles):
        y = i * rowH + pad
        sheet.paste(marked, (pad, y))
        sheet.paste(crop, (pad * 2 + 400, y + 70))
        d.text((pad * 2 + 400, y + 4), lbl, fill=(120, 230, 160))
    out = os.path.join(HERE, "_crop_preview.jpg")
    sheet.save(out, "JPEG", quality=92)
    print("wrote", out, "| CROP =", CROP)


if __name__ == "__main__":
    main()
