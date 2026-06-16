"""Quick coverage check: does ONE generous fixed crop contain all 9 digits
across the camera drift? Shows a grid of just the crops for many frames so we
can scan for any that miss the digits. The CNN (translation-tolerant) + random
shift/zoom augmentation absorbs the residual drift, as long as digits are IN
the crop here.
"""
import json
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
FRAMES = os.path.join(DATA, "frames")

# Generous band — tune until every crop below shows all 9 digits with margin.
CROP = (0.02, 0.03, 0.80, 0.42)


def main():
    rows = [json.loads(x) for x in open(os.path.join(DATA, "cnn_train.jsonl"))]
    rows.sort(key=lambda r: r["label"])
    n = 16
    step = max(1, len(rows)//n)
    picks = rows[::step][:n]

    cw, ch = 360, 120
    cols = 2
    rowsN = (len(picks)+cols-1)//cols
    pad = 6
    sheet = Image.new("RGB", (cols*(cw+pad)+pad, rowsN*(ch+18+pad)+pad), (18, 22, 28))
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(picks):
        img = Image.open(os.path.join(FRAMES, r["file"])).rotate(180).convert("RGB")
        w, h = img.size
        l, t, rr, b = CROP
        crop = img.crop((int(l*w), int(t*h), int(rr*w), int(b*h))).resize((cw, ch))
        cx = pad + (i % cols)*(cw+pad)
        cy = pad + (i//cols)*(ch+18+pad)
        d.text((cx, cy), r["label"], fill=(120, 230, 160))
        sheet.paste(crop, (cx, cy+16))
    out = os.path.join(HERE, "_coverage.jpg")
    sheet.save(out, "JPEG", quality=90)
    print("wrote", out, "CROP", CROP)


if __name__ == "__main__":
    main()
