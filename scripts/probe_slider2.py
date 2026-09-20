# -*- coding: utf-8 -*-
"""probe_slider2.py — 点开阿里云 Captcha，dump 展开后的滑块 DOM 与图片资源。

输出：logs/slider2_dom.json、logs/slider2_shot.png，以及可下载的 bg/puzzle dataURL 落盘
"""
from __future__ import annotations

import base64
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

JS_EXPANDED = r"""
(() => {
  const pick = (el) => ({
    tag: el.tagName.toLowerCase(),
    id: el.id || null,
    cls: (el.className && String(el.className).slice(0, 200)) || null,
    style: (el.getAttribute && el.getAttribute('style') || '').slice(0, 200),
    src: (el.getAttribute && el.getAttribute('src') || '').slice(0, 120),
    rect: (() => { try { const r = el.getBoundingClientRect();
      return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; }
      catch (e) { return null; } })(),
  });
  const root = document.querySelector('#captcha-element') || document;
  const all = Array.from(root.querySelectorAll('*')).filter(el =>
      /puzzle|slider|slide|bg|captcha|drag|handle|track|refresh|close|loading/i
        .test((el.id || '') + ' ' + String(el.className || '')));
  const canvasImgs = Array.from(root.querySelectorAll('img,canvas')).map(el => ({
    ...pick(el),
    dataUrl: el.tagName === 'IMG' ? (el.src || '') :
      (() => { try { return el.toDataURL('image/png'); } catch (e) { return ''; } })(),
  }));
  return {
    url: location.href,
    config: window.AliyunCaptchaConfig || null,
    scene: window.captchaScene || null,
    captchaRootHTML: (root.innerHTML || '').slice(0, 6000),
    nodes: all.map(pick),
    images: canvasImgs.map(i => ({...i, dataUrl: (i.dataUrl || '').slice(0, 80) + (i.dataUrl || '').length)),
  };
})()
"""

JS_IMAGES = r"""
(() => {
  const out = [];
  const root = document.querySelector('#captcha-element') || document;
  root.querySelectorAll('img,canvas').forEach((el, i) => {
    let u = '';
    if (el.tagName === 'IMG') u = el.src || '';
    else { try { u = el.toDataURL('image/png'); } catch (e) { u = ''; } }
    out.push({i, tag: el.tagName, w: el.width, h: el.height, id: el.id || null,
              cls: String(el.className || ''), url: u});
  });
  return JSON.stringify(out);
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
    co.set_user_data_path(tempfile.mkdtemp(prefix="probe_slider2_"))
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
    print("submitted password")
    time.sleep(3)

    # 点开人机验证（阿里云 Captcha 通常需要一个按钮触发）
    for sel in ("#captcha-button", "#captcha-element"):
        try:
            el = page.ele(sel, timeout=5)
            if el:
                print("click", sel)
                el.click()
                break
        except Exception as e:
            print("click fail", sel, type(e).__name__)
    time.sleep(4)

    dump = None
    for i in range(10):
        try:
            raw = _js(page, "JSON.stringify(" + JS_EXPANDED + ")")
            dump = json.loads(raw) if raw else None
        except Exception as e:
            print("dump err", type(e).__name__, e)
        if dump and dump.get("nodes"):
            print(f"[{i}] nodes={len(dump['nodes'])}")
            break
        print(f"[{i}] nodes={len((dump or {}).get('nodes') or [])}")
        time.sleep(2)

    (LOGS / "slider2_dom.json").write_text(
        json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        page.get_screenshot(path=str(LOGS), name="slider2_shot.png")
    except Exception as e:
        print("shot err", e)

    # 图片资源落盘（bg / puzzle）
    try:
        imgs = json.loads(_js(page, JS_IMAGES) or "[]")
    except Exception:
        imgs = []
    for it in imgs:
        u = it.get("url") or ""
        if u.startswith("data:image"):
            b64 = u.split(",", 1)[1]
            (LOGS / f"slider2_img_{it['i']}_{it.get('tag')}.png").write_bytes(base64.b64decode(b64))
            print("saved img", it["i"], it.get("tag"), it.get("w"), "x", it.get("h"))
        else:
            print("img(no dataurl)", it["i"], it.get("tag"), (u or "")[:80])

    print("--- config ---", (dump or {}).get("config"))
    print("--- nodes ---")
    for n in (dump or {}).get("nodes", []):
        print(" ", n)
    print("--- summary ---")
    print("written logs/slider2_dom.json, logs/slider2_shot.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
