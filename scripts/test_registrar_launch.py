# -*- coding: utf-8 -*-
"""验证 _free_port 并发去重 + RegistrarBot 真实启动/关闭一次。"""
import concurrent.futures
import sys
import time

sys.path.insert(0, "src")

from qoder2api.registrar import _free_port, _release_port, RegistrarBot


def t_ports() -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        ports = list(ex.map(lambda _: _free_port(), range(64)))
    dup = len(ports) - len(set(ports))
    print(f"ports={len(ports)} unique={len(set(ports))} dup={dup}")
    assert dup == 0, "端口分配有重复！"
    for p in ports:
        _release_port(p)
    print("port alloc OK")


def t_launch() -> None:
    t0 = time.time()
    bot = RegistrarBot(task_id="selftest", cleanup_profile=True)
    print(f"launch OK in {time.time()-t0:.1f}s port={bot._port} profile={bot.profile_dir}")
    bot.page.get("https://qoder.com/users/sign-up")
    time.sleep(2)
    print("title:", bot.page.title[:60])
    bot.close()
    print("closed OK")


if __name__ == "__main__":
    t_ports()
    t_launch()
