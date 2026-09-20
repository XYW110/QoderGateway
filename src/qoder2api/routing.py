# -*- coding: utf-8 -*-
"""routing.py — 按 API Key 的「路由策略」挑选账号。

策略（allowed_keys.strategy）：
  1 = 填充：同一 key + 同一模型恒定命中同一账号（crc32(key#model) % N，无状态推导，
      不落库；账号池增减时映射会随之漂移）
  2 = 轮询：每个请求依次取下一个账号（严格 round-robin，进程内游标，重启归零）

对外只用 pick_uid()：给定候选 uid 排序列表，返回本请求应使用的 uid。
失败重试时把已试过的 uid 放进 exclude，会顺延到下一个候选。
"""
from __future__ import annotations

import threading
import zlib

_LOCK = threading.Lock()
_RR_CURSOR: dict[str, int] = {}     # api_key -> 轮询游标


def _stable_index(salt: str, n: int) -> int:
    return zlib.crc32(salt.encode("utf-8")) % max(1, n)


def pick_uid(api_key: str, model: str, strategy: int, uids: list[str],
             exclude: set[str] | None = None) -> str | None:
    """在 uids（须是稳定排序的已启用账号）里挑一个 uid。

    exclude 中的 uid 会被跳过；全部被排除时返回 None（调用方自行兜底）。
    """
    if not uids:
        return None
    avail = [u for u in uids if not exclude or u not in exclude]
    if not avail:
        return None
    n_full = len(uids)

    if int(strategy or 2) == 1:
        # 填充：基准位固定，重试时顺延
        base = _stable_index(f"{api_key}#{model}", n_full)
        for i in range(n_full):
            uid = uids[(base + i) % n_full]
            if not exclude or uid not in exclude:
                return uid
        return None

    # 轮询：游标按整池步进，保证请求平均分布；重试顺延
    with _LOCK:
        cur = _RR_CURSOR.get(api_key, 0)
        for i in range(n_full):
            uid = uids[(cur + i) % n_full]
            if not exclude or uid not in exclude:
                _RR_CURSOR[api_key] = (cur + i + 1) % n_full
                return uid
        _RR_CURSOR[api_key] = (cur + 1) % n_full
        return None


def reset_cursors() -> None:
    with _LOCK:
        _RR_CURSOR.clear()


def cursor_snapshot() -> dict[str, int]:
    with _LOCK:
        return dict(_RR_CURSOR)
