# -*- coding: utf-8 -*-
"""qoder 阿里云 Captcha（FeiLin 拼图）自动求解。

核心结论（离线实测 `logs/slider/{bg,puzzle}.png` 验证）：
  * 背景图里的缺口是「原图与白色遮罩的混合」：  bg ≈ a*piece + (1-a)*255
  * 拼图块内容 = 缺口处原始像素 → 用该混合模型反解 a，残差最小处即缺口。
    实测 gx=175 gy=6 a=0.325（quality 0.77），远优于直接内容匹配 / ddddocr。
  * 纯内容匹配、以及 ddddocr `simple_target=True` 都会把结果偏到 ~200，**不可用**。

对外接口：
  locate_gap(bg_png, puzzle_png) -> dict|None   纯图像，无浏览器依赖
  solve(page, ...) -> dict                      浏览器闭环：打开→定位→拖动→判定
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import random
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# ---------------------------------------------------------------- DOM 选择器
SEL_CIRCLE = "#captcha-button"
SEL_START = "#aliyunCaptcha-captcha-text"
SEL_START_LEFT = "#aliyunCaptcha-captcha-left"
SEL_POPUP = "#aliyunCaptcha-window-float"
SEL_BG = "#aliyunCaptcha-img"
SEL_PUZZLE = "#aliyunCaptcha-puzzle"
SEL_SLIDER = "#aliyunCaptcha-sliding-slider"
SEL_TEXT = "#aliyunCaptcha-sliding-text"
SEL_REFRESH = "#aliyunCaptcha-btn-refresh"

ALPHA_MIN = 8          # 判定「非透明」的 alpha 阈值
CORE_ALPHA = 200       # 内芯阈值（排除描边）
CORE_ERODE = 5         # 内芯腐蚀核


# ---------------------------------------------------------------- 小工具
def _erode(mask: np.ndarray, k: int) -> np.ndarray:
    """k x k 腐蚀（正方形结构元）。mask 为 0/1。"""
    r = k // 2
    h, w = mask.shape
    pad = np.pad(mask, r, mode="constant")
    acc = np.ones((h, w), dtype=bool)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            acc &= pad[r + dy:r + dy + h, r + dx:r + dx + w] > 0
    return acc.astype(np.uint8)


def _b64_to_bytes(data_url: str) -> bytes:
    if not data_url:
        return b""
    return base64.b64decode(data_url.split(",", 1)[1]) if "," in data_url else b""


def _to_bgr(img: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(img[:, :, ::-1])


# ---------------------------------------------------------------- 缺口定位
def locate_gap(bg_png: bytes, puzzle_png: bytes) -> dict | None:
    """返回缺口信息（背景图自然像素坐标系）或 None。"""
    if not bg_png or not puzzle_png:
        return None
    bg = np.array(Image.open(io.BytesIO(bg_png)).convert("RGB")).astype(np.float32)
    pz_im = Image.open(io.BytesIO(puzzle_png)).convert("RGBA")
    canvas_w, canvas_h = pz_im.size
    pa = np.array(pz_im)
    ys, xs = np.where(pa[:, :, 3] > ALPHA_MIN)
    if xs.size == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    piece = pa[y0:y1 + 1, x0:x1 + 1].astype(np.float32)
    ph, pw = piece.shape[:2]
    bh, bw = bg.shape[:2]
    if ph >= bh or pw >= bw:
        return None

    core = _erode((piece[:, :, 3] > CORE_ALPHA).astype(np.uint8), CORE_ERODE).astype(np.float32)
    n_core = float(core.sum())
    if n_core < 50:
        core = (piece[:, :, 3] > CORE_ALPHA).astype(np.float32)
        n_core = float(core.sum())
        if n_core < 20:
            return None

    dev = (piece[:, :, :3] - 255.0) * core[:, :, None]      # core 外置零
    denom = float((dev ** 2).sum())
    if denom <= 1e-6:
        return None

    img = bg - 255.0
    num = cv2.matchTemplate(img, dev, cv2.TM_CCORR)          # Σ_core dev*(bg-255)
    sq = (img ** 2).sum(axis=2).astype(np.float32)
    ssq = cv2.matchTemplate(sq, core, cv2.TM_CCORR)          # Σ_core (bg-255)^2
    resid = (ssq - (num ** 2) / denom) / n_core
    resid = np.nan_to_num(resid, nan=1e18, posinf=1e18, neginf=1e18)

    # 全图 argmin 仅作参考；真实匹配限制在 y0±3 行带内（见下）
    iy_all, _ = np.unravel_index(int(np.argmin(resid)), resid.shape)
    alpha = float(num[iy_all, int(np.argmin(resid[iy_all]))]) / denom
    med = float(np.median(resid))

    # 不变量：拼图块在 canvas 里的 y0 == 缺口 y（拖动只动 x，y 固定）。
    # 全图 argmin 会被背景其它强纹理行抢走（实测假匹配 gap_y=0/4，quality 0.01~0.32），
    # 因此把最优搜索限制在 y0±3 行带内，y 天然一致，x 在带内取最优。
    band_lo = max(0, y0 - 3)
    band_hi = min(resid.shape[0] - 1, y0 + 3)
    if band_hi < band_lo:                                    # y0 越界（模板放不下）→ 兜底全图
        band_lo = band_hi = int(iy_all)
    band = resid[band_lo:band_hi + 1]
    by, bx = np.unravel_index(int(np.argmin(band)), band.shape)
    iy, ix = band_lo + int(by), int(bx)
    best = float(resid[iy, ix])
    gx, gy = int(ix), int(iy)
    alpha = float(num[iy, ix]) / denom
    r_x = max(3, pw // 3)                                    # 屏蔽最优点取次优
    tmp = band.copy()
    tmp[:, max(0, gx - r_x):gx + r_x + 1] = 1e18
    second = float(tmp.min())
    quality = 1.0 - (best / second) if second > 0 else 0.0
    # 可信度闸门（band 内判别）：alpha 仍按白罩混合系数校验；quality 为带内最优/次优比
    bad: list[str] = []
    if not (0.05 <= alpha <= 0.90):
        bad.append("alpha=%.3f" % alpha)
    if abs(gy - y0) > 2:
        bad.append("gap_y=%d!=piece_y0=%d" % (gy, y0))
    if quality < 0.02:
        bad.append("quality=%.3f" % quality)
    return {
        "gap_x": gx, "gap_y": gy,
        "piece_x0": x0, "piece_y0": y0, "piece_w": pw, "piece_h": ph,
        "canvas_w": canvas_w, "canvas_h": canvas_h,
        "alpha": round(alpha, 4),
        "resid": round(best, 3), "second_resid": round(second, 3),
        "median_resid": round(med, 3), "quality": round(quality, 4),
        "bg_w": bw, "bg_h": bh,
        "valid": not bad, "invalid_reason": "; ".join(bad),
    }


# ---------------------------------------------------------------- CDP 基础
def _eval(page, expr: str):
    """本环境 page.run_js 恒返回 None，必须走 CDP Runtime.evaluate。"""
    r = page.run_cdp("Runtime.evaluate", expression=expr, returnByValue=True)
    return ((r or {}).get("result") or {}).get("value")


JS_SNAP = r"""
JSON.stringify((function () {
  function el(s) { return document.querySelector(s); }
  function info(s) {
    var e = el(s);
    if (!e) return null;
    var b = e.getBoundingClientRect();
    var cs = getComputedStyle(e);
    return {x: b.x, y: b.y, w: b.width, h: b.height, top: b.top, leftRect: b.left,
            cssLeft: cs.left, opacity: cs.opacity,
            display: cs.display, visibility: cs.visibility,
            natW: e.naturalWidth || 0, natH: e.naturalHeight || 0,
            cls: e.className, txt: (e.innerText || '').slice(0, 120)};
  }
  function src(s) { var e = el(s); return e ? (e.src || '') : ''; }
  return {
    url: location.href,
    popup: info('#aliyunCaptcha-window-float'),
    popupCls: (el('#aliyunCaptcha-window-float') || {}).className || '',
    bg: info('#aliyunCaptcha-img'),
    puzzle: info('#aliyunCaptcha-puzzle'),
    slider: info('#aliyunCaptcha-sliding-slider'),
    sliderBody: info('#aliyunCaptcha-sliding-body'),
    startText: (el('#aliyunCaptcha-captcha-text') || {}).innerText || '',
    slideText: (el('#aliyunCaptcha-sliding-text') || {}).innerText || '',
    certify: (el('#aliyunCaptcha-certifyId') || {}).innerText || '',
    bgSrc: src('#aliyunCaptcha-img'),
    puzzleSrc: src('#aliyunCaptcha-puzzle'),
    otp: !!el('#basic_otp, input[autocomplete="one-time-code"], #basic_code'),
    captchaHost: (function(){ var h = el('#captcha-element');
      return h ? (h.innerText || '').replace(/\s+/g, ' ').slice(0, 200) : ''; })()
  };
})())
"""


def snapshot(page) -> dict:
    raw = _eval(page, JS_SNAP)
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _rect(page, sel: str) -> dict | None:
    v = _eval(page, "(function(){var e=document.querySelector('%s');if(!e)return null;"
                    "var r=e.getBoundingClientRect();"
                    "if(r.width<1||r.height<1)return null;"
                    "return JSON.stringify({x:r.x,y:r.y,w:r.width,h:r.height});})()" % sel)
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


def _mouse(page, mtype: str, x: float, y: float, buttons: int = 1) -> None:
    page.run_cdp("Input.dispatchMouseEvent", type=mtype, x=round(float(x), 2), y=round(float(y), 2),
                 button="left", buttons=buttons, clickCount=1)


def real_click(page, sel: str) -> bool:
    """真实（受信任）点击元素中心：JS .click() 是 untrusted，阿里云会拒绝。"""
    r = _rect(page, sel)
    if not r:
        return False
    cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
    _mouse(page, "mouseMoved", cx, cy, 0)
    time.sleep(0.05)
    _mouse(page, "mousePressed", cx, cy, 1)
    time.sleep(random.uniform(0.05, 0.12))
    _mouse(page, "mouseReleased", cx, cy, 0)
    return True


def _puzzle_left(page) -> float:
    v = _eval(page, "parseFloat(getComputedStyle(document.querySelector('%s')).left)||0"
              % SEL_PUZZLE)
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def popup_open(snap: dict) -> bool:
    sp = snap.get("popup") or {}
    return bool(sp) and (sp.get("w") or 0) > 10 and "window-show" in (snap.get("popupCls") or "")


# ---------------------------------------------------------------- 打开验证
def wait_widget(page, *, timeout: float = 45.0, poll: float = 1.5) -> dict | None:
    """等阿里云 widget 挂载（qoder 实测约 14s）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        snap = snapshot(page)
        n = _eval(page, "document.querySelectorAll('[id^=\"aliyunCaptcha\"]').length") or 0
        if snap.get("bg") and snap.get("puzzle") and snap.get("slider") and n:
            return snap
        time.sleep(poll)
    return None


