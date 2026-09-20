# -*- coding: utf-8 -*-
"""test_locate_gap.py — 用已落盘素材验证 src/qoder2api/slider.py::locate_gap。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"D:\Work\Project\TestProject\QoderGateway")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from qoder2api.slider import locate_gap  # noqa: E402

D = ROOT / "logs" / "slider"

for tag in ("", "_r1"):
    bg = D / f"bg{tag}.png"
    pz = D / f"puzzle{tag}.png"
    if not bg.exists() or not pz.exists():
        continue
    g = locate_gap(bg.read_bytes(), pz.read_bytes())
    print(f"[{bg.name}] -> {json.dumps(g, ensure_ascii=False)}")
