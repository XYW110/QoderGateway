# -*- coding: utf-8 -*-
"""_peek_slider_img.py — 分析已保存的滑块背景/拼图（尺寸、alpha 边界、非透明框）。"""
import sys
from pathlib import Path

from PIL import Image

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

D = Path(r"D:\Work\Project\TestProject\QoderGateway\logs\slider")
for name in ("bg.png", "puzzle.png"):
    p = D / name
    if not p.exists():
        print(name, "missing")
        continue
    im = Image.open(p)
    print(f"== {name} mode={im.mode} size={im.size}")
    if im.mode in ("RGBA", "LA"):
        a = im.getchannel("A")
        bbox = a.getbbox()
        print("   alpha bbox:", bbox)
        # 非透明像素占比
        hist = a.histogram()
        total = im.size[0] * im.size[1]
        opaque = sum(hist[128:])
        print(f"   opaque px: {opaque}/{total} ({opaque/total:.1%})")
    else:
        print("   no alpha channel; corner px:", im.convert("RGB").getpixel((0, 0)))
    # 缩略网格采样，粗略看内容分布
    small = im.convert("RGB").resize((30, 12))
    px = small.load()
    for y in range(12):
        row = "".join(
            "#" if sum(px[x, y]) < 240 else ("." if sum(px[x, y]) > 660 else "+")
            for x in range(30))
        print("   ", row)
