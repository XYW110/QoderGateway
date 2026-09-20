# -*- coding: utf-8 -*-
"""fit_slider_gap.py — 离线交叉验证缺口检测（qoder = 阿里云 FeiLin 拼图）。

背景里缺口是「浅灰拼图形填充」，拼图块是「带深灰描边的内容块」，
两者颜色不同 → 内容匹配会失效，必须同时用「形状掩码匹配」交叉验证。
输出：各算法候选 x、标注图 annotated.png、饱和度高亮图 sat.png、顶部放大图 top3x.png。
"""
from __future__ import annotations

import io
import json
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


def png_bytes(im: Image.Image) -> bytes:
    b = io.BytesIO()
    im.save(b, format="PNG")
    return b.getvalue()


def mt(img, tmpl, method, mask=None):
    try:
        if mask is None:
            r = cv2.matchTemplate(img, tmpl, method)
        else:
            r = cv2.matchTemplate(img, tmpl, method, mask=mask)
    except Exception as e:  # noqa
        print("   matchTemplate fail", method, type(e).__name__, e)
        return None, None
    r = np.nan_to_num(r, nan=-1.0, posinf=1.0, neginf=-1.0)
    _, mx, _, ml = cv2.minMaxLoc(r)
    return ml, mx


def main() -> int:
    bg_im = Image.open(D / "bg.png").convert("RGBA")
    pz_im = Image.open(D / "puzzle.png").convert("RGBA")
    BW, BH = bg_im.size
    print(f"bg={bg_im.size} puzzle_full={pz_im.size}")

    a = np.array(pz_im)
    ys, xs = np.where(a[:, :, 3] > 8)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    print(f"piece alpha bbox x[{x0},{x1}] y[{y0},{y1}] -> {x1 - x0 + 1}x{y1 - y0 + 1}")
    pz_crop = pz_im.crop((x0, y0, x1 + 1, y1 + 1))
    pz_crop.save(D / "puzzle_crop.png")

    pa = np.array(pz_crop)
    tmpl_rgb = pa[:, :, :3]
    tmpl_bgr = tmpl_rgb[:, :, ::-1].copy()
    tmpl_a = pa[:, :, 3].copy()
    t_h, t_w = tmpl_a.shape[:2]
    tmpl_gray = cv2.cvtColor(tmpl_rgb, cv2.COLOR_RGB2GRAY)

    ba = np.array(bg_im)
    bg_rgb = ba[:, :, :3]
    bg_bgr = bg_rgb[:, :, ::-1].copy()
    bg_gray = cv2.cvtColor(bg_rgb, cv2.COLOR_RGB2GRAY)

    hsv = cv2.cvtColor(bg_rgb, cv2.COLOR_RGB2HSV)
    S = hsv[:, :, 1].astype(np.int16)
    V = hsv[:, :, 2].astype(np.int16)

    cands: dict[str, dict] = {}

    def rec(name, x, conf, **extra):
        d = {"x": None if x is None else round(float(x), 2),
             "conf": None if conf is None else round(float(conf), 5)}
        d.update(extra)
        cands[name] = d
        print(f"  {name:<34} x={d['x']} conf={d['conf']} {extra or ''}")

    # ---------- A/B ddddocr ----------
    try:
        import ddddocr
        det = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        for tag, tgt in (("crop", pz_crop), ("full", pz_im)):
            for simple in (False, True):
                try:
                    r = det.slide_match(png_bytes(tgt.convert("RGBA")),
                                        png_bytes(bg_im), simple_target=simple)
                    rec(f"ddddocr[{tag},simple={simple}]", r.get("target_x"),
                        r.get("confidence"), target_y=r.get("target_y"))
                except Exception as e:
                    print(f"   ddddocr fail {tag}/{simple}: {type(e).__name__} {e}")
    except Exception as e:
        print("  no ddddocr:", type(e).__name__, e)

    # ---------- C/D/E 内容匹配（带 alpha 掩码）----------
    rec("cv2 CCORR_NORMED alpha-mask",
        *(lambda p: (p[0][0] if p[0] else None, p[1]))(mt(bg_gray, tmpl_gray, cv2.TM_CCORR_NORMED, tmpl_a)))
    rec("cv2 CCOEFF_NORMED alpha-mask",
        *(lambda p: (p[0][0] if p[0] else None, p[1]))(mt(bg_gray, tmpl_gray, cv2.TM_CCOEFF_NORMED, tmpl_a)))

    # 灰度反转掩码（拼图块被深色描边 → 反色后与浅灰缺口更相似）
    rec("cv2 CCORR_NORMED invert-mask",
        *(lambda p: (p[0][0] if p[0] else None, p[1]))(
            mt(255 - bg_gray, 255 - tmpl_gray, cv2.TM_CCORR_NORMED, tmpl_a)))

    # 边缘匹配
    eg_b = cv2.Canny(bg_gray, 60, 160)
    eg_t = cv2.Canny(tmpl_gray, 60, 160)
    eg_t = cv2.bitwise_and(eg_t, eg_t, mask=tmpl_a)
    rec("cv2 edge CCOEFF_NORMED",
        *(lambda p: (p[0][0] if p[0] else None, p[1]))(mt(eg_b, eg_t, cv2.TM_CCOEFF_NORMED, tmpl_a)))

    # ---------- F 形状掩码匹配（关键：颜色无关）----------
    for s_th, v_th in ((70, 140), (90, 130), (110, 130)):
        hole = ((S < s_th) & (V > v_th)).astype(np.float32)
        core = (tmpl_a > 200).astype(np.float32)
        if core.sum() < 10:
            continue
        loc, conf = mt(hole, core, cv2.TM_CCORR_NORMED)
        if loc is None:
            continue
        # 形状匹配峰值 (0~1)：用重叠比例归一化更直观
        x, y = loc
        patch = hole[y:y + t_h, x:x + t_w]
        iou = float((patch * core).sum() / max(1.0, core.sum()))
        rec(f"shape-overlap S<{s_th},V>{v_th}", x, conf, y=y, overlap=round(iou, 3))

    # 缺口灰块自身的连通域（参考）
    for s_th, v_th in ((70, 140), (90, 130)):
        m = ((S < s_th) & (V > v_th)).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, lab, stats, cent = cv2.connectedComponentsWithStats(m, 8)
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            w_, h_ = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
            if 1200 < area < 4000 and 0.6 < w_ / max(1, h_) < 1.8:
                print(f"   blob(S<{s_th}) area={area} bbox=({stats[i,0]},{stats[i,1]},{w_}x{h_})")

    # ---------- 标注图 ----------
    colors = [(255, 0, 0), (0, 160, 0), (0, 0, 255), (255, 0, 255), (0, 180, 180),
              (128, 0, 255), (255, 128, 0), (0, 90, 255), (60, 60, 60), (0, 220, 0)]
    ann = bg_bgr.copy()
    legend = []
    for i, (name, d) in enumerate(cands.items()):
        if d["x"] is None:
            continue
        col = colors[i % len(colors)]
        xx = int(round(d["x"]))
        cv2.line(ann, (xx, 0), (xx, BH - 1), col, 1)
        cv2.putText(ann, str(i), (max(0, xx - 4), 12 + 14 * (i % 6)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, col, 1, cv2.LINE_AA)
        legend.append(f"{i}={name} x={d['x']}")
    cv2.imwrite(str(D / "annotated.png"), ann)

    sat = cv2.applyColorMap(np.clip(255 - S, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)
    cv2.imwrite(str(D / "sat.png"), sat)

    top = bg_bgr[0:80, :, :]
    top = cv2.resize(top, (top.shape[1] * 3, top.shape[0] * 3), interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(str(D / "top3x.png"), top)

    (D / "gap_candidates.json").write_text(
        json.dumps({"bg": list(bg_im.size), "piece_bbox": [x0, y0, x1, y1],
                    "piece_size": [t_w, t_h], "cands": cands},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nlegend:")
    for s in legend:
        print("  ", s)
    print("wrote annotated.png / sat.png / top3x.png / gap_candidates.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
