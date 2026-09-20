# -*- coding: utf-8 -*-
"""probe_slider3.py — 精简版：dump 展开后滑块可用元素（id/class/rect）。"""
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
LOGS = ROOT / "logs"
SIGNUP = "https://qoder.com/users/sign-up"

JS = r"""
(() => {
  const out = [];
  const root = document.querySelector('#captcha-element') || document.body;
  const walk = (el) => {
    if (!el || !el.tagName) return;
    const id = el.id || '';
    const cls = String(el.className || '');
    let r = null;
    try { const b = el.getBoundingClientRect();
      r = {x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height)}; } catch (e) {}
    if ((id || cls) && r && r.w > 0) out.push({tag: el.tagName, id, cls: cls.slice(0,80), rect: r});
    Array.from(el.children || []).forEach(walk);
  };
  walk(root);
  return JSON.stringify({url: location.href, n: out.length, nodes: out});
})()
"""


def _js(page, expr: str):
    r = page.run_cdp("Runtime.evaluate", expression=expr, returnByValue=True)
    return ((r or {}).get("result") or {}).get("value")


def _rand(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


def main() -> int:
    import socket
    import tempfile

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    co = ChromiumOptions()
    co.set_local_port(port)
    co.set_user_data_path(tempfile.mkdtemp(prefix="probe_slider3_"))
    page = ChromiumPage(co)
    LOGS.mkdir(parents=True, exist_ok=True)

    page.get(SIGNUP)
    page.wait.load_start()
    time.sleep(2)
    page.ele("#basic_firstName").input("Test")
    page.ele("#basic_lastName").input("User")
    page.ele("#basic_email").input(f"{_rand(6)}.{_rand(6)}{random.randint(100, 999)}@gmail.com")
    cb = page.ele("css:.ant-checkbox-input")
    if cb:
        cb.parent().click()
    for sel in ('css:button[type="submit"]', 'tag:button'):
        b = page.ele(sel, timeout=2)
        if b:
            b.click()
            break
    time.sleep(2)
    page.wait.ele_displayed("#basic_password", timeout=30)
    page.ele("#basic_password").input("Abcd1234!xyz")
    for sel in ('css:button[type="submit"]', 'tag:button'):
        b = page.ele(sel, timeout=2)
        if b:
            b.click()
            break
    time.sleep(3)
    for sel in ("#captcha-button", "#captcha-element"):
        el = page.ele(sel, timeout=5)
        if el:
            print("click", sel)
            el.click()
            break
    time.sleep(5)

    data = None
    for i in range(6):
        raw = _js(page, JS)
        data = json.loads(raw) if raw else None
        if data and data.get("n"):
            break
        time.sleep(2)

    (LOGS / "slider3_dom.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("nodes:", (data or {}).get("n"))
    for n in (data or {}).get("nodes", []):
        print(" ", n)
    try:
        page.get_screenshot(path=str(LOGS), name="slider3_shot.png")
        print("shot saved")
    except Exception as e:
        print("shot err", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
