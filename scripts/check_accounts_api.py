# -*- coding: utf-8 -*-
"""check_accounts_api.py — 校验 /ui/accounts 是否下发 email、是否泄露 password / token。"""
from __future__ import annotations

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
r = httpx.get("http://127.0.0.1:5050/ui/accounts",
              headers={"X-Gateway-Token": tok}, timeout=20)
d = r.json()
accs = d.get("accounts") or []
print("http", r.status_code, "| accounts:", len(accs), "| active_uid:", d.get("active_uid"))
if accs:
    keys = sorted(accs[-1].keys())
    print("keys:", keys)
    for probe in ("email", "password", "security_oauth_token", "refresh_token", "machine_id"):
        print(f"  {probe:<22} in response? {'YES' if probe in keys else 'no'}")
    print("sample(last 2):")
    for a in accs[-2:]:
        print("   ", {k: a[k] for k in ("uid", "name", "email") if k in a})

# --- 导出接口校验 ---
for qs, label in (("?download=0", "内联 JSON"), ("?download=0&include_secrets=0", "内联 JSON(脱敏)")):
    r2 = httpx.get(f"http://127.0.0.1:5050/ui/accounts/export{qs}",
                   headers={"X-Gateway-Token": tok}, timeout=20)
    try:
        recs = r2.json()
    except Exception as e:
        print(f"\nexport {label}: 解析失败 {e}  body={r2.text[:200]}")
        continue
    keys = sorted(recs[0].keys()) if recs else []
    print(f"\nexport {label}: http {r2.status_code} | 条数 {len(recs)}")
    print("  keys:", keys)
    for probe in ("email", "password", "token", "refresh_token", "machine_id"):
        print(f"    {probe:<15} 导出? {'YES' if probe in keys else 'no'}")

r3 = httpx.get("http://127.0.0.1:5050/ui/accounts/export",
               headers={"X-Gateway-Token": tok}, timeout=20)
print("\nexport 默认(download=1): http", r3.status_code,
      "| Content-Type:", r3.headers.get("content-type"),
      "| Content-Disposition:", r3.headers.get("content-disposition"),
      "| bytes:", len(r3.content))

