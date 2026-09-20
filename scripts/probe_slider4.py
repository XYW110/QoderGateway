# -*- coding: utf-8 -*-
"""probe_slider4.py — 点「开始验证」后 dump 全部子元素（不过滤 id/class）。"""
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
(function () {
  var out = [];
  var root = document.querySelector('#captcha-element');
  if (!root) return JSON.stringify({err: 'no #captcha-element'});
  var walk = function (el, d) {
    if (!el || !el.tagName || out.length > 300) return;
    var b = null;
    try { b = el.getBoundingClientRect(); } catch (e) { b = null; }
    out.push({
      d: d,
      tag: el.tagName,
      id: el.id || '',
      cls: String(el.className || '').slice(0, 120),
      txt: (el.children.length === 0 ? String(el.textContent || '').trim().slice(0, 60) : ''),
      src: (el.getAttribute && (el.getAttribute('src') || '')) ? String(el.getAttribute('src')).slice(0, 90) : '',
      rect: b ? [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)] : null
    });
    var kids = el.children || [];
    for (var i = 0; i < kids.length; i++) walk(kids[i], d + 1);
  };
  walk(root, 0);
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
    co.set_user_data_path(tempfile.mkdtemp(prefix="probe_slider4_"))
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

    el = page.ele("#captcha-button", timeout=8)
    if el:
        print("click #captcha-button")
        el.click()
    else:
        print("no #captcha-button")
    time.sleep(5)

    data = None
    for i in range(6):
        raw = _js(page, JS)
        data = json.loads(raw) if raw else None
        if data and data.get("n", 0) > 3:
            break
        time.sleep(2)

    (LOGS / "slider4_dom.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("nodes:", (data or {}).get("n"))
    for n in (data or {}).get("nodes", []):
        pad = "  " * n.get("d", 0)
        print(f"{pad}{n['tag']} id={n['id']!r} cls={n['cls'][:40]!r} rect={n['rect']} "
              f"src={n['src'][:50]!r} txt={n['txt'][:24]!r}")
    try:
        page.get_screenshot(path=str(LOGS), name="slider4_shot.png")
    except Exception as e:
        print("shot err", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
