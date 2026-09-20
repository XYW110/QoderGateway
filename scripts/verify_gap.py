# -*- coding: utf-8 -*-
"""verify_gap.py — 终极验证：把拼图块按候选 x 贴回背景，无缝者即正确缺口。

原理：拼图块内容 = 缺口处的原始像素，贴回正确位置应当看不出接缝。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

D = Path(r"D:\Work\Project\TestProject\QoderGateway\logs\slider")


def main() -> int:
    bg = Image.open(D / "bg.png").convert("RGBA")
    pz = Image.open(D / "puzzle.png").convert("RGBA")
    W, H = bg.size

    a = np.array(pz)
    ys, xs = np.where(a[:, :, 3] > 8)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    pz = pz.crop((x0, y0, x1 + 1, y1 + 1))
    pw, ph = pz.size
    print(f"piece crop {pw}x{ph}, canvas offset ({x0},{y0})")

    # --- 精确测缺口：低饱和 + 高亮 连通域（限制上半部）---
    b = np.array(bg.convert("RGB"))
    hsv = cv2.cvtColor(b, cv2.COLOR_RGB2HSV)
    S = hsv[:, :, 1].astype(np.int16)
    V = hsv[:, :, 2].astype(np.int16)
    for s_th, v_th in ((40, 180), (55, 170), (70, 160), (85, 150)):
        m = ((S < s_th) & (V > v_th)).astype(np.uint8)
        m[70:, :] = 0
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        n, lab, stats, cent = cv2.connectedComponentsWithStats(m, 8)
        found = []
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            w_, h_ = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
            if area > 800:
                found.append((area, int(stats[i, 0]), int(stats[i, 1]), w_, h_))
        found.sort(reverse=True)
        print(f"S<{s_th},V>{v_th} -> {found[:3]}")

    # --- 贴回验证 ---
    bg_a = np.array(bg).astype(np.float32)
    pz_a = np.array(pz).astype(np.float32)
    al = (pz_a[:, :, 3:4] / 255.0)

    def composite(gx: int, gy: int) -> np.ndarray:
        out = bg_a.copy()
        reg = out[gy:gy + ph, gx:gx + pw, :3]
        out[gy:gy + ph, gx:gx + pw, :3] = reg * (1 - al) + pz_a[:, :, :3] * al
        return np.clip(out[:, :, :3], 0, 255).astype(np.uint8)

    for gx in (174, 175, 176, 197, 200):
        if gx + pw > W:
            continue
        img = composite(gx, y0)
        cv2.imwrite(str(D / f"paste_{gx}.png"), img[:, :, ::-1])
        # 局部放大（缺口周围 ±30px）
        x_a, x_b = max(0, gx - 30), min(W, gx + pw + 30)
        y_a, y_b = max(0, y0 - 20), min(H, y0 + ph + 20)
        crop = img[y_a:y_b, x_a:x_b, :]
        crop = cv2.resize(crop, (crop.shape[1] * 4, crop.shape[0] * 4), interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(str(D / f"paste_{gx}_zoom.png"), crop[:, :, ::-1])
    print("wrote paste_*.png / paste_*_zoom.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
