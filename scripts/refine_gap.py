# -*- coding: utf-8 -*-
"""refine_gap.py — 亚像素精修缺口位置。

模型：缺口 = 原图与白色遮罩的混合  bg ≈ a*piece + (1-a)*255
其中 piece 就是缺口处的原始像素 → 在正确位置残差最小。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

D = Path(r"D:\Work\Project\TestProject\QoderGateway\logs\slider")


def erode(m: np.ndarray, k: int) -> np.ndarray:
    """k x k 腐蚀（正方形结构元，纯 numpy）。"""
    out = m.copy()
    r = k // 2
    pad = np.pad(out, r, mode="constant")
    h, w = out.shape
    acc = np.ones_like(out, dtype=bool)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            acc &= pad[r + dy:r + dy + h, r + dx:r + dx + w] > 0
    return acc.astype(np.uint8)


def main() -> int:
    bg = np.array(Image.open(D / "bg.png").convert("RGB")).astype(np.float64)
    pz_full = Image.open(D / "puzzle.png").convert("RGBA")
    a = np.array(pz_full)
    ys, xs = np.where(a[:, :, 3] > 8)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    pz = np.array(pz_full.crop((x0, y0, x1 + 1, y1 + 1))).astype(np.float64)
    ph, pw = pz.shape[:2]
    print(f"piece {pw}x{ph} canvas offset ({x0},{y0})")

    core = erode((pz[:, :, 3] > 200).astype(np.uint8), 5) > 0
    print(f"interior pixels (erode5): {int(core.sum())}")

    piece_rgb = pz[:, :, :3]
    dev = piece_rgb - 255.0                      # piece-255
    denom = float((dev[core] ** 2).sum())

    rows = []
    for gy in range(max(0, y0 - 4), y0 + 5):
        for gx in range(165, 190):
            if gy + ph > bg.shape[0] or gx + pw > bg.shape[1]:
                continue
            reg = bg[gy:gy + ph, gx:gx + pw]
            num = float(((reg - 255.0)[core] * dev[core]).sum())
            alpha = num / denom if denom else 0.0
            pred = alpha * piece_rgb + (1 - alpha) * 255.0
            resid = float(((reg - pred)[core] ** 2).mean())
            rows.append((resid, gx, gy, alpha))
    rows.sort()
    print("\ntop-8 blend model (resid, gx, gy, alpha):")
    for r in rows[:8]:
        print(f"   resid={r[0]:8.2f}  gx={r[1]:3d}  gy={r[2]:3d}  alpha={r[3]:.3f}")
    best = rows[0]

    rows2 = []
    for gy in range(max(0, y0 - 4), y0 + 5):
        for gx in range(165, 190):
            if gy + ph > bg.shape[0] or gx + pw > bg.shape[1]:
                continue
            reg = bg[gy:gy + ph, gx:gx + pw]
            resid = float(((reg - piece_rgb)[core] ** 2).mean())
            rows2.append((resid, gx, gy))
    rows2.sort()
    print("\nraw content top-5 (resid, gx, gy):")
    for r in rows2[:5]:
        print(f"   resid={r[0]:8.2f}  gx={r[1]:3d}  gy={r[2]:3d}")

    print(f"\nBEST gap: gx={best[1]} gy={best[2]} alpha={best[3]:.3f} (canvas x0={x0} y0={y0})")
    print(f"puzzle CSS left (自然像素) = {best[1]} - {x0} = {best[1] - x0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
