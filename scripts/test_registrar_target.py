# -*- coding: utf-8 -*-
"""验证 target_success / batch_interval 行为（不启动真实浏览器）。"""
import sys
import time

sys.path.insert(0, "src")

from qoder2api import registrar as R


def test_target_stop() -> None:
    """target_success=2：母线程批次内累计 2 次成功后应自动置 stop_requested。"""
    R._run_parent = lambda pid, workers=3: _fake_parent(pid, successes=2)
    out = R.start_registration(parents=1, target_success=2, batch_interval=0)
    assert out["ok"] and out["target_success"] == 2 and out["batch_interval"] == 0, out
    for _ in range(50):
        if not R._REGISTRAR["running"]:
            break
        time.sleep(0.1)
    st = R.get_registrar_status()
    print(f"after run: stop_requested={st['stop_requested']} stats={st['stats']}")
    assert st["stop_requested"] is True, "达到目标未自动停"
    assert st["stats"]["success"] >= 2, st["stats"]


def test_unlimited() -> None:
    """target_success=0：不因成功数停止（桩只跑 1 批即退，stop 应保持 False）。"""
    R._run_parent = lambda pid, workers=3: _fake_parent(pid, successes=3)
    out = R.start_registration(parents=1, target_success=0, batch_interval=0)
    assert out["target_success"] == 0
    for _ in range(50):
        if not R._REGISTRAR["running"]:
            break
        time.sleep(0.1)
    st = R.get_registrar_status()
    print(f"unlimited: stop_requested={st['stop_requested']} stats={st['stats']}")
    assert st["stop_requested"] is False, "target=0 不应自动停"


def test_clamp() -> None:
    """参数钳制：parents 1-6、interval 0-3600、负数 target → 0。"""
    out = R.start_registration(parents=99, target_success=-5, batch_interval=99999)
    assert out["parents"] == 6, out
    assert out["target_success"] == 0, out
    assert out["batch_interval"] == 3600, out
    R.stop_registration()
    time.sleep(0.3)
    print(f"clamp OK: {out}")


def _fake_parent(pid: str, successes: int) -> None:
    """模拟一个母线程的一批：successes 个成功 + 1 个失败，然后走目标检查。"""
    time.sleep(0.2)
    for i in range(successes):
        R._finish_task(f"{pid}-fake-s{i}", "success", result={"email": f"a{i}@x.com"})
    R._finish_task(f"{pid}-fake-f", "failed", error="simulated")
    if R._maybe_stop_on_target(pid):
        return
    # 模拟批间隔（分段 sleep 语义）
    interval = float(R._REGISTRAR["batch_interval"] or 0)
    waited = 0.0
    while waited < interval and not R._REGISTRAR["stop_requested"]:
        time.sleep(min(0.1, interval - waited))
        waited += 0.1


if __name__ == "__main__":
    test_target_stop()
    test_unlimited()
    test_clamp()
    print("ALL OK")
