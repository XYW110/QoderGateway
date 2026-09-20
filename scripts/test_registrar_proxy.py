# -*- coding: utf-8 -*-
"""验证 registrar_proxy 三种状态：关闭 / 开启带 URL / 开启无 URL。"""
import importlib
import os
import sys

sys.path.insert(0, "src")

from qoder2api import env


def with_env(**kw) -> None:
    for k in ("QODER_REGISTRAR_PROXY", "QODER_REGISTRAR_PROXY_URL", "QODER_PROXY"):
        os.environ.pop(k, None)
    os.environ.update(kw)


# 1) 默认关闭 → None
with_env()
assert env.registrar_proxy() is None, "默认应不走代理"

# 2) 开启 + 专用 URL
with_env(QODER_REGISTRAR_PROXY="1", QODER_REGISTRAR_PROXY_URL="http://127.0.0.1:7890")
assert env.registrar_proxy() == "http://127.0.0.1:7890", env.registrar_proxy()

# 3) 开启 + 回退 QODER_PROXY
with_env(QODER_REGISTRAR_PROXY="true", QODER_PROXY="socks5://10.0.0.1:1080")
assert env.registrar_proxy() == "socks5://10.0.0.1:1080", env.registrar_proxy()

# 4) 开启但无地址 → None（直连）
with_env(QODER_REGISTRAR_PROXY="yes")
assert env.registrar_proxy() is None, "无地址应回退直连"

# 5) 显式关闭即使有 URL
with_env(QODER_REGISTRAR_PROXY="0", QODER_REGISTRAR_PROXY_URL="http://127.0.0.1:7890")
assert env.registrar_proxy() is None, "显式关闭应直连"

print("registrar_proxy OK")

# 顺带验证 .env.example 只含代码里存在的键
used = {
    "QODER_HOST", "QODER_PORT", "QODER_ADMIN_PASSWORD", "QODER_PROXY",
    "LOCAL_PROXY", "QODER_REGISTRAR_PROXY", "QODER_REGISTRAR_PROXY_URL",
    "QODER_SLIDER_AUTO", "QODER_USE_OLD_PROTOCOL", "QODER_FIRST_TOKEN_TIMEOUT",
    "QODER_STREAM_READ_TIMEOUT", "QODER_TOTAL_TIMEOUT", "QODER_PAT",
    "QODER_MAIL_BACKEND", "YYDS_API_KEY", "YYDS_API_BASE",
}
listed = set()
for line in open(".env.example", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        listed.add(line.split("=", 1)[0].strip())
extra = listed - used
missing = used - listed
print(f"example keys={len(listed)} 未使用={sorted(extra)} 未列={sorted(missing)}")
assert not extra, f".env.example 含无用键: {extra}"
