# -*- coding: utf-8 -*-
"""并发改造单测：
1) account_slot 限流（ACCOUNT_CONCURRENCY=2 → 并发上限 2，溢出等待）
2) shared_client 单例 + close
3) get_session_for_uid_cached TTL 命中 + invalidate 失效
"""
import asyncio
import os
import sys
import time

os.environ["QODER_ACCOUNT_CONCURRENCY"] = "2"
os.environ["QODER_ACCOUNT_SLOT_WAIT"] = "2"
os.environ["QODER_SESSION_CACHE_TTL"] = "1"

sys.path.insert(0, "src")

from qoder2api import bridge, accounts


async def t_slot() -> None:
    inside = 0
    max_inside = 0

    async def worker() -> None:
        nonlocal inside, max_inside
        async with bridge.account_slot("uid-test"):
            inside += 1
            max_inside = max(max_inside, inside)
            await asyncio.sleep(0.2)
            inside -= 1

    t0 = time.time()
    await asyncio.gather(*[worker() for _ in range(6)])
    print(f"slot: max_inside={max_inside} (expect 2), elapsed={time.time()-t0:.2f}s (expect >= 0.6s)")
    assert max_inside == 2, "账号闸未限流"
    assert time.time() - t0 >= 0.55, "疑似未排队"

    # 槽位全占满且等待超时 → AccountSlotBusy
    holders = [bridge.account_slot("uid-busy") for _ in range(2)]
    for h in holders:
        await h.__aenter__()
    try:
        async with bridge.account_slot("uid-busy"):
            print("busy: 未抛异常（意外）")
    except bridge.AccountSlotBusy as e:
        print(f"busy: AccountSlotBusy OK ({str(e)[:60]})")
    finally:
        for h in holders:
            await h.__aexit__(None, None, None)


async def t_client() -> None:
    c1 = await bridge.shared_client()
    c2 = await bridge.shared_client()
    print(f"client singleton: {c1 is c2}")
    assert c1 is c2, "共享 client 不是单例"
    await bridge.close_shared_client()
    c3 = await bridge.shared_client()
    print(f"client recreated after close: {c3 is not c1} closed={c1.is_closed}")
    assert c3 is not c1 and c1.is_closed
    await bridge.close_shared_client()


def t_session_cache() -> None:
    from qoder2api.database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT uid FROM accounts WHERE enabled = 1 AND security_oauth_token != '' LIMIT 1").fetchone()
    if not row:
        print("session cache: 无可用账号，跳过")
        return
    uid = row[0]
    s1 = accounts.get_session_for_uid_cached(uid)
    s2 = accounts.get_session_for_uid_cached(uid)
    print(f"session cache hit(same object): {s1 is s2}")
    assert s1 is s2, "缓存未命中"
    accounts.invalidate_session_cache(uid)
    s3 = accounts.get_session_for_uid_cached(uid)
    print(f"session cache after invalidate(new object): {s3 is not s1}")
    assert s3 is not s1, "失效后应重建"


async def main() -> None:
    await t_slot()
    await t_client()
    t_session_cache()
    print("ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
