# -*- coding: utf-8 -*-
"""Stitch the two layout halves back into one preview image."""

import os
import sys

from PIL import Image

out_dir = sys.argv[1] if len(sys.argv) > 1 else "output"
a = Image.open(os.path.join(out_dir, "layout-a.png")).convert("RGB")
b = Image.open(os.path.join(out_dir, "layout-b.png")).convert("RGB")
w = max(a.width, b.width)
merged = Image.new("RGB", (w, a.height + b.height), (242, 242, 239))
merged.paste(a, (0, 0))
merged.paste(b, (0, a.height))
path = os.path.join(out_dir, "preview.png")
merged.save(path)
print(path, merged.size)
