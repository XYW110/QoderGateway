# -*- coding: utf-8 -*-
"""ratelimit.py — 按 API Key 维度的限流：RPM（每分钟请求数）+ 并发数。

约定：limit = 0 表示不限。计数为**进程内内存态**（不落库，重启归零）。
- RPM：60s 滑动窗口（deque 记录命中时间戳）
- 并发：inflight 计数，请求进入 +1、结束（含流式结束）必须 release

acquire() 先判并发再判 RPM；两者都通过才占用并发名额。返回 (ok, reason, retry_after)。
"""
from __future__ import annotations

import collections
import threading
import time

_LOCK = threading.Lock()
_RPM: dict[str, collections.deque] = {}
_INFLIGHT: dict[str, int] = {}
WINDOW = 60.0


def acquire(api_key: str, rpm_limit: int, concurrency_limit: int,
            now: float | None = None) -> tuple[bool, str | None, float]:
    rpm_limit = int(rpm_limit or 0)
    concurrency_limit = int(concurrency_limit or 0)
    t = time.time() if now is None else now
    with _LOCK:
        if concurrency_limit > 0 and _INFLIGHT.get(api_key, 0) >= concurrency_limit:
            return False, (f"concurrency limit {concurrency_limit} exceeded "
                           f"(inflight={_INFLIGHT.get(api_key, 0)})"), 1.0
        if rpm_limit > 0:
            q = _RPM.setdefault(api_key, collections.deque())
            while q and t - q[0] > WINDOW:
                q.popleft()
            if len(q) >= rpm_limit:
                retry = max(0.5, WINDOW - (t - q[0]))
                return False, (f"RPM limit {rpm_limit}/min exceeded "
                               f"(used={len(q)})"), retry
            q.append(t)
        _INFLIGHT[api_key] = _INFLIGHT.get(api_key, 0) + 1
        return True, None, 0.0


def release(api_key: str) -> None:
    with _LOCK:
        n = _INFLIGHT.get(api_key, 0) - 1
        _INFLIGHT[api_key] = n if n > 0 else 0


def rpm_used(api_key: str, now: float | None = None) -> int:
    t = time.time() if now is None else now
    with _LOCK:
        q = _RPM.get(api_key)
        if not q:
            return 0
        while q and t - q[0] > WINDOW:
            q.popleft()
        return len(q)


def inflight(api_key: str) -> int:
    with _LOCK:
        return _INFLIGHT.get(api_key, 0)


def usage(api_key: str) -> dict:
    return {"rpm_used": rpm_used(api_key), "inflight": inflight(api_key)}


def reset() -> None:
    with _LOCK:
        _RPM.clear()
        _INFLIGHT.clear()
