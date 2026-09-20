# -*- coding: utf-8 -*-
"""解析 slider2_dom.json 的容器结构。"""
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

d = json.loads(Path("logs/slider2_dom.json").read_text(encoding="utf-8"))
h = d.get("captchaRootHTML") or ""
print("HTML_LEN", len(h))
print(h[:2500])
print("=== ids/classes ===")
seen = set()
for m in re.finditer(r"<(\w+)([^>]*)>", h):
    tag, attrs = m.group(1), m.group(2)
    i = re.search(r'id="([^"]*)"', attrs)
    c = re.search(r'class="([^"]*)"', attrs)
    key = (tag, i.group(1) if i else "", (c.group(1) if c else "")[:60])
    if key in seen:
        continue
    seen.add(key)
    if key[1] or key[2]:
        print(" ", key)
