# -*- coding: utf-8 -*-
"""Print the order of a generated brief JSON (debug helper)."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "output-test/brief-2026-11-21.json"
data = json.load(open(path, encoding="utf-8"))
print("=== 主榜 ===")
for i, it in enumerate(data["items"], 1):
    print(f"{i:2d} {it['score']:4.1f} cn={str(it.get('cn'))[:5]:5s} | {it['title_zh'][:40]} | {it['source']}")
print("=== 国内要闻 ===")
for i, it in enumerate(data.get("extras") or [], 1):
    print(f"{i:2d} {it['score']:4.1f} cn={str(it.get('cn'))[:5]:5s} | {it['title_zh'][:40]} | {it['source']}")
print("total", len(data["items"]), "+", len(data.get("extras") or []))
