# -*- coding: utf-8 -*-
"""Print a compact view of the last run's JSON."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "output/brief-2026-11-21.json"
data = json.load(open(path, encoding="utf-8"))
print("items", len(data["items"]), "| usage", data.get("usage"))
for it in data["items"]:
    print(
        f"{it['score']:.1f} | {it['title_zh'][:30]:32s} | "
        f"summary {len(it.get('summary', '')):3d} | insight {len(it.get('insight', '')):3d} | "
        f"terms {len(it.get('terms') or [])} | {it['source']}"
    )
