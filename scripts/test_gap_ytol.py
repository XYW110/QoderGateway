# -*- coding: utf-8 -*-
"""locate_gap y_tol/band 参数回归：存档图 + 合成偏移用例。

1) 存档 bg/puzzle：默认参数与放宽参数都应定位成功（历史上 valid）
2) 合成：把拼图块在 canvas 里下移 3px（等价 piece_y0 与 gap_y 差 3），
   旧逻辑（闸门 2）必判死，新逻辑（y_tol=6/band=6）应接受
"""
import io
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, "src")

from qoder2api.slider import locate_gap

bg = open("logs/slider/bg.png", "rb").read()
pz = open("logs/slider/puzzle.png", "rb").read()

g0 = locate_gap(bg, pz)
print("archived default:", None if not g0 else {k: g0[k] for k in ("gap_x", "gap_y", "piece_y0", "alpha", "quality", "valid", "invalid_reason")})
assert g0 is not None
g1 = locate_gap(bg, pz, y_tol=6, band=6)
print("archived relaxed:", None if not g1 else {k: g1[k] for k in ("gap_x", "gap_y", "valid")})
assert g1 is not None

# 合成 piece_y0 偏移 +3：把拼图块画布整体下移 3 行（透明补齐）
im = Image.open(io.BytesIO(pz)).convert("RGBA")
arr = np.array(im)
shifted = np.zeros_like(arr)
shifted[3:, :] = arr[:-3, :]
buf = io.BytesIO()
Image.fromarray(shifted, "RGBA").save(buf, format="PNG")
pz_shift = buf.getvalue()

g_strict = locate_gap(bg, pz_shift)            # 默认 y_tol=2, band=3
g_relax = locate_gap(bg, pz_shift, y_tol=6, band=6)
print("shifted default:", None if not g_strict else {k: g_strict[k] for k in ("gap_x", "gap_y", "piece_y0", "valid", "invalid_reason")})
print("shifted relaxed:", None if not g_relax else {k: g_relax[k] for k in ("gap_x", "gap_y", "piece_y0", "valid", "invalid_reason")})
assert g_strict is not None and g_relax is not None
# 默认参数下 gap_x 必须与放宽一致（x 才是拖动目标，不能因放宽而跑偏）
assert g_strict["gap_x"] == g_relax["gap_x"], (g_strict["gap_x"], g_relax["gap_x"])
print("gap_x stable:", g_relax["gap_x"])
print("OK")
