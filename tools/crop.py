# -*- coding: utf-8 -*-
"""Split the full-page screenshot into readable halves (verification helper)."""

import os
import sys

from PIL import Image

src = sys.argv[1]
out_dir = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("TEMP", ".")
im = Image.open(src).convert("RGB")
w, h = im.size
px = im.load()
bg = px[5, 5]
last = h - 1
while last > 0:
    row = [px[x, last] for x in range(0, w, 7)]
    if any(abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2]) > 12 for c in row):
        break
    last -= 1
print("content bottom:", last, "of", h)
mid = last // 2
for name, box in (("a", (0, 0, w, mid)), ("b", (0, mid, w, last + 26))):
    crop = im.crop(box)
    path = os.path.join(out_dir, f"layout-{name}.png")
    crop.save(path)
    print(name, crop.size, path)
