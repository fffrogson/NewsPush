# -*- coding: utf-8 -*-
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open("output/brief-2026-11-21.json", encoding="utf-8"))
print("overview:", d["overview"])
print("items:", len(d["items"]))
zh = 0
for it in d["items"]:
    if it["lang"] == "zh":
        zh += 1
    print(f'{it["score"]:4.1f} {it["lang"]} {it["category"]:5} | {it["title_zh"][:34]}')
    if not it["summary"]:
        print("        <无摘要>")
print("中文条目:", zh, "/", len(d["items"]))
