# -*- coding: utf-8 -*-
"""probe_slider_dom.py — 实测 qoder 注册页人机验证的真实 DOM。

流程：打开注册页 → 填姓名/邮箱 → 勾选 → 继续 → 填密码 → 继续
      → 等待人机验证出现 → dump iframe / script / 可疑元素 / 全局对象
输出：控制台 + logs/slider_dom.json
"""
from __future__ import annotations

import json
import random
import string
import sys
import time
from pathlib import Path

from DrissionPage import ChromiumOptions, ChromiumPage

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(r"D:\Work\Project\TestProject\QoderGateway")
OUT = ROOT / "logs" / "slider_dom.json"
SIGNUP = "https://qoder.com/users/sign-up"

JS_DUMP = r"""
(() => {
  const pick = (el) => ({
    tag: el.tagName.toLowerCase(),
    id: el.id || null,
    cls: (el.className && String(el.className).slice(0, 200)) || null,
    aria: el.getAttribute && el.getAttribute('aria-label'),
    src: el.getAttribute && el.getAttribute('src'),
    style: (el.getAttribute && el.getAttribute('style') || '').slice(0, 160),
    rect: (() => { try { const r = el.getBoundingClientRect();
      return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; }
      catch (e) { return null; } })(),
  });
  const q = (sel) => Array.from(document.querySelectorAll(sel)).slice(0, 40).map(pick);
  const globals = Object.keys(window).filter(k =>
    /captcha|slider|verify|challenge|aliyun|geetest|turnstile|nc_/i.test(k)).slice(0, 60);
  return {
    url: location.href,
    title: document.title,
    iframes: q('iframe'),
    scripts: Array.from(document.querySelectorAll('script[src]'))
      .map(s => s.src).filter(Boolean),
    dom: q('[id*="captcha"],[class*="captcha"],[id*="slider"],[class*="slider"],'
         + '[id*="verify"],[class*="verify"],[class*="puzzle"],[class*="drag"],[class*="slide"]'),
    inputs: q('input'),
    buttons: q('button'),
    globals,
    bodyText: (document.body.innerText || '').slice(0, 1200),
  };
})()
"""


def _rand(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


def _js(page, expr: str):
    """该环境下 page.run_js 恒返回 None，用 CDP Runtime.evaluate 取值。"""
    r = page.run_cdp("Runtime.evaluate", expression=expr, returnByValue=True)
    res = (r or {}).get("result") or {}
    return res.get("value")


def main() -> int:
    import socket
    import tempfile

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    profile = tempfile.mkdtemp(prefix="probe_slider_")
    co = ChromiumOptions()
    co.set_local_port(port)
    co.set_user_data_path(profile)
    page = ChromiumPage(co)

    print("open", SIGNUP)
    page.get(SIGNUP)
    page.wait.load_start()
    time.sleep(2)

    email = f"{_rand(6)}.{_rand(6)}{random.randint(100, 999)}@gmail.com"
    print("fill", email)
    page.ele("#basic_firstName").input("Test")
    page.ele("#basic_lastName").input("User")
    page.ele("#basic_email").input(email)
    cb = page.ele("css:.ant-checkbox-input")
    if cb:
        cb.parent().click()

    def click_submit() -> None:
        for sel in ('css:button[type="submit"]', 'tag:button'):
            try:
                b = page.ele(sel, timeout=2)
                if b:
                    b.click()
                    return
            except Exception:
                pass

    click_submit()
    time.sleep(2)
    try:
        page.wait.ele_displayed("#basic_password", timeout=30)
        page.ele("#basic_password").input("Abcd1234!xyz")
        click_submit()
        print("submitted password step")
    except Exception as e:
        print("password step skipped:", type(e).__name__)

    # 等滑块出现
    dump = None
    for i in range(20):
        time.sleep(2)
        try:
            raw = _js(page, "JSON.stringify(" + JS_DUMP + ")")
            d = json.loads(raw) if raw else None
        except Exception as e:
            print("dump err", type(e).__name__, e)
            continue
        if not d:
            print(f"[{i}] empty dump")
            continue
        has = bool(d.get("dom")) or bool(d.get("iframes"))
        print(f"[{i}] url={str(d.get('url'))[:80]} dom={len(d.get('dom') or [])} "
              f"iframes={len(d.get('iframes') or [])} globals={d.get('globals')}")
        dump = d
        if has:
            break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        (OUT.parent / "slider_page.html").write_text(page.html or "", encoding="utf-8")
    except Exception as e:
        print("html dump failed:", e)
    print("written", OUT)
    print("--- scripts (captcha-ish) ---")
    for s in (dump or {}).get("scripts", []):
        if any(k in s.lower() for k in ("captcha", "aliyun", "geetest", "challenge", "verify", "slider")):
            print(" ", s)
    print("--- globals ---", (dump or {}).get("globals"))
    print("--- iframes ---")
    for f in (dump or {}).get("iframes", []):
        print(" ", f)
    print("--- dom ---")
    for el in (dump or {}).get("dom", []):
        print(" ", el)
    print("--- bodyText ---")
    print(((dump or {}).get("bodyText") or "")[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
