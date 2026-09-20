# -*- coding: utf-8 -*-
"""离线自测：API Key 路由策略(routing) + 限流(ratelimit) + Key 配置(config)。

不联网、不动真实库：DB_PATH 指向临时目录。
用法：.venv\\Scripts\\python.exe scripts\\test_routing_ratelimit.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qoder2api import database as db  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="qoder_test_"))
db.DB_PATH = TMP / "test.db"
db.init_db()
assert str(db.DB_PATH).startswith(str(TMP)), db.DB_PATH

from qoder2api import config, ratelimit, routing  # noqa: E402

PASS = 0
FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAILS.append(f"{name} :: {extra}")
        print(f"  [FAIL] {name}  {extra}")


UIDS = ["uidA", "uidB", "uidC", "uidD"]
MODEL = "lite"

print("== 1. 路由策略 1（填充：同 key+模型固定账号）==")
K1 = "sk-strategy1"
seen = {routing.pick_uid(K1, MODEL, 1, UIDS) for _ in range(30)}
check("同 key+模型恒同一账号", len(seen) == 1, f"命中集合={seen}")

base = seen.pop()
check("exclude 生效(顺延到下一个)", routing.pick_uid(K1, MODEL, 1, UIDS, {base}) != base)
check("全部排除 -> None", routing.pick_uid(K1, MODEL, 1, UIDS, set(UIDS)) is None)
check("空账号池 -> None", routing.pick_uid(K1, MODEL, 1, []) is None)

# 不同 key 仍有稳定结果（不保证必不同，仅验证确定性）
other = {routing.pick_uid("sk-other", MODEL, 1, UIDS) for _ in range(10)}
check("异 key 结果仍确定", len(other) == 1)
check("模型参与哈希(不同模型可为不同账号)",
      isinstance(routing.pick_uid(K1, "pro", 1, UIDS), str))

print("== 2. 路由策略 2（严格轮询）==")
routing.reset_cursors()
K2 = "sk-strategy2"
seq = [routing.pick_uid(K2, MODEL, 2, UIDS) for _ in range(12)]
check("连续请求覆盖全部账号", set(seq) == set(UIDS), f"seq={seq}")
c = Counter(seq)
check("分布均匀(12次/4账号=各3次)", all(v == 3 for v in c.values()), str(dict(c)))
check("顺序为环上游走", seq[:4] == UIDS or seq[:4] == UIDS[1:] + UIDS[:1], f"{seq[:4]}")

routing.reset_cursors()
a = routing.pick_uid(K2, MODEL, 2, UIDS)
b = routing.pick_uid(K2, MODEL, 2, UIDS, {a})
check("策略2 重试顺延(跳过已试)", b == UIDS[(UIDS.index(a) + 1) % len(UIDS)], f"a={a} b={b}")
check("策略2 全排除 -> None", routing.pick_uid(K2, MODEL, 2, UIDS, set(UIDS)) is None)

routing.reset_cursors()
check("reset_cursors 归零", routing.cursor_snapshot() == {})
routing.pick_uid(K2, MODEL, 2, UIDS)
check("游标快照可见", routing.cursor_snapshot().get(K2) == 1)

print("== 3. 限流：RPM ==")
ratelimit.reset()
K3 = "sk-rpm"
k = 0
ok1, _, _ = ratelimit.acquire(K3, 2, 0)
ok2, _, _ = ratelimit.acquire(K3, 2, 0)
ok3, reason3, retry3 = ratelimit.acquire(K3, 2, 0)
check("limit=2 前两次放行", ok1 and ok2)
check("第 3 次拒绝", not ok3, str(reason3))
check("拒绝原因含 RPM", "RPM" in (reason3 or ""), str(reason3))
check("retry_after 在 (0,60]", 0 < retry3 <= 60.0, str(retry3))
ratelimit.release(K3)
ratelimit.release(K3)
check("rpm_used = 2", ratelimit.rpm_used(K3) == 2, str(ratelimit.rpm_used(K3)))
check("inflight 释放归零", ratelimit.inflight(K3) == 0, str(ratelimit.inflight(K3)))

# 窗口滑动：伪造 61s 前的时间戳应过期
ratelimit.reset()
t0 = time.time()
for _ in range(2):
    ratelimit.acquire(K3, 2, 0, now=t0)
ok_old, _, _ = ratelimit.acquire(K3, 2, 0, now=t0 + 1)
check("窗口内仍受限", not ok_old)
ok_new, _, _ = ratelimit.acquire(K3, 2, 0, now=t0 + 61)
check("60s 后窗口滚动放行", ok_new)

print("== 4. 限流：并发 ==")
ratelimit.reset()
K4 = "sk-conc"
o1, _, _ = ratelimit.acquire(K4, 0, 1)
o2, r2, _ = ratelimit.acquire(K4, 0, 1)
check("并发=1 第 1 次放行", o1)
check("并发=1 第 2 次拒绝", not o2, str(r2))
check("拒绝原因含 concurrency", "concurrency" in (r2 or ""), str(r2))
check("inflight=1", ratelimit.inflight(K4) == 1)
ratelimit.release(K4)
check("release 后 inflight=0", ratelimit.inflight(K4) == 0)
o3, _, _ = ratelimit.acquire(K4, 0, 1)
check("release 后可再次进入", o3)
ratelimit.release(K4)
ratelimit.release(K4)
check("重复 release 不出现负数", ratelimit.inflight(K4) == 0)

print("== 5. limit = 0 表示不限 ==")
ratelimit.reset()
K5 = "sk-zero"
allok = all(ratelimit.acquire(K5, 0, 0)[0] for _ in range(200))
check("RPM/并发=0 连续 200 次全部放行", allok)
check("0 限额不记录 RPM", ratelimit.rpm_used(K5) == 0, str(ratelimit.rpm_used(K5)))
check("0 限额仍占并发名额(需释放)", ratelimit.inflight(K5) == 200)
for _ in range(200):
    ratelimit.release(K5)
check("全部释放后 inflight=0", ratelimit.inflight(K5) == 0)

print("== 6. API Key 配置：名称 / 策略 / 限额 ==")
config.save_config({"auth_required": False, "allowed_keys": ["sk-a"]})
rec = config.upsert_api_key({"api_key": "sk-a", "name": "我的Key", "strategy": 2,
                             "rpm_limit": 60, "concurrency_limit": 5})
check("upsert 回显", rec["name"] == "我的Key" and rec["strategy"] == 2
      and rec["rpm_limit"] == 60 and rec["concurrency_limit"] == 5, str(rec))
check("get_api_key 读回名称", config.get_api_key("sk-a")["name"] == "我的Key")
check("created_at 已写入", bool(config.get_api_key("sk-a")["created_at"]))

# 旧前端 string[] 接口不得抹掉新字段
config.save_config({"allowed_keys": ["sk-a", "sk-b"]})
r2 = config.get_api_key("sk-a")
check("旧 /ui/config 不抹掉 name/strategy/rpm", r2["name"] == "我的Key"
      and r2["strategy"] == 2 and r2["rpm_limit"] == 60, str(r2))
rb = config.get_api_key("sk-b")
check("新增 key 使用默认值(1/0/0)", rb["strategy"] == 1 and rb["rpm_limit"] == 0
      and rb["concurrency_limit"] == 0 and rb["enabled"] == 1, str(rb))

cfg = config.load_config()
check("load_config 下发 api_keys 详情", len(cfg["api_keys"]) == 2, str(len(cfg["api_keys"])))
check("allowed_keys 向后兼容=已启用列表",
      cfg["allowed_keys"] == ["sk-a", "sk-b"], str(cfg["allowed_keys"]))

# 部分更新：只改限额，其余保留
config.upsert_api_key({"api_key": "sk-a", "rpm_limit": 0})
r3 = config.get_api_key("sk-a")
check("部分更新保留 name/strategy", r3["name"] == "我的Key" and r3["strategy"] == 2, str(r3))
check("部分更新写入 rpm=0", r3["rpm_limit"] == 0)

print("== 7. 校验与边界 ==")
try:
    config.upsert_api_key({"api_key": "  "})
    check("空 api_key 报错", False, "未抛 ValueError")
except ValueError as e:
    check("空 api_key 报错", True)
try:
    config.upsert_api_key({"api_key": "sk-a", "strategy": 9})
    check("非法 strategy 报错", False, "未抛 ValueError")
except ValueError as e:
    check("非法 strategy 报错", "strategy" in str(e), str(e))
r4 = config.upsert_api_key({"api_key": "sk-a", "strategy": 1, "rpm_limit": -5,
                            "concurrency_limit": -3})
check("负数限额归零", r4["rpm_limit"] == 0 and r4["concurrency_limit"] == 0, str(r4))

print("== 8. 启用开关 ==")
config.upsert_api_key({"api_key": "sk-off", "enabled": False})
cfg2 = config.load_config()
check("enabled=0 不进 allowed_keys", "sk-off" not in cfg2["allowed_keys"], str(cfg2["allowed_keys"]))
check("enabled=0 仍在 api_keys 详情中",
      any(k["api_key"] == "sk-off" and k["enabled"] == 0 for k in cfg2["api_keys"]))
config.upsert_api_key({"api_key": "sk-off", "rpm_limit": 9})
check("未传 enabled 时保留旧值(仍为 0)",
      config.get_api_key("sk-off")["enabled"] == 0, str(config.get_api_key("sk-off")))
config.upsert_api_key({"api_key": "sk-off", "enabled": True})
check("重新启用生效", "sk-off" in config.load_config()["allowed_keys"])
check("enabled 显式 false 生效",
      config.upsert_api_key({"api_key": "sk-off", "enabled": 0})["enabled"] == 0)
check("enabled 缺省新建=1",
      config.upsert_api_key({"api_key": "sk-new"})["enabled"] == 1)

print("== 9. 删除 ==")
check("delete 返回 True", config.delete_api_key("sk-a") is True)
check("删除后读不到", config.get_api_key("sk-a") is None)
check("重复删除返回 False", config.delete_api_key("sk-a") is False)
left = {k["api_key"] for k in config.list_api_keys()}
check("剩余 key 正确", left == {"sk-b", "sk-off", "sk-new"}, str(left))

print("== 10. 与 app.py 的对接面（无网络导入检查）==")
import qoder2api.app as app_mod  # noqa: E402
routes = {r.path for r in app_mod.app.routes if hasattr(r, "path")}
for p in ("/ui/keys", "/ui/keys/{api_key}", "/v1/chat/completions", "/ui/config"):
    check(f"路由已注册 {p}", p in routes, str(sorted(routes)))
check("_pick_session 可调用", callable(getattr(app_mod, "_pick_session", None)))

print()
print(f"临时库：{db.DB_PATH}")
print(f"结果：PASS={PASS} FAIL={len(FAILS)}")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL TESTS PASSED")
