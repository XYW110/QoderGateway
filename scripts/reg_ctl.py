# -*- coding: utf-8 -*-
"""reg_ctl.py — 网关注册机控制台（start/stop/status）。

用法：
  python scripts/reg_ctl.py start [parents]
  python scripts/reg_ctl.py stop
  python scripts/reg_ctl.py status [tail]
"""
from __future__ import annotations

import json
import sys

import httpx

from qoder2api.config import load_config
from qoder2api.env import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = "http://127.0.0.1:5050"


def main() -> int:
    load_dotenv()
    tok = load_config()["gateway_token"]
    h = {"X-Gateway-Token": tok}
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()

    if cmd == "start":
        parents = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        r = httpx.post(f"{BASE}/ui/registrar/start", headers=h,
                       json={"parents": parents}, timeout=30)
        print("start ->", r.status_code, r.text[:400])
        return 0
    if cmd == "stop":
        r = httpx.post(f"{BASE}/ui/registrar/stop", headers=h, timeout=30)
        print("stop ->", r.status_code, r.text[:400])
        return 0

    tail = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    r = httpx.get(f"{BASE}/ui/registrar/status", headers=h, timeout=20)
    d = r.json()
    print("running:", d.get("running"), "| stats:", d.get("stats"),
          "| verify:", json.dumps(d.get("verification"), ensure_ascii=False))
    tasks = {**d.get("active", {}), **d.get("recent", {})}
    for tid, t in tasks.items():
        print("--- %s stage=%s err=%s" % (tid, t.get("stage"), t.get("error")))
        for ln in (t.get("logs") or [])[-tail:]:
            print("   ", ln)
    if not tasks:
        print("(no tasks yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
