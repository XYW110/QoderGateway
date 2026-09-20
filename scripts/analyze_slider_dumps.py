# -*- coding: utf-8 -*-
"""analyze_slider_dumps.py — 复盘每个 dump 目录：重算缺口 + 标注图。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(r"D:\Work\Project\TestProject\QoderGateway")
sys.path.insert(0, str(ROOT / "src"))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from qoder2api.slider import locate_gap  # noqa: E402

BASE = ROOT / "logs" / "slider"


def main() -> int:
    dirs = [p for p in BASE.rglob("r0_bg.png")]
    if len(sys.argv) > 1:
        dirs = [p for p in dirs if sys.argv[1] in str(p)]
    for bgp in sorted(dirs):
        d = bgp.parent
        pzp = d / "r0_puzzle.png"
        if not pzp.exists():
            continue
        g = locate_gap(bgp.read_bytes(), pzp.read_bytes())
        dj = d / "drag.json"
        drag = json.loads(dj.read_text(encoding="utf-8")) if dj.exists() else None
        print(f"--- {d.relative_to(BASE)}")
        print(f"    gap: {json.dumps(g, ensure_ascii=False)}")
        print(f"    drag: {json.dumps(drag, ensure_ascii=False)}")
        if g:
            im = cv2.imread(str(bgp))
            cv2.rectangle(im, (g["gap_x"], g["gap_y"]),
                          (g["gap_x"] + g["piece_w"], g["gap_y"] + g["piece_h"]),
                          (0, 255, 0), 1)
            cv2.line(im, (g["gap_x"], 0), (g["gap_x"], im.shape[0] - 1), (0, 0, 255), 1)
            out = d / "verify.png"
            cv2.imwrite(str(out), im)
            print(f"    annotated -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
