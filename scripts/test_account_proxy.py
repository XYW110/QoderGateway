# -*- coding: utf-8 -*-
"""账号级代理测试：
1) resolve_proxy 优先级：账号开 > 账号开但无地址(回退全局) > 账号关(全局) > 都没(直连)
2) 带账号密码时拼 URL userinfo 并做 URL 编码；无密码只拼 user
3) set_account_proxy：保存/脱敏返回/空密码保留
4) client 池按代理分组：同代理同一 client，不同代理不同 client
"""
import asyncio
import os
import sys

sys.path.insert(0, "src")

from qoder2api import accounts, bridge
from qoder2api.auth import AuthIdentity, SessionContext
from qoder2api.database import get_db


def mk_sess(**kw) -> SessionContext:
    ident = AuthIdentity(name="t", aid="u", uid="u", yx_uid="", organization_id="",
                         organization_name="", user_type="", security_oauth_token="x",
                         refresh_token="y")
    return SessionContext(temp_key=b"k" * 16, cosy_key="c", info="i", identity=ident,
                          machine_id="m", machine_token="mt", machine_type="mty", **kw)


def t_resolve() -> None:
    os.environ.pop("QODER_PROXY", None)
    # 账号未启用 → 直连
    assert bridge.resolve_proxy(mk_sess()) is None
    # 账号启用 + 地址
    s = mk_sess(proxy_enabled=True, proxy_url="http://127.0.0.1:7890")
    assert bridge.resolve_proxy(s) == "http://127.0.0.1:7890"
    # 账号启用但地址为空 → 回退全局
    os.environ["QODER_PROXY"] = "http://global:8080"
    assert bridge.resolve_proxy(mk_sess(proxy_enabled=True, proxy_url="")) == "http://global:8080"
    # 账号关闭 → 全局
    assert bridge.resolve_proxy(mk_sess(proxy_enabled=False, proxy_url="http://a:1")) == "http://global:8080"
    # 账号优先于全局
    assert bridge.resolve_proxy(mk_sess(proxy_enabled=True, proxy_url="socks5://1.2.3.4:1080")) == "socks5://1.2.3.4:1080"
    os.environ.pop("QODER_PROXY", None)
    # 账号 + 密码（含需编码特殊字符）
    s = mk_sess(proxy_enabled=True, proxy_url="http://1.2.3.4:8080",
                proxy_username="u ser@1", proxy_password="p@ss/w:ord")
    got = bridge.resolve_proxy(s)
    print("with creds:", got)
    assert got == "http://u%20ser%401:p%40ss%2Fw%3Aord@1.2.3.4:8080", got
    # 只有账号没有密码
    s = mk_sess(proxy_enabled=True, proxy_url="http://1.2.3.4:8080", proxy_username="user")
    assert bridge.resolve_proxy(s) == "http://user@1.2.3.4:8080"
    # 无 scheme 的地址（用户只写 ip:port）→ 原样返回，不拼 userinfo
    s = mk_sess(proxy_enabled=True, proxy_url="127.0.0.1:7890", proxy_username="user")
    assert bridge.resolve_proxy(s) == "127.0.0.1:7890"
    print("resolve_proxy OK")


async def t_pool() -> None:
    a = await bridge.client_for(mk_sess(proxy_enabled=True, proxy_url="http://127.0.0.1:7890"))
    b = await bridge.client_for(mk_sess(proxy_enabled=True, proxy_url="http://127.0.0.1:7890"))
    c = await bridge.client_for(mk_sess(proxy_enabled=True, proxy_url="http://127.0.0.1:7891"))
    d = await bridge.client_for(mk_sess())
    print(f"pool: same={a is b} diff={a is not c} direct_separate={d is not a}")
    assert a is b and a is not c and d is not a
    await bridge.close_shared_client()
    e = await bridge.client_for(mk_sess(proxy_enabled=True, proxy_url="http://127.0.0.1:7890"))
    assert e is not a and a.is_closed
    await bridge.close_shared_client()
    print("client pool OK")


def t_db() -> None:
    with get_db() as conn:
        row = conn.execute("SELECT uid FROM accounts WHERE enabled = 1 AND security_oauth_token != '' LIMIT 1").fetchone()
    if not row:
        print("db: 无可用账号，跳过")
        return
    uid = row[0]
    r1 = accounts.set_account_proxy(uid, enabled=True, url="http://127.0.0.1:7890",
                                    username="user1", password="secret1")
    assert r1["proxy_enabled"] and r1["proxy_url"] == "http://127.0.0.1:7890"
    assert r1["proxy_username"] == "user1" and r1["proxy_password_set"] is True
    assert "proxy_password" not in r1, "密码不得回显"
    # 空密码 → 保留
    r2 = accounts.set_account_proxy(uid, enabled=True, url="", username="", password="")
    assert r2["proxy_password_set"] is True and r2["proxy_url"] == ""
    # 关开关
    r3 = accounts.set_account_proxy(uid, enabled=False, url="http://x:1", username="u", password=None)
    assert r3["proxy_enabled"] is False and r3["proxy_password_set"] is True
    # 列表接口不泄露密码
    data = accounts.db_load_accounts()
    acc = next(a for a in data["accounts"] if a["uid"] == uid)
    assert "proxy_password" not in acc and acc.get("proxy_password_set") in (True, False)
    # 缓存已失效 → 新会话带新代理配置
    s = accounts.get_session_for_uid_cached(uid)
    assert s.proxy_enabled is False
    accounts.set_account_proxy(uid, enabled=True, url="http://127.0.0.1:9999", username="", password=None)
    s2 = accounts.get_session_for_uid_cached(uid)
    assert s2.proxy_enabled is True and s2.proxy_url == "http://127.0.0.1:9999", s2.proxy_url
    # 还原为关闭
    accounts.set_account_proxy(uid, enabled=False, url="", username="", password=None)
    r = accounts.set_account_proxy(uid, enabled=False, url="", username="", password=None)
    assert r["proxy_enabled"] is False and r["proxy_url"] == ""
    print("db proxy OK")


async def main() -> None:
    t_resolve()
    await t_pool()
    t_db()
    print("ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
