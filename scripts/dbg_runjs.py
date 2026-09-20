# -*- coding: utf-8 -*-
"""dbg_runjs.py — 验证 DrissionPage run_js 返回值是否可用。"""
import socket
import sys
import tempfile

from DrissionPage import ChromiumOptions, ChromiumPage

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
co = ChromiumOptions()
co.set_local_port(port)
co.set_user_data_path(tempfile.mkdtemp(prefix="dbg_runjs_"))
p = ChromiumPage(co)
p.get("https://qoder.com/users/sign-up")
p.wait.load_start()

for script in ("1+1", "document.title", "JSON.stringify({a:1})",
               "location.href", "typeof window.AliyunCaptcha"):
    try:
        v = p.run_js(script)
        print(repr(script), "run_js ->", repr(v))
    except Exception as e:
        print(repr(script), "run_js ERR", type(e).__name__, e)
    try:
        r = p.run_cdp("Runtime.evaluate",
                      expression=script, returnByValue=True)
        print("   cdp ->", repr(r))
    except Exception as e:
        print("   cdp ERR", type(e).__name__, e)

print("--- html len ---", len(p.html or ""))
print("--- tabs ---", [t.url for t in p.get_tabs()])
