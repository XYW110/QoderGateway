# -*- coding: utf-8 -*-
"""poll_reg.py — 轮询网关注册机状态（本地诊断用）。"""
import sys

import httpx

from qoder2api.config import load_config
from qoder2api.env import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()
tok = load_config()["gateway_token"]
r = httpx.get(
    "http://127.0.0.1:5050/ui/registrar/status",
    headers={"X-Gateway-Token": tok},
    timeout=20,
)
d = r.json()
print("running:", d.get("running"), "| stats:", d.get("stats"),
      "| verify:", d.get("verification"))
tasks = {**d.get("active", {}), **d.get("recent", {})}
for tid, t in tasks.items():
    print("--- %s stage=%s err=%s" % (tid, t.get("stage"), t.get("error")))
    for ln in t.get("logs", [])[-60:]:
        print("   ", ln)
if not tasks:
    print("(no tasks yet)")
