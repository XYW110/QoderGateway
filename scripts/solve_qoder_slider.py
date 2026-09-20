# -*- coding: utf-8 -*-
"""solve_qoder_slider.py — qoder 阿里云 Captcha 滑块求解（DrissionPage 原生，独立调试用）。

流程：注册页填表 → 提交密码 → 点「点击开始验证」弹出滑块
      → 取背景/拼图 → ddddocr 求缺口 → 拖 #aliyunCaptcha-sliding-slider（单调正向）
      → 校验是否通过（弹窗消失 / 进入 OTP 页）
"""
from __future__ import annotations

import base64
import json
import math
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
LOGS = ROOT / "logs" / "slider"
SIGNUP = "https://qoder.com/users/sign-up"

SEL_CIRCLE = "#captcha-button"
SEL_START = "#aliyunCaptcha-captcha-text"
SEL_START_LEFT = "#aliyunCaptcha-captcha-left"
SEL_POPUP = "#aliyunCaptcha-window-float"
SEL_BG = "#aliyunCaptcha-img"
SEL_PUZZLE = "#aliyunCaptcha-puzzle"
SEL_SLIDER = "#aliyunCaptcha-sliding-slider"
SEL_TEXT = "#aliyunCaptcha-sliding-text"

JS_STATE = r"""
JSON.stringify((function () {
  function rect(sel) {
    var el = document.querySelector(sel);
    if (!el) return null;
    var b = el.getBoundingClientRect();
    var cs = getComputedStyle(el);
    return {x: b.x, y: b.y, w: b.width, h: b.height,
            left: cs.left, display: cs.display, visibility: cs.visibility,
            natural: {w: el.naturalWidth || 0, h: el.naturalHeight || 0}};
  }
  function src(sel) {
    var el = document.querySelector(sel);
    return el ? (el.src || el.getAttribute('src') || '') : '';
  }
  return {
    url: location.href,
    popup: rect('#aliyunCaptcha-window-float'),
    popupCls: (document.querySelector('#aliyunCaptcha-window-float') || {}).className || '',
    bg: rect('#aliyunCaptcha-img'),
    puzzle: rect('#aliyunCaptcha-puzzle'),
    slider: rect('#aliyunCaptcha-sliding-slider'),
    sliderLeft: rect('#aliyunCaptcha-sliding-left'),
    text: (document.querySelector('#aliyunCaptcha-sliding-text') || {}).innerText || '',
    startText: (document.querySelector('#aliyunCaptcha-captcha-text') || {}).innerText || '',
    certify: (document.querySelector('#aliyunCaptcha-certifyId') || {}).innerText || '',
    bgSrc: src('#aliyunCaptcha-img').slice(0, 60),
    puzzleSrc: src('#aliyunCaptcha-puzzle').slice(0, 60),
    bgLen: src('#aliyunCaptcha-img').length,
    puzzleLen: src('#aliyunCaptcha-puzzle').length,
  };
})())
"""


def _js(page, expr: str):
    r = page.run_cdp("Runtime.evaluate", expression=expr, returnByValue=True)
    res = (r or {}).get("result") or {}
    v = res.get("value")
    return v


def _state(page) -> dict:
    raw = _js(page, JS_STATE)
    return json.loads(raw) if raw else {}


