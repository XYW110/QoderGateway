# -*- coding: utf-8 -*-
"""验证 _SLIDE_LOCK 串行语义：3 线程并发求解不得重叠。"""
import sys
import threading
import time

sys.path.insert(0, "src")

from qoder2api.registrar import _SLIDE_LOCK

inside = 0
max_inside = 0
lock = threading.Lock()


def worker(i: int) -> None:
    global inside, max_inside
    with _SLIDE_LOCK:
        with lock:
            inside += 1
            max_inside = max(max_inside, inside)
        time.sleep(0.3)  # 模拟一次求解耗时
        with lock:
            inside -= 1


t0 = time.time()
threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
for t in threads:
    t.start()
for t in threads:
    t.join()
elapsed = time.time() - t0
print(f"max concurrent inside lock = {max_inside} (expect 1)")
print(f"elapsed = {elapsed:.2f}s (expect >= 0.9s for serialized)")
assert max_inside == 1, "锁未串行！"
assert elapsed >= 0.85, "疑似并行执行！"
print("serialized OK")
