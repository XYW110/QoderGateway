# -*- coding: utf-8 -*-
"""API Key 端到端测试（真实 5050 网关 + 进程内 TestClient）。

A. 真实 HTTP：GET/POST/DELETE /ui/keys 全流程 + 旧 /ui/config 兼容性（收尾自动还原真实库）
B. 进程内 TestClient（临时库，不联网）：/v1/chat/completions 的 401 与 429(Retry-After)

安全：网关 token 只在进程内使用，**不打印**。
用法：.venv\\Scripts\\python.exe scripts\\test_api_keys.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402

BASE = os.getenv("QODER_BASE", "http://127.0.0.1:5050")
TEST_KEY = f"sk-selftest-{int(time.time())}"
TEST_NAME = "自测Key"

PASS = 0
FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAILS.append(name)
        print(f"  [FAIL] {name}  {extra}")


from qoder2api import config  # noqa: E402

# 注意：此处 load_config 读的是**真实库**，token 仅留在内存
_real_cfg = config.load_config()
TOKEN = _real_cfg["gateway_token"]
H = {"x-gateway-token": TOKEN}
ORIG_AUTH = bool(_real_cfg.get("auth_required"))
ORIG_KEYS = [k["api_key"] for k in _real_cfg.get("api_keys", [])]
print(f"网关 {BASE} | 原有 key 数={len(ORIG_KEYS)} | auth_required={ORIG_AUTH}")

c = httpx.Client(base_url=BASE, timeout=20.0)

print("== A. 真实网关 /ui/keys ==")
try:
    r = c.get("/ui/keys")
    check("无 token -> 401", r.status_code == 401, str(r.status_code))

    r = c.get("/ui/keys", headers=H)
    check("带 token -> 200", r.status_code == 200, r.text[:200])
    body = r.json() if r.status_code == 200 else {}
    check("返回 keys 列表", isinstance(body.get("keys"), list), str(body)[:200])
    check("返回 auth_required 字段", "auth_required" in body, str(body)[:200])

    r = c.post("/ui/keys", headers=H, json={
        "api_key": TEST_KEY, "name": TEST_NAME, "strategy": 2,
        "rpm_limit": 3, "concurrency_limit": 2, "enabled": True})
    check("POST 新建 key -> 200", r.status_code == 200, r.text[:300])
    rec = (r.json() or {}).get("key", {}) if r.status_code == 200 else {}
    check("回显 name/strategy/rpm/conc",
          rec.get("name") == TEST_NAME and rec.get("strategy") == 2
          and rec.get("rpm_limit") == 3 and rec.get("concurrency_limit") == 2, str(rec))
    check("回显实时用量字段", "rpm_used" in rec and "inflight" in rec, str(rec))

    r = c.post("/ui/keys", headers=H, json={"api_key": TEST_KEY, "rpm_limit": 0})
    rec2 = (r.json() or {}).get("key", {}) if r.status_code == 200 else {}
    check("部分更新保留 name/strategy",
          rec2.get("name") == TEST_NAME and rec2.get("strategy") == 2, str(rec2))
    check("部分更新写入 rpm_limit=0", rec2.get("rpm_limit") == 0, str(rec2))

    r = c.get("/ui/keys", headers=H)
    listed = [k for k in (r.json().get("keys") or []) if k["api_key"] == TEST_KEY]
    check("GET 能读回该 key", len(listed) == 1, str(r.json())[:300])
    check("rpm_used/inflight 已注入", bool(listed) and "rpm_used" in listed[0] and "inflight" in listed[0])

    r = c.post("/ui/keys", headers=H, json={"api_key": TEST_KEY, "strategy": 7})
    check("非法 strategy -> 400", r.status_code == 400, str(r.status_code))
    r = c.post("/ui/keys", headers=H, json={"api_key": "   "})
    check("空 api_key -> 400", r.status_code == 400, str(r.status_code))

    # 旧接口兼容：不应抹掉 name/strategy
    keep = list(dict.fromkeys(ORIG_KEYS + [TEST_KEY]))
    r = c.post("/ui/config", headers=H, json={"auth_required": ORIG_AUTH, "allowed_keys": keep})
    check("旧 POST /ui/config -> 200", r.status_code == 200, r.text[:200])
    r = c.get("/ui/keys", headers=H)
    listed = [k for k in (r.json().get("keys") or []) if k["api_key"] == TEST_KEY]
    check("旧接口未抹掉 name/strategy",
          bool(listed) and listed[0]["name"] == TEST_NAME and listed[0]["strategy"] == 2, str(listed))

    r = c.delete(f"/ui/keys/{TEST_KEY}", headers=H)
    check("DELETE -> 200", r.status_code == 200, r.text[:200])
    r = c.get("/ui/keys", headers=H)
    check("删除后不在列表",
          not any(k["api_key"] == TEST_KEY for k in (r.json().get("keys") or [])))
    r = c.delete(f"/ui/keys/{TEST_KEY}", headers=H)
    check("重复 DELETE -> 404", r.status_code == 404, str(r.status_code))
finally:
    # 收尾：还原真实库（只动我们自己的测试 key，其余保持原样）
    try:
        c.post("/ui/config", headers=H,
               json={"auth_required": ORIG_AUTH, "allowed_keys": ORIG_KEYS})
        c.delete(f"/ui/keys/{TEST_KEY}", headers=H)
        final = c.get("/ui/keys", headers=H).json()
        left = [k["api_key"] for k in final.get("keys", [])]
        same = sorted(left) == sorted(ORIG_KEYS)
        restored = bool(final.get("auth_required")) == ORIG_AUTH
        check("收尾还原原库状态", same and restored, f"left={left} auth={final.get('auth_required')}")
    except Exception as e:
        check("收尾还原原库状态", False, repr(e))

print("== B. 进程内 /v1/chat/completions 鉴权与限流（临时库，不联网）==")
from qoder2api import database as db  # noqa: E402

db.DB_PATH = Path(tempfile.mkdtemp(prefix="qoder_keys_")) / "t.db"
db.init_db()

import qoder2api.app as appmod  # noqa: E402  (必须在 DB_PATH 改写后导入)
from fastapi.testclient import TestClient  # noqa: E402

config.save_config({"auth_required": True, "gateway_token": "t0k"})
client = TestClient(appmod.app)
AUTH = {"authorization": "Bearer sk-live"}

r = client.post("/v1/chat/completions", json={"model": "lite", "messages": []})
check("鉴权开启 + 无 key -> 401", r.status_code == 401, f"{r.status_code} {r.text[:120]}")

r = client.post("/v1/chat/completions", json={"model": "lite", "messages": []},
                headers={"authorization": "Bearer wrong"})
check("鉴权开启 + 非法 key -> 401", r.status_code == 401, f"{r.status_code}")

config.upsert_api_key({"api_key": "sk-live", "name": "闸门", "strategy": 1, "enabled": False})
r = client.post("/v1/chat/completions", json={"model": "lite", "messages": []}, headers=AUTH)
check("已停用的 key -> 401", r.status_code == 401, f"{r.status_code}")

config.upsert_api_key({"api_key": "sk-live", "name": "闸门", "strategy": 2,
                       "rpm_limit": 1, "concurrency_limit": 0, "enabled": True})
appmod.ratelimit.reset()
appmod.ratelimit.acquire("sk-live", 1, 0)   # 占满 1 次配额（不发真实请求）
r = client.post("/v1/chat/completions", json={"model": "lite", "messages": []}, headers=AUTH)
check("超 RPM -> 429", r.status_code == 429, f"{r.status_code} {r.text[:120]}")
check("429 带 Retry-After", "retry-after" in {k.lower() for k in r.headers}, str(dict(r.headers)))
check("429 原因含 RPM", "RPM" in r.text, r.text[:160])

config.upsert_api_key({"api_key": "sk-live", "rpm_limit": 0, "concurrency_limit": 1})
appmod.ratelimit.reset()
appmod.ratelimit.acquire("sk-live", 0, 1)
r = client.post("/v1/chat/completions", json={"model": "lite", "messages": []}, headers=AUTH)
check("超并发 -> 429", r.status_code == 429, f"{r.status_code}")
check("429 原因含 concurrency", "concurrency" in r.text, r.text[:160])
appmod.ratelimit.release("sk-live")

config.upsert_api_key({"api_key": "sk-live", "rpm_limit": 0, "concurrency_limit": 0})
appmod.ratelimit.reset()
for _ in range(3):
    appmod.ratelimit.acquire("sk-live", 0, 0)
r = client.post("/v1/chat/completions", json={"model": "lite", "messages": []}, headers=AUTH)
check("limit=0 不被限流拦截", r.status_code != 429, f"{r.status_code} {r.text[:160]}")

config.save_config({"auth_required": False})
appmod.ratelimit.reset()
r = client.post("/v1/chat/completions", json={"model": "lite", "messages": []},
                headers={"authorization": "Bearer wrong"})
check("关鉴权时非法 key 不 401", r.status_code != 401, f"{r.status_code}")

c.close()
print()
print(f"结果：PASS={PASS} FAIL={len(FAILS)}")
if FAILS:
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL TESTS PASSED")