def open_verify(page, *, timeout: float = 45.0) -> dict | None:
    """真实点击 #captcha-button / 「点击开始验证」→ 等弹窗 window-show。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        snap = snapshot(page)
        if popup_open(snap):
            return snap
        hit = None
        for sel in (SEL_START, SEL_START_LEFT, SEL_CIRCLE):
            if _rect(page, sel):
                hit = sel
                break
        if hit:
            real_click(page, hit)
            # 点击后给足窗口，避免重复点击把弹窗点关
            for _ in range(10):
                time.sleep(0.5)
                snap = snapshot(page)
                if popup_open(snap):
                    return snap
        time.sleep(1.2)
    return None


def refresh(page) -> bool:
    """真实点击刷新按钮换一题。"""
    for sel in (SEL_REFRESH, "#aliyunCaptcha-sliding-body"):
        if sel == SEL_REFRESH and _rect(page, sel):
            return real_click(page, sel)
    return False


# ---------------------------------------------------------------- 目标换算
def target_left(snap: dict, gap: dict) -> float | None:
    """算 #aliyunCaptcha-puzzle 需要设置的 computedStyle.left（CSS px，绝对值）。

    注意：snapshot 里的 pz["x"] 是 getBoundingClientRect 结果，**已经包含当前 left**，
    所以必须先用当前 computedStyle.left 还原容器 x，否则第二次尝试会算出「相对增量」
    而把拼图拖回起点（实测踩坑：gap=248 却算出 target=0.77）。
    """
    bg, pz = snap.get("bg"), snap.get("puzzle")
    if not bg or not pz or not bg.get("w") or not bg.get("natW") or not pz.get("natW"):
        return None
    bg_scale = bg["w"] / bg["natW"]                      # 例：300/296
    pz_scale = pz["w"] / pz["natW"]                      # 例：52/52 = 1
    gap_css_x = bg["x"] + gap["gap_x"] * bg_scale        # 缺口左缘视口 CSS 坐标
    piece_css_off = gap["piece_x0"] * pz_scale           # 块在 canvas 内的左偏移
    try:
        cur_left = float(str(pz.get("cssLeft", "0")).replace("px", "").strip() or 0)
    except Exception:
        cur_left = 0.0
    container_x = pz["x"] - cur_left                     # 还原定位容器视口 x
    return gap_css_x - container_x - piece_css_off


# ---------------------------------------------------------------- 拖动闭环
def drag_to(page, slider: dict, tgt_left: float, *, tol: float = 0.5,
            max_steps: int = 90, dump_dir=None) -> dict:
    """闭环拖动：每步读 #aliyunCaptcha-puzzle 的 computedStyle.left，斜率自适应单调逼近。

    容差必须小：实测差 1.07px 就会被阿里云判失败（s3），差 0.26px 才通过（s1）。
    """
    x0 = slider["x"] + slider["w"] / 2
    y0 = slider["y"] + slider["h"] / 2
    sx = x0
    l0 = _puzzle_left(page)
    _mouse(page, "mouseMoved", sx, y0, 0)
    time.sleep(0.08)
    _mouse(page, "mousePressed", sx, y0, 1)
    time.sleep(random.uniform(0.10, 0.20))

    trace: list[float] = []
    slope, prev_x, prev_l = 1.0, None, l0
    cur = l0
    t0 = time.time()
    moved = False
    for i in range(max_steps):
        cur = _puzzle_left(page)
        if abs(cur - l0) > 0.5:
            moved = True
        need = tgt_left - cur
        if abs(need) <= tol:
            break
        if prev_x is not None and abs(sx - prev_x) > 0.4:
            obs = (cur - prev_l) / (sx - prev_x)
            if 0.05 < obs < 20:
                slope = 0.45 * slope + 0.55 * obs          # 平滑观测斜率
        prev_x, prev_l = sx, cur
        step = (need / max(slope, 0.15)) * random.uniform(0.6, 0.85)
        step = min(max(step, 1.0), 40.0) if need > 0 else max(min(step, -1.0), -12.0)
        sx += step
        _mouse(page, "mouseMoved", sx, y0 + random.uniform(-1.2, 1.2), 1)
        trace.append(round(cur, 1))
        time.sleep(random.uniform(0.030, 0.060))
        if i == 8 and not moved:
            break                                            # 完全没动 → 尽早放弃
        if time.time() - t0 > 20:
            break
    # 末段精修：用观测斜率做精确补偿，把残差压到 0.25px 内再松手
    for _ in range(8):
        cur = _puzzle_left(page)
        need = tgt_left - cur
        if abs(need) <= 0.25:
            break
        sx += need / max(slope, 0.2)
        _mouse(page, "mouseMoved", sx, y0, 1)
        time.sleep(0.06)
    time.sleep(random.uniform(0.15, 0.40))
    _mouse(page, "mouseReleased", sx, y0, 0)
    final = _puzzle_left(page)
    out = {"start_left": round(l0, 2), "target_left": round(tgt_left, 2),
           "final_left": round(final, 2), "diff": round(tgt_left - final, 2),
           "steps": len(trace), "slope": round(slope, 3),
           "slider_dx": round(sx - x0, 1), "trace_tail": trace[-10:]}
    if dump_dir:
        p = Path(dump_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "drag.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    return out


# ---------------------------------------------------------------- 判定
PASS_HINTS = ("验证成功", "验证通过", "成功", "通过")
FAIL_HINTS = ("验证失败", "失败", "错误", "再试", "重试", "请重新")
# 弹窗关闭后若提示回到「点击开始验证」等 → 属于失败重置，绝不可当作通过
RESET_HINTS = ("点击", "开始验证", "拖动", "完成拼图")


def judge(page, *, timeout: float = 25.0) -> dict:
    """滑动后判定是否通过：弹窗关闭 / OTP 框出现 / 成功文案 → 通过。

    注意 timeout 不能太短：实测通过后弹窗还会停留展示成功动画，
    15s 容易误判失败（s2 案例），故默认 25s。
    """
    t0 = time.time()
    last: dict = {}
    empty = 0
    while time.time() - t0 < timeout:
        snap = snapshot(page)
        if not snap:
            empty += 1
            if empty >= 3:                                # 连续空快照才算异常
                return {"pass": False, "reason": "no-snapshot"}
            time.sleep(0.6)
            continue
        empty = 0
        last = snap
        cls = snap.get("popupCls") or ""
        st = snap.get("startText") or ""
        if not popup_open(snap):
            # 弹窗消失有两种，靠 #aliyunCaptcha-captcha-text 区分：
            #   真通过  → 「验证通过!」（实测）
            #   失败重置 → 回到「点击开始验证」
            host = snap.get("captchaHost") or ""
            if any(k in st for k in ("通过", "成功")) or any(k in host for k in ("通过", "成功")):
                return {"pass": True, "reason": "popup-closed-pass", "cls": cls,
                        "startText": st, "url": snap.get("url"), "host": host[:160]}
            if any(k in st for k in RESET_HINTS):
                return {"pass": False, "reason": "closed-not-passed", "cls": cls,
                        "startText": st, "url": snap.get("url")}
            return {"pass": True, "reason": "popup-closed-weak", "cls": cls,
                    "startText": st, "url": snap.get("url"), "host": host[:160]}
        if snap.get("otp"):
            return {"pass": True, "reason": "otp-field", "cls": cls}
        host = snap.get("captchaHost") or ""
        if any(k in host for k in PASS_HINTS):
            return {"pass": True, "reason": "success-text", "host": host[:160]}
        txt = (snap.get("slideText") or "") + " " + host
        if any(k in txt for k in FAIL_HINTS):
            return {"pass": False, "reason": "fail-text", "text": txt[:160], "cls": cls}
        time.sleep(0.6)
    sp = last.get("popup") or {}
    return {"pass": False, "reason": "timeout", "cls": last.get("popupCls"),
            "text": last.get("slideText"), "popup_w": sp.get("w")}


# ---------------------------------------------------------------- 总入口
def solve(page, *, dump_dir=None, rounds: int = 3, open_popup: bool = True,
          open_timeout: float = 45.0) -> dict:
    """完整求解：打开弹窗 → 定位 → 拖动 → 判定；失败换题重试。"""
    log: list[dict] = []
    seen: set[str] = set()
    if dump_dir:
        Path(dump_dir).mkdir(parents=True, exist_ok=True)

    if open_popup:
        snap = open_verify(page, timeout=open_timeout)
        if snap is None:
            w = wait_widget(page, timeout=min(open_timeout, 20.0))
            if w is None:
                return {"ok": False, "reason": "no-widget", "log": log}
            snap = open_verify(page, timeout=open_timeout)
            if snap is None:
                return {"ok": False, "reason": "no-popup", "log": log}

    for rd in range(rounds):
        if rd > 0:
            # 上一轮失败后弹窗可能已关闭/被重置 → 重新打开再战
            if open_verify(page, timeout=open_timeout) is None:
                log.append({"round": rd, "error": "reopen-failed"})
                break
        snap = snapshot(page)
        bg_b = _b64_to_bytes(snap.get("bgSrc") or "")
        pz_b = _b64_to_bytes(snap.get("puzzleSrc") or "")
        item: dict = {"round": rd}
        # 换题没生效（bg/puzzle 与已试过的一致）→ 再拖也是重复提交同一个错误答案，直接收手
        ph_ = hashlib.md5(bg_b + b"|" + pz_b).hexdigest()
        if ph_ in seen:
            item["error"] = "same-puzzle-as-before"
            log.append(item)
            break
        seen.add(ph_)
        if dump_dir:
            d = Path(dump_dir)
            if bg_b:
                (d / f"r{rd}_bg.png").write_bytes(bg_b)
            if pz_b:
                (d / f"r{rd}_puzzle.png").write_bytes(pz_b)
        gap = locate_gap(bg_b, pz_b)
        item["gap"] = gap
        if gap is None:
            item["error"] = "locate_gap failed"
            log.append(item)
            refresh(page)
            time.sleep(2.2)
            continue
        if not gap.get("valid", True):
            item["error"] = "gap-invalid: " + (gap.get("invalid_reason") or "")
            log.append(item)                     # 假匹配绝不拿去拖
            refresh(page)
            time.sleep(2.2)
            continue
        if abs(gap["gap_y"] - gap["piece_y0"]) > 3:
            item["warn_y"] = [gap["gap_y"], gap["piece_y0"]]
        tgt = target_left(snap, gap)
        item["target_left"] = None if tgt is None else round(tgt, 2)
        if tgt is None or not snap.get("slider"):
            item["error"] = "no target/slider"
            log.append(item)
            refresh(page)
            time.sleep(2.2)
            continue
        item["drag"] = drag_to(page, snap["slider"], tgt, dump_dir=dump_dir)
        j = judge(page)
        item["judge"] = j
        log.append(item)
        if j.get("pass"):
            return {"ok": True, "round": rd, "gap": gap, "drag": item["drag"],
                    "judge": j, "weak": j.get("reason") == "popup-closed-weak", "log": log}
        if rd < rounds - 1:
            refresh(page)
            time.sleep(2.2)
    return {"ok": False, "reason": "all-rounds-failed", "log": log}