def _rand(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


def _b64_to_bytes(data_url: str) -> bytes:
    return base64.b64decode(data_url.split(",", 1)[1]) if "," in data_url else b""


def _get_src(page, sel: str) -> str:
    return _js(page, f"(document.querySelector('{sel}')||{{}}).src || ''") or ""


def solve_gap(bg_bytes: bytes, puzzle_bytes: bytes, disp_w: float, natural_w: int):
    """返回 (目标缺口左缘 CSS 像素, 诊断信息)。"""
    try:
        import ddddocr  # noqa
    except Exception as e:
        return None, {"ddddocr": f"missing: {type(e).__name__}"}
    det = getattr(solve_gap, "_det", None)
    if det is None:
        import ddddocr as _d
        det = _d.DdddOcr(det=False, ocr=False, show_ad=False)
        solve_gap._det = det
    res = det.slide_match(puzzle_bytes, bg_bytes, simple_target=False)
    tx = int(res.get("target_x", -1))
    conf = float(res.get("confidence", 0.0))
    diag = {"target_x": tx, "confidence": conf, "natural_w": natural_w, "disp_w": disp_w}
    if tx < 0:
        return None, diag
    scale = (disp_w / natural_w) if natural_w else 1.0
    return round(tx * scale), diag


def _mouse(page, mtype: str, x: float, y: float) -> None:
    page.run_cdp("Input.dispatchMouseEvent", type=mtype, x=x, y=y,
                 button="left", buttons=1 if mtype != "mouseReleased" else 0,
                 clickCount=1)


def drag_to(page, start_x: float, y: float, target_pz: float,
            puzzle_sel: str = SEL_PUZZLE, max_steps: int = 60) -> dict:
    """从滑条起点拖动，闭环逼近拼图位移 target_pz（单调正向，绝不回拉）。"""
    def pz() -> float:
        v = _js(page, f"parseFloat(getComputedStyle(document.querySelector('{puzzle_sel}')).left)||0")
        return float(v or 0)

    _mouse(page, "mousePressed", start_x, y)
    time.sleep(0.12)
    cur = start_x
    last_pz = pz()
    trace = [round(last_pz, 1)]
    for step in range(max_steps):
        remain = target_pz - last_pz
        if abs(remain) <= 1.5:
            break
        # 非线性补偿：拼图位移对滑动位移约为二次关系，先按剩余量给步长并做阻尼
        delta = max(1.0, min(remain * 0.55, 60))
        if remain < 0:
            delta = max(0.5, remain * 0.5)  # 实际上不应回拉；此处仅用于过冲极小时收敛
        cur += delta
        _mouse(page, "mouseMoved", cur, y)
        time.sleep(0.035)
        new_pz = pz()
        if new_pz - last_pz > 0.01:
            # 若比例已知，用观测校准剩余步长
            last_pz = new_pz
        else:
            last_pz = new_pz
        trace.append(round(last_pz, 1))
    _mouse(page, "mouseReleased", cur, y)
    return {"final_pz": round(pz(), 1), "target_pz": round(target_pz, 1), "trace": trace[-12:]}


def main() -> int:
    import socket
    import tempfile

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    co = ChromiumOptions()
    co.set_local_port(port)
    co.set_user_data_path(tempfile.mkdtemp(prefix="solve_slider_"))
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

    # 1) 点 #captcha-button → 出现「点击开始验证」
    for attempt in range(10):
        el = page.ele(SEL_CIRCLE, timeout=3)
        n = _js(page, "document.querySelectorAll('[id^=\"aliyunCaptcha\"]').length") or 0
        st0 = _js(page, "(document.querySelector('#aliyunCaptcha-captcha-text')||{}).innerText||''") or ""
        print(f"[boot {attempt}] #captcha-button={'yes' if el else 'no'} aliyunNodes={n} startText={st0!r}")
        if el and n > 0:
            break
        time.sleep(2)
    if el:
        try:
            el.click()
            print("clicked #captcha-button")
        except Exception as e:
            print("click #captcha-button failed:", type(e).__name__, e)
    time.sleep(3)

    # 2) 点「点击开始验证」打开弹窗
    for attempt in range(8):
        st = _state(page)
        popup = st.get("popup") or {}
        n = _js(page, "document.querySelectorAll('[id^=\"aliyunCaptcha\"]').length") or 0
        print(f"[open {attempt}] popupW={popup.get('w')} nodes={n} "
              f"startText={st.get('startText')!r} text={st.get('text')!r}")
        if (popup.get("w") or 0) > 10:
            print("popup open")
            break
        clicked = False
        for sel in (SEL_START, SEL_START_LEFT, SEL_CIRCLE):
            try:
                e = page.ele(sel, timeout=2)
                if e:
                    e.click()
                    clicked = True
                    print("clicked", sel)
                    break
            except Exception as ex:
                print("click fail", sel, type(ex).__name__)
        time.sleep(2)
        if not clicked:
            print("no start button found")
            break

    st = _state(page)
    print("state:", json.dumps({k: st.get(k) for k in
                                ("url", "popup", "puzzle", "slider", "text", "startText", "certify")},
                               ensure_ascii=False))
    (LOGS / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3) 取背景 / 拼图
    bg_url = _get_src(page, SEL_BG)
    pz_url = _get_src(page, SEL_PUZZLE)
    (LOGS / "bg.png").write_bytes(_b64_to_bytes(bg_url))
    (LOGS / "puzzle.png").write_bytes(_b64_to_bytes(pz_url))
    print("bg bytes", len(_b64_to_bytes(bg_url)), "| puzzle bytes", len(_b64_to_bytes(pz_url)))

    target, diag = solve_gap(_b64_to_bytes(bg_url), _b64_to_bytes(pz_url),
                             (st.get("bg") or {}).get("w") or 0,
                             ((st.get("bg") or {}).get("natural") or {}).get("w") or 0)
    print("gap:", target, diag)
    if target is None:
        try:
            page.get_screenshot(path=str(LOGS), name="shot_fail.png")
        except Exception:
            pass
        return 2

    # 4) 拖动
    srect = st.get("slider") or {}
    if not srect.get("w"):
        print("slider not visible")
        return 3
    sx = srect["x"] + srect["w"] / 2
    sy = srect["y"] + srect["h"] / 2
    print(f"drag from ({sx:.0f},{sy:.0f}) target_pz={target}")
    res = drag_to(page, sx, sy, float(target))
    print("drag result:", res)

    time.sleep(2)
    after = _state(page)
    print("after:", json.dumps({k: after.get(k) for k in ("url", "popup", "popupCls", "text", "certify")},
                               ensure_ascii=False))
    try:
        page.get_screenshot(path=str(LOGS), name="shot_after.png")
    except Exception:
        pass
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
